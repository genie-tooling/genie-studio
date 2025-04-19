# pm/handlers/change_queue_handler.py
import re
import uuid
import difflib
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSlot, Qt, QTimer
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox, QApplication
from loguru import logger

from ..ui.change_queue_widget import ChangeQueueWidget
from ..ui.diff_dialog import DiffDialog
from ..core.workspace_manager import WorkspaceManager
from ..ui.controllers.status_bar_controller import StatusBarController

# Import the patch library safely
try:
    import patch as patch_library
    HAS_PATCH_LIB = True
except ImportError:
    HAS_PATCH_LIB = False
    logger.warning("Optional library 'python-patch' not found. 'Apply as Patch' feature will be disabled.")

def apply_patch(original_content: str, patch_str: str) -> Optional[str]:
    """Attempts to apply a unified diff patch to the original content."""
    if not HAS_PATCH_LIB:
        logger.error("Patch application failed: 'python-patch' library not installed.")
        return None
    try:
        # Ensure patch string is bytes
        patch_bytes = patch_str.encode('utf-8')
        # The library expects the original content as bytes as well
        original_bytes = original_content.encode('utf-8')

        patch_set = patch_library.fromstring(patch_bytes)
        # The apply method modifies the original bytes in-place if successful,
        # or returns False on failure. We need to pass a copy.
        result = patch_set.apply(original_bytes) # Apply to original bytes

        if result is not False: # Library returns False on failure, original bytes on success
             # Decode result back to string (assuming utf-8)
             logger.debug("Patch library apply() successful.")
             return result.decode('utf-8')
        else:
             logger.warning("Patch application failed (patch library returned False). Hunks may not apply.")
             return None
    except Exception as e:
        logger.exception(f"Error applying patch: {e}")
        return None

class ChangeQueueHandler(QObject):
    """Handles logic for the Change Queue (viewing, applying, rejecting)."""

    # --- FIX: Corrected constructor signature ---
    def __init__(self,
                 widget: ChangeQueueWidget,
                 workspace: WorkspaceManager,
                 status_bar: StatusBarController,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        if not isinstance(widget, ChangeQueueWidget): raise TypeError("widget must be ChangeQueueWidget")
        if not isinstance(workspace, WorkspaceManager): raise TypeError("workspace must be WorkspaceManager")
        if not isinstance(status_bar, StatusBarController): raise TypeError("status_bar must be StatusBarController")

        self._widget = widget
        self._workspace = workspace
        self._status_bar = status_bar
        self._connect_pyqtSignals()
        logger.info("ChangeQueueHandler initialized.")
    # --- End Signature Fix ---

    def _connect_pyqtSignals(self):
        self._widget.view_requested.connect(self._handle_view_request)
        self._widget.apply_requested.connect(self._handle_apply_request)
        self._widget.reject_requested.connect(self._handle_reject_request)

    def _find_original_block(self, original_lines: List[str], proposed_lines: List[str]) -> Tuple[int, int, str]:
        """Finds the best matching block using SequenceMatcher and signature fallback."""
        if not proposed_lines or not original_lines:
             return -1, -1, 'none'

        # SequenceMatcher Approach
        matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines, autojunk=False)
        match = matcher.find_longest_match(0, len(original_lines), 0, len(proposed_lines))

        if match.size > 0:
            # Check for near-perfect match at the start of proposed content
            if match.b == 0 and match.size >= len(proposed_lines) * 0.8:
                 start_index = match.a; end_index = match.a + match.size - 1
                 logger.debug(f"Found 'exact' block match via SM: Orig lines {start_index+1}-{end_index+1}")
                 return start_index, end_index, 'exact'

            # Check overall ratio for partial match
            ratio = matcher.ratio()
            logger.debug(f"SequenceMatcher ratio: {ratio:.3f}")
            if ratio > 0.6: # Threshold for considering it a 'partial' match
                start_index = match.a; end_index = match.a + match.size - 1
                logger.debug(f"Found 'partial' block match via SM ratio: Orig lines {start_index+1}-{end_index+1}")
                return start_index, end_index, 'partial'

        # Signature Fallback (if SM fails or gives low confidence)
        first_proposed_line = next((line for line in proposed_lines if line.strip()), None)
        if first_proposed_line:
            # Regex to find common definition starts (adjust as needed)
            sig_match = re.match(r"^\s*(async\s+)?(def|class)\s+(\w+)\s*\(", first_proposed_line)
            if sig_match:
                signature_start = sig_match.group(0).strip() # Use the whole matched signature start
                try:
                    start_index = -1
                    # Find the first line in original containing this signature start
                    for i, line in enumerate(original_lines):
                        if signature_start in line.strip(): # Simple containment check
                            start_index = i; break

                    if start_index != -1:
                        # Try to find the block end based on indentation
                        start_indent = len(original_lines[start_index]) - len(original_lines[start_index].lstrip())
                        end_index = start_index
                        for i in range(start_index + 1, len(original_lines)):
                            line = original_lines[i];
                            if not line.strip(): continue # Skip empty lines for indent check
                            current_indent = len(line) - len(line.lstrip())
                            # Stop if line is not empty and indent is less or equal
                            if current_indent <= start_indent:
                                end_index = i - 1 # Previous line was the end
                                break
                            end_index = i # Extend block to this line
                        else: # If loop finished without break, block goes to end of file
                            end_index = len(original_lines) - 1

                        logger.debug(f"Found 'exact' block match via signature fallback: Orig lines {start_index+1}-{end_index+1}")
                        return start_index, end_index, 'exact' # Treat signature match as 'exact'
                except Exception as e:
                    logger.error(f"Error during signature matching fallback: {e}")

        logger.warning("Could not find matching block in original content.");
        return -1, -1, 'none'

    @pyqtSlot(dict)
    def _handle_view_request(self, change_data: Dict):
        logger.debug(f"CQH: Handling view request for change ID {change_data.get('id')}")
        original_full_content = change_data.get('original_full_content');
        original_block_content = change_data.get('original_block_content')
        original_start_line = change_data.get('original_start_line');
        original_end_line = change_data.get('original_end_line')
        proposed_content = change_data.get('proposed_content');
        match_confidence = change_data.get('match_confidence')

        if original_full_content is None or proposed_content is None or match_confidence is None:
             logger.error("View request missing essential data.");
             QMessageBox.warning(self._widget.window(),"View Error", "Could not display change: Missing data.");
             return

        dialog = DiffDialog(
            original_full_content=original_full_content,
            original_block_content=original_block_content,
            original_start_line=original_start_line,
            original_end_line=original_end_line,
            proposed_content=proposed_content,
            match_confidence=match_confidence,
            parent=self._widget.window()
        )

        if dialog.exec():
            insertion_line = getattr(dialog, 'insertion_line', -1);
            apply_mode = getattr(dialog, 'apply_mode', 'reject')
            logger.info(f"DiffDialog accepted. Apply mode: '{apply_mode}', Insertion line: {insertion_line}")

            if apply_mode == 'insert':
                change_data['insertion_line'] = insertion_line; change_data['apply_type'] = 'insert'
            elif apply_mode == 'auto_replace':
                change_data['apply_type'] = 'replace'
            elif apply_mode == 'patch':
                change_data['apply_type'] = 'patch'
            else:
                logger.warning(f"DiffDialog accepted unexpected mode '{apply_mode}'. Assuming reject.");
                return # Don't proceed if mode is unknown

            # Apply the single change determined by the dialog
            self._handle_apply_request([change_data])
        else:
            logger.info("DiffDialog closed or rejected.")

    @pyqtSlot(list)
    def _handle_apply_request(self, selected_changes_data: List[Dict]):
        logger.info(f"CQH: Handling apply request for {len(selected_changes_data)} changes.")
        processed_ids = set(); items_to_remove = []
        for change_data in selected_changes_data:
            change_id = change_data.get('id'); file_path = change_data.get('file_path')
            original_full_content = change_data.get('original_full_content'); proposed_content = change_data.get('proposed_content')
            original_start_line = change_data.get('original_start_line', -1); original_end_line = change_data.get('original_end_line', -1)
            insertion_line = change_data.get('insertion_line', -1); apply_type = change_data.get('apply_type', 'none')

            if not all([change_id, file_path, original_full_content is not None, proposed_content is not None, apply_type != 'none']):
                logger.warning(f"Skipping invalid change data for apply: {change_data.get('display_name')}"); continue
            if change_id in processed_ids: continue

            success = False; final_content = None
            try:
                orig_lines = original_full_content.splitlines(keepends=True)
                prop_lines = proposed_content.splitlines(keepends=True)
                # Ensure proposed content ends with newline if original did (helps diff/patch)
                if orig_lines and orig_lines[-1].endswith(('\n','\r')) and prop_lines and not prop_lines[-1].endswith(('\n','\r')):
                    prop_lines[-1] += '\n'

                if apply_type == 'insert' and insertion_line != -1:
                    logger.debug(f"Applying {change_id} via INSERTION: File='{file_path.name}', Line {insertion_line+1}")
                    # Clamp insertion index to valid range
                    insert_at = max(0, min(insertion_line, len(orig_lines)));
                    new_lines = orig_lines[:insert_at] + prop_lines + orig_lines[insert_at:]
                    final_content = "".join(new_lines); success = True

                elif apply_type == 'replace' and original_start_line != -1 and original_end_line != -1:
                    logger.debug(f"Applying {change_id} via REPLACEMENT: File='{file_path.name}', Lines {original_start_line+1}-{original_end_line+1}")
                    start = max(0, original_start_line);
                    end = min(len(orig_lines) -1 , original_end_line) # Use len-1 for index
                    if start > end: raise ValueError(f"Invalid line range: {start+1}-{end+1}")
                    new_lines = orig_lines[:start] + prop_lines + orig_lines[end + 1:]
                    final_content = "".join(new_lines); success = True

                elif apply_type == 'patch':
                    logger.debug(f"Applying {change_id} via PATCH: File='{file_path.name}'")
                    if original_start_line == -1 or original_end_line == -1:
                         logger.error(f"Cannot apply patch for {file_path.name}: Original block not identified."); success = False
                    else:
                         start = max(0, original_start_line);
                         end = min(len(orig_lines) -1 , original_end_line)
                         if start > end: raise ValueError(f"Invalid range for patch: {start+1}-{end+1}")
                         orig_block_lines = orig_lines[start : end + 1]
                         # Generate unified diff between the original block and the full proposed content
                         patch_str = "".join(difflib.unified_diff(
                             orig_block_lines, prop_lines,
                             fromfile=f"a/{file_path.name}", tofile=f"b/{file_path.name}",
                             lineterm='\n' # Use consistent line endings for patch
                             ))

                         if not patch_str:
                              logger.warning(f"Generated patch is empty for {file_path.name}. Applying as simple replacement.");
                              new_lines = orig_lines[:start] + prop_lines + orig_lines[end + 1:];
                              final_content = "".join(new_lines); success = True
                         else:
                              logger.debug(f"Generated Patch:\n{patch_str}")
                              # Apply the patch to the *full* original content
                              patched_content = apply_patch(original_full_content, patch_str)
                              if patched_content is not None:
                                  final_content = patched_content; success = True
                              else:
                                  logger.error(f"Failed to apply patch for {file_path.name}. Check patch content and original file state.");
                                  QMessageBox.critical(self._widget.window(), "Patch Apply Failed", f"Applying patch failed for '{file_path.name}'.\nCheck logs for details.");
                                  success = False # Ensure success is false
                else:
                    logger.error(f"Cannot apply {change_id}: Inconsistent apply_type ('{apply_type}') or invalid data."); success = False

                if success and final_content is not None:
                    # Use WorkspaceManager to handle saving and updating editor state
                    save_success = self._workspace.save_tab_content_directly(file_path, final_content)
                    if save_success:
                        self._status_bar.update_status(f"Applied changes to: {file_path.name}", 3000)
                    else:
                        self._status_bar.update_status(f"❌ Failed save to: {file_path.name}", 5000); success = False
                elif success: # Should not happen if logic is correct
                    logger.error("Internal error: Apply successful but final_content is None."); success = False

            except Exception as e:
                logger.exception(f"Error applying change {change_id} for {file_path.name}: {e}");
                self._status_bar.update_status(f"❌ Error applying to: {file_path.name}", 5000);
                success = False # Ensure success is false on exception

            if success:
                 processed_ids.add(change_id);
                 item = self._find_item_by_id(change_id)
                 if item:
                     items_to_remove.append(item)
                 else:
                     logger.warning(f"Could not find list item for applied change ID {change_id}")

        if items_to_remove:
            self._widget.remove_items(items_to_remove)

    @pyqtSlot(list)
    def _handle_reject_request(self, selected_changes_data: List[Dict]):
        logger.info(f"CQH: Handling reject request for {len(selected_changes_data)} changes.")
        items_to_remove = []; rejected_count = 0
        for change_data in selected_changes_data:
            change_id = change_data.get('id');
            item = self._find_item_by_id(change_id) if change_id else None
            if item:
                items_to_remove.append(item); rejected_count += 1
            elif change_id:
                logger.warning(f"Could not find item for rejected change ID {change_id}")
        if items_to_remove:
            self._widget.remove_items(items_to_remove);
            self._status_bar.update_status(f"Rejected {rejected_count} change(s).", 3000)

    @pyqtSlot(str)
    def handle_potential_change(self, ai_content_with_markers: str):
        """Parses AI content for change blocks and adds them to the queue."""
        logger.info("ChangeQueueHandler: Received potential_change_detected pyqtSignal. Parsing content...")
        # Improved regex to handle optional trailing newline before END FILE
        change_pattern = re.compile(
            r"### START FILE: (?P<filepath>.*?) ###\n" # Start marker and path
            r"(?P<content>.*?)"                      # Content (non-greedy)
            r"\n?### END FILE: (?P=filepath) ###",      # Optional newline and End marker
            re.DOTALL | re.MULTILINE
        )
        matches = list(change_pattern.finditer(ai_content_with_markers)); changes_added = 0
        logger.debug(f"Found {len(matches)} potential change blocks in received content.")

        for i, match in enumerate(matches):
            logger.debug(f"--- Processing received block {i+1}/{len(matches)} ---")
            try:
                relative_path_str = match.group('filepath').strip();
                proposed_content = match.group('content') # Content exactly as captured
                if not relative_path_str:
                    logger.warning(f"Block {i+1}: Empty file path."); continue
                logger.debug(f"Block {i+1}: Filepath='{relative_path_str}'")

                abs_path = self._workspace.project_path / relative_path_str;
                original_full_content = None
                if abs_path.is_file():
                    try:
                        original_full_content = abs_path.read_text(encoding='utf-8')
                    except Exception as e:
                        logger.error(f"Block {i+1}: Failed read original file {abs_path}: {e}"); continue
                else:
                    logger.warning(f"Block {i+1}: File '{abs_path}' not found (considered new).");
                    original_full_content = "" # Treat as empty for comparison/diff

                original_lines_match = original_full_content.splitlines() # Split for matching function
                proposed_lines_match = proposed_content.splitlines()

                start_line, end_line, confidence = self._find_original_block(original_lines_match, proposed_lines_match)
                original_block_content = None # The specific block content for diff view

                if start_line != -1 and original_full_content: # Only extract block if match found and original exists
                    # Use keepends=True for accurate block extraction
                    original_lines_with_ends = original_full_content.splitlines(keepends=True)
                    # Clamp end_line to valid index
                    safe_end_line = min(end_line, len(original_lines_with_ends) - 1)
                    if start_line <= safe_end_line: # Ensure range is valid
                         original_block_content = "".join(original_lines_with_ends[start_line : safe_end_line + 1])
                         logger.info(f"Block {i+1}: Matched original block lines {start_line+1}-{safe_end_line+1} (Confidence: {confidence})")
                    else:
                         logger.warning(f"Block {i+1}: Invalid line range from matcher ({start_line+1}-{end_line+1}). No block extracted.")
                         confidence = 'none' # Force manual review if range is bad
                elif start_line == -1:
                     logger.warning(f"Block {i+1}: No matching block found.")
                     confidence = 'none' # Ensure confidence reflects no match found

                logger.debug(f"Block {i+1}: Calling widget.add_change for {abs_path.name}...")
                self._widget.add_change(
                    file_path=abs_path,
                    proposed_content=proposed_content, # Pass raw proposed content
                    original_full_content=original_full_content, # Pass full original content
                    original_block_content=original_block_content, # Pass extracted block or None
                    original_start_line=start_line,
                    original_end_line=end_line,
                    match_confidence=confidence
                )
                changes_added += 1
                logger.debug(f"Block {i+1}: Added change to queue widget.")
            except Exception as e:
                logger.exception(f"Block {i+1}: Error processing change block: {e}")
        # --- End Loop ---

        if changes_added > 0:
             logger.info(f"Finished processing potential changes. Added {changes_added} item(s) to queue.")
             self._status_bar.update_status(f"Detected {changes_added} pending file change(s). Review in queue.", 5000)
        else:
             logger.debug("Finished processing. No valid change blocks added to queue.")

    def _find_item_by_id(self, change_id: str) -> Optional[QListWidgetItem]:
        """Finds a QListWidgetItem in the change list by its stored change ID."""
        for i in range(self._widget.change_list.count()):
            item = self._widget.change_list.item(i)
            # Check item is not None before accessing data
            if item:
                 data = item.data(Qt.ItemDataRole.UserRole)
                 if isinstance(data, dict) and data.get('id') == change_id:
                     return item
        return None

