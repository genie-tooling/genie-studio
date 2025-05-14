# pm/handlers/change_queue_handler.py
import re
import uuid
import difflib # For matching
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PySide6.QtCore import QObject, Slot, Qt, QTimer, Signal
from PySide6.QtWidgets import QListWidgetItem, QMessageBox, QApplication # For finding item and messages
from loguru import logger

# Dependency Imports
from ..ui.change_queue_widget import ChangeQueueWidget
from ..ui.diff_dialog import DiffDialog
from ..core.workspace_manager import WorkspaceManager
from ..ui.controllers.status_bar_controller import StatusBarController


class ChangeQueueHandler(QObject):
    """Handles logic for the Change Queue (viewing, applying, rejecting)."""

    # Signals emitted by this handler
    view_requested = Signal(dict)       # Emits the full change_data_dict when view is requested
    apply_requested = Signal(list)      # list[change_data_dict] (for batch apply button)
    reject_requested = Signal(list)     # list[change_data_dict] (for batch reject button)

    def __init__(self,
                 widget: ChangeQueueWidget,         # 1st position (UI Widget)
                 workspace: WorkspaceManager,     # 2nd position (Core Service)
                 status_bar: StatusBarController, # 3rd position (Controller)
                 parent: Optional[QObject] = None): # 4th position (or last)
        """
        Initializes the ChangeQueueHandler.

        Args:
            widget: The ChangeQueueWidget UI element this handler manages.
            workspace: The WorkspaceManager for file operations.
            status_bar: The StatusBarController for showing messages.
            parent: The optional parent QObject.
        """
        super().__init__(parent) # Pass parent to the superclass init
        self._widget = widget
        self._workspace = workspace
        self._status_bar = status_bar

        # Connect signals from the UI widget right after initialization
        self._connect_signals()
        logger.info("ChangeQueueHandler initialized.")

    def _connect_signals(self):
        """Connect signals from the UI widget to handler slots."""
        # Ensure self._widget exists before connecting
        if not self._widget:
            logger.error("ChangeQueueHandler: Cannot connect signals, widget is None.")
            return

        try:
            # Connect signals emitted by ChangeQueueWidget to slots in this handler
            self._widget.view_requested.connect(self._handle_view_request)
            self._widget.apply_requested.connect(self._handle_apply_request) # Batch apply from button
            self._widget.reject_requested.connect(self._handle_reject_request)
            logger.debug("ChangeQueueHandler: UI widget signals connected.")
        except AttributeError as e:
             # This might happen if the widget is somehow invalid or missing expected signals
             logger.error(f"ChangeQueueHandler: Error connecting signals - widget missing attribute? {e}")
        except Exception as e:
             # Catch any other unexpected errors during connection
             logger.exception(f"ChangeQueueHandler: Unexpected error connecting signals: {e}")

    def _find_original_block(self, original_lines: List[str], proposed_lines: List[str]) -> Tuple[int, int, str]:
        """
        Tries to find the start/end lines in original_lines that best match
        the proposed_lines using difflib.SequenceMatcher.

        Args:
            original_lines: List of strings representing lines in the original file (without line endings).
            proposed_lines: List of strings representing lines in the proposed content (without line endings).

        Returns:
            A tuple containing:
            - start_line_index (int): The 0-based starting line index in the original file, or -1 if no match.
            - end_line_index (int): The 0-based *inclusive* ending line index in the original file, or -1 if no match.
            - confidence_level (str): 'partial' if a plausible match is found, 'none' otherwise.
        """
        if not proposed_lines or not original_lines:
            logger.debug("Find Block: Empty input lines.")
            return -1, -1, 'none'

        # Use SequenceMatcher to find matching blocks
        matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines, autojunk=False)

        # get_matching_blocks() returns tuples of (i, j, n)
        # where original_lines[i:i+n] == proposed_lines[j:j+n]
        matching_blocks = matcher.get_matching_blocks()

        # Filter out the 'junk' block at the end if present
        if matching_blocks and matching_blocks[-1] == (len(original_lines), len(proposed_lines), 0):
            matching_blocks = matching_blocks[:-1]

        if not matching_blocks:
            logger.warning("Find Block: No matching blocks found by difflib.")
            return -1, -1, 'none'

        # Heuristic: Find the single longest matching block (`n` is max).
        best_match = None
        max_n = 0
        for i, j, n in matching_blocks:
            if n > max_n:
                 max_n = n
                 best_match = (i, j, n) # Store the block with the longest match

        # --- Thresholding ---
        # Require a minimum match length and coverage ratio
        min_match_length = 2 # Example: require at least 2 lines to match
        min_coverage_ratio = 0.3 # Example: require match to cover at least 30% of proposed lines

        if best_match and best_match[2] >= min_match_length:
            i, j, n = best_match
            coverage = n / len(proposed_lines) if len(proposed_lines) > 0 else 0

            logger.debug(f"Find Block: Best match details - Original Start={i}, Proposed Start={j}, Length={n}, Coverage={coverage:.2f}")

            if coverage >= min_coverage_ratio:
                # We found a plausible block. Return its start/end in the *original* file.
                original_start_line = i
                original_end_line = i + n - 1 # Inclusive end index
                logger.info(f"Find Block: Found plausible match via difflib. Original lines: {original_start_line + 1}-{original_end_line + 1}")
                # Confidence is 'partial' as difflib finds similarities.
                return original_start_line, original_end_line, 'partial'
            else:
                 logger.warning(f"Find Block: Longest match (n={n}) coverage ({coverage:.2f}) below threshold ({min_coverage_ratio}).")
        else:
            if best_match: logger.warning(f"Find Block: Longest match (n={best_match[2]}) below minimum length ({min_match_length}).")
            else: logger.warning("Find Block: No suitable matching block identified by difflib heuristics.")

        # If no plausible match met the criteria
        return -1, -1, 'none'

    @Slot(dict)
    def _handle_view_request(self, change_data: Dict):
        """Shows the DiffDialog for the selected change item."""
        logger.debug(f"ChangeQueueHandler: Handling view request for change ID {change_data.get('id')}")

        original_full_content = change_data.get('original_full_content')
        original_block_content = change_data.get('original_block_content')
        original_start_line = change_data.get('original_start_line')
        original_end_line = change_data.get('original_end_line')
        proposed_content = change_data.get('proposed_content')
        match_confidence = change_data.get('match_confidence') # Get confidence

        if original_full_content is None or proposed_content is None or match_confidence is None:
             logger.error("View request missing essential data (full_content, proposed_content, or match_confidence).")
             QMessageBox.warning(self._widget.window(),"View Error", "Could not display change: Missing essential data.")
             return

        # Ensure line numbers are valid integers if not None
        if original_start_line is not None and not isinstance(original_start_line, int):
            logger.error(f"Invalid type for original_start_line: {type(original_start_line)}")
            original_start_line = -1 # Fallback
        if original_end_line is not None and not isinstance(original_end_line, int):
            logger.error(f"Invalid type for original_end_line: {type(original_end_line)}")
            original_end_line = -1 # Fallback

        # Create and show the DiffDialog
        dialog = DiffDialog(
            original_full_content=original_full_content,
            original_block_content=original_block_content,
            original_start_line=original_start_line if original_start_line is not None else -1,
            original_end_line=original_end_line if original_end_line is not None else -1,
            proposed_content=proposed_content,
            match_confidence=match_confidence, # Pass confidence ('partial' or 'none')
            parent=self._widget.window()
        )

        if dialog.exec():
            # Dialog was accepted (Apply Auto, Insert Here)
            insertion_line = getattr(dialog, 'insertion_line', -1)
            apply_mode = getattr(dialog, 'apply_mode', 'reject') # Get how dialog was accepted

            if apply_mode == 'insert':
                logger.info(f"DiffDialog accepted with 'Insert Here' at line {insertion_line + 1}.")
                change_data['insertion_line'] = insertion_line
                change_data['apply_type'] = 'insert' # Mark how to apply
            elif apply_mode == 'auto_replace':
                 logger.info("DiffDialog accepted with 'Apply Auto-Detected Change'.")
                 change_data['apply_type'] = 'replace' # Mark how to apply
            else:
                 logger.warning(f"DiffDialog accepted with unexpected mode '{apply_mode}'. Skipping apply.")
                 return # Don't proceed if mode is unclear

            # Trigger the apply logic for this single item
            self._handle_apply_request([change_data])
        else:
             # Dialog was rejected or closed
             logger.info("DiffDialog closed or 'Reject Change' clicked.")

    @Slot(list)
    def _handle_apply_request(self, selected_changes_data: List[Dict]):
        """Attempts to apply the selected changes (handles replacement or insertion)."""
        logger.info(f"ChangeQueueHandler: Handling apply request for {len(selected_changes_data)} changes.")
        processed_ids = set()
        items_to_remove = []

        for change_data in selected_changes_data:
            change_id = change_data.get('id')
            file_path = change_data.get('file_path')
            original_full_content = change_data.get('original_full_content')
            proposed_content = change_data.get('proposed_content')
            original_start_line = change_data.get('original_start_line', -1)
            original_end_line = change_data.get('original_end_line', -1)
            insertion_line = change_data.get('insertion_line', -1)
            apply_type = change_data.get('apply_type', 'none') # Get apply type ('insert' or 'replace')

            if not change_id or not file_path or original_full_content is None or proposed_content is None or apply_type == 'none':
                logger.warning(f"Skipping invalid change data for apply: ID={change_id}, Path={file_path}, ApplyType={apply_type}")
                continue

            if change_id in processed_ids:
                 logger.trace(f"Skipping already processed change ID {change_id}")
                 continue

            success = False
            final_content = None

            try:
                original_lines = original_full_content.splitlines(keepends=True)
                proposed_lines = proposed_content.splitlines(keepends=True)

                # Ensure proposed content has a trailing newline if original does
                if original_lines and original_lines[-1].endswith(('\n','\r')):
                    if not proposed_lines or not proposed_lines[-1].endswith(('\n','\r')):
                         proposed_lines.append('\n') # Add newline if missing

                if apply_type == 'insert' and insertion_line != -1:
                    # --- Insertion Logic ---
                    logger.debug(f"Applying change {change_id} via INSERTION: File='{file_path.name}', Before Line {insertion_line+1}")
                    # Clamp insertion index to valid range
                    insert_at = max(0, min(insertion_line, len(original_lines)))
                    new_content_lines = original_lines[:insert_at] + proposed_lines + original_lines[insert_at:]
                    final_content = "".join(new_content_lines)
                    success = True

                elif apply_type == 'replace' and original_start_line != -1 and original_end_line != -1:
                    # --- Replacement Logic ---
                    logger.debug(f"Applying change {change_id} via REPLACEMENT: File='{file_path.name}', Lines {original_start_line+1}-{original_end_line+1}")
                    start = max(0, original_start_line)
                    # Use exclusive end index for slicing, calculated from inclusive end line
                    end = min(len(original_lines), original_end_line + 1)
                    if start >= end: # Check if range is valid
                         raise ValueError(f"Invalid line range: Start index {start} >= End index {end} (Orig End Line: {original_end_line})")

                    # Combine parts: before + proposed + after
                    new_content_lines = original_lines[:start] + proposed_lines + original_lines[end:]
                    final_content = "".join(new_content_lines)
                    success = True
                else:
                    logger.error(f"Cannot apply change {change_id} for '{file_path.name}': Inconsistent apply_type ('{apply_type}') or invalid line data (start={original_start_line}, end={original_end_line}, insert={insertion_line}).")
                    QMessageBox.warning(self._widget.window(), "Apply Failed", f"Could not apply the change in '{file_path.name}' due to inconsistent data.")
                    success = False # Ensure success is false

                # --- Save if successful ---
                if success and final_content is not None:
                    save_success = self._workspace.save_tab_content_directly(file_path, final_content)
                    if save_success:
                         self._status_bar.update_status(f"Applied changes to: {file_path.name}", 3000)
                    else:
                         # Workspace manager should emit error, but update status here too
                         self._status_bar.update_status(f"❌ Failed save to: {file_path.name}", 5000)
                         success = False # Mark as failed if save fails
                elif success:
                     # Should not happen if logic above is correct
                     logger.error("Apply logic indicated success but final_content is None.")
                     success = False

            except Exception as e:
                 logger.exception(f"Error applying change {change_id} for {file_path.name}: {e}")
                 self._status_bar.update_status(f"❌ Error applying to: {file_path.name}", 5000)
                 success = False

            # --- Add item to removal list ONLY if successfully applied and saved ---
            if success:
                processed_ids.add(change_id)
                item = self._find_item_by_id(change_id)
                if item:
                    items_to_remove.append(item)
                else:
                     logger.warning(f"Could not find list item for successfully applied change ID {change_id}")

        # --- Remove successfully processed items from the UI list ---
        if items_to_remove:
            self._widget.remove_items(items_to_remove)

    @Slot(list)
    def _handle_reject_request(self, selected_changes_data: List[Dict]):
        """Handles the request to reject (remove) selected changes from the queue."""
        logger.info(f"ChangeQueueHandler: Handling reject request for {len(selected_changes_data)} changes.")
        items_to_remove = []
        rejected_count = 0
        for change_data in selected_changes_data:
            change_id = change_data.get('id')
            if not change_id:
                 logger.warning("Reject request received for change data with no ID.")
                 continue
            item = self._find_item_by_id(change_id)
            if item:
                items_to_remove.append(item)
                rejected_count += 1
            else:
                 logger.warning(f"Could not find list item for rejected change ID {change_id}")

        if items_to_remove:
            self._widget.remove_items(items_to_remove)
            self._status_bar.update_status(f"Rejected {rejected_count} change(s).", 3000)

    @Slot(str)
    def handle_potential_change(self, ai_content_with_markers: str):
        """
        Parses AI-generated content containing file markers, attempts to find
        the corresponding original block using difflib, and adds the change
        proposal to the ChangeQueueWidget.
        """
        logger.debug("ChangeQueueHandler: Received potential change content. Parsing...")
        # Regex to find blocks marked by ### START/END FILE: ... ###
        change_pattern = re.compile(
            r"### START FILE: (?P<filepath>.*?) ###\n(?P<content>.*?)\n### END FILE: (?P=filepath) ###",
            re.DOTALL | re.MULTILINE
        )
        matches = change_pattern.finditer(ai_content_with_markers)
        changes_added = 0

        for match in matches:
            try:
                relative_path_str = match.group('filepath').strip()
                proposed_content = match.group('content')

                if not relative_path_str:
                    logger.warning("Skipping change block with empty file path.")
                    continue

                # Resolve absolute path and read original content
                abs_path = self._workspace.project_path / relative_path_str
                original_full_content = None
                if abs_path.is_file():
                    try:
                        original_full_content = abs_path.read_text(encoding='utf-8')
                    except Exception as e:
                        logger.error(f"Failed to read original file {abs_path}: {e}")
                        # Optionally add to queue anyway with 'none' confidence? For now, skip.
                        continue
                else:
                    logger.warning(f"File path specified in change block not found: '{abs_path}'. Skipping.")
                    continue

                # Prepare lines for difflib (without line endings)
                original_lines = original_full_content.splitlines()
                proposed_lines = proposed_content.splitlines()

                # --- Use enhanced block finding ---
                start_line, end_line, confidence = self._find_original_block(original_lines, proposed_lines)
                # 'confidence' will be 'partial' or 'none'
                # ---------------------------------

                original_block_content = None
                # Extract the original block content only if a match was found
                if confidence == 'partial' and start_line != -1 and end_line != -1 and start_line <= end_line:
                    # Use splitlines(keepends=True) for accurate block content extraction
                    original_lines_with_ends = original_full_content.splitlines(keepends=True)
                    # Ensure indices are within bounds before slicing
                    start_idx = max(0, start_line)
                    end_idx = min(len(original_lines_with_ends), end_line + 1) # +1 for exclusive slice end
                    if start_idx < end_idx:
                         original_block_content = "".join(original_lines_with_ends[start_idx : end_idx])
                         logger.info(f"Found and extracted original block for '{relative_path_str}' lines {start_line+1}-{end_line+1}")
                    else:
                         logger.warning(f"Invalid line indices returned for '{relative_path_str}': start={start_line}, end={end_line}. Resetting match.")
                         start_line, end_line, confidence = -1, -1, 'none' # Reset if indices invalid
                else:
                    # If no match found, log it. Confidence is already 'none'.
                    logger.warning(f"No plausible matching block found for '{relative_path_str}'. Will require manual insertion.")
                    start_line, end_line = -1, -1 # Ensure lines are -1

                # --- Add the change proposal to the UI queue ---
                self._widget.add_change(
                    file_path=abs_path,
                    proposed_content=proposed_content,
                    original_full_content=original_full_content,
                    original_block_content=original_block_content, # Pass the extracted block or None
                    original_start_line=start_line,             # Pass the found start line or -1
                    original_end_line=end_line,                 # Pass the found end line or -1
                    match_confidence=confidence                 # Pass 'partial' or 'none'
                )
                changes_added += 1
            except Exception as e:
                 # Catch errors during processing of a single block
                 logger.exception(f"Error processing detected change block: {e}")

        # Update status bar after processing all blocks
        if changes_added > 0:
             self._status_bar.update_status(f"Detected {changes_added} pending file change(s). Review required.", 5000)
        else:
             logger.debug("No valid file change blocks found in AI content.")

    def _find_item_by_id(self, change_id: str) -> Optional[QListWidgetItem]:
        """Helper function to find a QListWidgetItem in the change list by its stored ID."""
        if not self._widget:
            return None
        for i in range(self._widget.change_list.count()):
            item = self._widget.change_list.item(i)
            if not item: # Should not happen, but check
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            # Ensure data is a dictionary and has the 'id' key
            if isinstance(data, dict) and data.get('id') == change_id:
                return item
        return None # Not found