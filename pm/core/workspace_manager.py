# pm/core/workspace_manager.py
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QTabWidget, QPlainTextEdit, QMessageBox, QApplication # Added QApplication
from PySide6.QtGui import QFont, QIcon # Added QIcon
from pathlib import Path
import os
from loguru import logger
import qtawesome as qta
from typing import Dict, Optional

from ..ui.highlighter import PygmentsHighlighter
from .token_utils import count_tokens
# *** IMPORT FROM NEW CONSTANTS FILE ***
from .constants import TOKEN_COUNT_ROLE, TREE_TOKEN_SIZE_LIMIT
from .project_config import DEFAULT_STYLE, AVAILABLE_PYGMENTS_STYLES

# Constants should ideally be in a central config module
IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', '.mypy_cache', '.pytest_cache', 'node_modules'}
IGNORE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.zip', '.tar', '.gz', '.ico', '.svg', '.db', '.sqlite', '.bin', '.exe', '.dll', '.so', '.o', '.a', '.lib'}

class WorkspaceManager(QObject):
    """Manages project state, file tree, and editor tabs."""
    project_changed = Signal(Path)      # Emitted when project path changes
    editors_changed = Signal()          # Emitted when tabs are opened/closed
    file_saved = Signal(Path)           # Emitted when a file is successfully saved
    file_operation_error = Signal(str)  # Emitted on file load/save/create errors

    def __init__(self, initial_project_path: Path, settings: dict, parent=None):
        super().__init__(parent)
        self._project_path = initial_project_path
        self._settings = settings # Keep settings reference for font, etc.
        # Path -> Widget mapping for open editor tabs
        self.open_editors: Dict[Path, QPlainTextEdit] = {}
        logger.info(f"WorkspaceManager initialized for path: {initial_project_path}")

    @property
    def project_path(self) -> Path:
        return self._project_path

    def set_project_path(self, new_path: Path):
        """Sets a new project path, clearing existing editors."""
        new_path = Path(new_path).resolve() # Ensure absolute path
        if new_path != self._project_path and new_path.is_dir():
            logger.info(f"WorkspaceManager: Setting project path to {new_path}")
            self._project_path = new_path
            self.open_editors.clear() # Clear editors from old project
            # MainWindow is responsible for saving/loading the '.patchmind.json' config
            self.project_changed.emit(new_path)
            self.editors_changed.emit()
        elif not new_path.is_dir():
             error_msg = f"Invalid project path selected: {new_path}"
             logger.error(f"WorkspaceManager: {error_msg}")
             self.file_operation_error.emit(error_msg)

    def populate_file_tree(self, tree_widget: QTreeWidget):
        if not self._project_path or not self._project_path.is_dir():
            logger.error("Wks Mgr: Populate tree fail - invalid path.")
            tree_widget.clear(); return

        logger.info(f"Wks Mgr: Populating file tree for {self._project_path}")
        tree_widget.blockSignals(True); tree_widget.clear()
        try:
            proj_root_item = QTreeWidgetItem(tree_widget, [self._project_path.name, ""])
            proj_root_item.setIcon(0, qta.icon('fa5s.folder-open', color='lightblue'))
            proj_root_item.setData(0, Qt.UserRole, str(self._project_path))
            # Root item itself is NOT checkable
            proj_root_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            logger.trace(f"ROOT '{proj_root_item.text(0)}': Flags set. Flags: {proj_root_item.flags()}")
            tree_items = {str(self._project_path): proj_root_item}

            for root, dirs, files in os.walk(self._project_path, topdown=True, onerror=logger.warning):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
                parent_item = tree_items.get(str(root_path))
                if parent_item is None: continue

                # Process Directories
                for dname in sorted(dirs):
                     dir_path = root_path / dname
                     item = QTreeWidgetItem(parent_item, [dname, ""])
                     item.setIcon(0, qta.icon('fa5s.folder', color='lightgray'))
                     item.setData(0, Qt.UserRole, str(dir_path))
                     # --- Explicitly set flags for Dirs ---
                     required_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                     logger.trace(f"  DIR '{dname}': Setting flags to {required_flags}")
                     item.setFlags(required_flags)
                     final_flags = item.flags()
                     is_checkable = bool(final_flags & Qt.ItemIsUserCheckable)
                     logger.trace(f"  DIR '{dname}': Flags SET. IsCheckable={is_checkable}. Final Flags: {final_flags}")
                     # --- End Flags ---
                     item.setCheckState(0, Qt.Checked)
                     tree_items[str(dir_path)] = item

                # Process Files
                for fname in sorted(files):
                    fpath = root_path / fname
                    if fname.startswith('.') or fpath.suffix.lower() in IGNORE_EXT: continue

                    # --- Simplified token display for now ---
                    token_display = "-"
                    token_count = 0
                    # (Keep token calculation logic commented out temporarily if needed)
                    try:
                        fsize = fpath.stat().st_size
                        if fsize <= TREE_TOKEN_SIZE_LIMIT:
                           try:
                               content = fpath.read_text(encoding='utf-8', errors='ignore')
                               token_count = count_tokens(content) # Still calculate for data role
                               token_display = f"{token_count:,}"
                           except Exception: token_display = "Error"
                        else: token_display = f">{TREE_TOKEN_SIZE_LIMIT // 1024}KB"
                    except OSError: token_display = "N/A"; continue
                    # --- End Simplified ---

                    item = QTreeWidgetItem(parent_item, [fname, token_display])
                    item.setIcon(0, qta.icon('fa5s.file-code', color='darkgray'))
                    item.setData(0, Qt.UserRole, str(fpath))
                    item.setData(0, TOKEN_COUNT_ROLE, token_count)
                    # --- Explicitly set flags for Files ---
                    required_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                    logger.trace(f"  FILE '{fname}': Setting flags to {required_flags}")
                    item.setFlags(required_flags)
                    final_flags = item.flags()
                    is_checkable = bool(final_flags & Qt.ItemIsUserCheckable)
                    logger.trace(f"  FILE '{fname}': Flags SET. IsCheckable={is_checkable}. Final Flags: {final_flags}")
                    # --- End Flags ---
                    item.setCheckState(0, Qt.Checked)
                    item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)

        except Exception as e:
             logger.exception(f"Wks Mgr: Error during tree population: {e}")
        finally:
            tree_widget.expandToDepth(0)
            tree_widget.blockSignals(False)
            logger.info("Wks Mgr: File tree population finished.")

    def load_file(self, path: Path, tab_widget: QTabWidget) -> Optional[QPlainTextEdit]:
        """Loads a file into the editor tab widget, returns the editor widget."""
        path = path.resolve() # Ensure absolute path
        if not path.is_file():
             logger.warning(f"WorkspaceManager: Attempted to load non-file: {path}")
             self.file_operation_error.emit(f"Cannot load: '{path.name}' is not a file.")
             return None

        # --- Check if already open and focus ---
        if path in self.open_editors:
            editor = self.open_editors[path]
            found_tab_index = -1
            for i in range(tab_widget.count()):
                if tab_widget.widget(i) == editor:
                    found_tab_index = i
                    break
            if found_tab_index != -1:
                 logger.debug(f"File already open, focusing tab {found_tab_index}: {path.name}")
                 tab_widget.setCurrentIndex(found_tab_index)
                 editor.setFocus() # Explicitly set focus
                 return editor
            else:
                 # Should not happen if open_editors is consistent, but handle defensively
                 logger.warning(f"Editor for {path} in dict but not found in tabs. Removing stale entry and reloading.")
                 try:
                     del self.open_editors[path]
                 except KeyError: pass # Ignore if already removed somehow

        logger.info(f"WorkspaceManager: Loading file into new tab: {path}")
        try:
            # Consider adding size check here too
            if path.stat().st_size > (2 * 1024 * 1024): # Example: 2MB limit for direct load
                reply = QMessageBox.question(QApplication.activeWindow(), "Large File",
                                             f"'{path.name}' is large ({path.stat().st_size // 1024} KB).\nLoad anyway?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.No:
                    logger.info(f"User cancelled loading large file: {path.name}")
                    return None
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
             error_msg = f"Could not read file:\n{path}\n\nError: {e}"
             logger.error(f"WorkspaceManager: {error_msg}")
             self.file_operation_error.emit(error_msg) # Emit signal
             return None

        # --- Create Editor Widget ---
        try:
            editor = QPlainTextEdit()
            editor.setPlainText(text)
            editor.setObjectName(str(path)) # Store path for later retrieval (save, close)

            # Apply font from settings
            font_name = self._settings.get("editor_font", "Fira Code")
            font_size = int(self._settings.get("editor_font_size", 11))
            editor.setFont(QFont(font_name, font_size))
            style_name = self._settings.get('syntax_highlighting_style', DEFAULT_STYLE)
            # Apply syntax highlighting
            lang = self._guess_lang(path)
            editor.highlighter = PygmentsHighlighter(editor.document(), language=lang, style_name=style_name)
            logger.debug(f"Applied highlighter (Style: {style_name}, Lang: {lang}) to {path.name}")

        except Exception as e:
             error_msg = f"Error creating editor widget for {path.name}: {e}"
             logger.exception(error_msg) # Log full traceback
             self.file_operation_error.emit(error_msg)
             return None

        # --- Add Editor to Tab Widget ---
        try:
            index = tab_widget.addTab(editor, path.name)
            if index == -1:
                 # This shouldn't typically happen unless tab_widget is invalid
                 raise RuntimeError("Failed to add tab to QTabWidget.")

            tab_widget.setTabToolTip(index, str(path))
            tab_widget.setCurrentWidget(editor) # Make the new tab active
            editor.setFocus()                   # Set keyboard focus to the editor

            logger.info(f"Added editor for {path.name} at tab index {index}")

            # Update internal tracking
            self.open_editors[path] = editor
            self.editors_changed.emit() # Signal that the set of open editors changed
            return editor

        except Exception as e:
             error_msg = f"Error adding editor tab for {path.name}: {e}"
             logger.exception(error_msg)
             self.file_operation_error.emit(error_msg)
             # Clean up editor if tab adding failed
             editor.deleteLater()
             if path in self.open_editors:
                 del self.open_editors[path]
             return None

    def _guess_lang(self, path: Path) -> str | None:
         ext = path.suffix.lower(); mapping = {'.py':'python','.js':'javascript','.ts':'typescript','.html':'html','.css':'css','.json':'json','.yaml':'yaml','.yml':'yaml','.go':'go','.rb':'ruby','.sh':'bash','.toml':'toml','.ini':'ini','.md':'markdown','.java':'java','.c':'c','.cpp':'cpp','.h':'c','.hpp':'cpp','.cs':'csharp','.xml':'xml','.sql':'sql','.php':'php','.pl':'perl','.kt':'kotlin','.swift':'swift','.rs':'rust'}; return mapping.get(ext)

    def close_tab(self, index: int, tab_widget: QTabWidget):
        """Closes an editor tab, removing internal reference."""
        widget = tab_widget.widget(index)
        if widget and isinstance(widget, QPlainTextEdit):
             path_to_remove = Path(widget.objectName()) # Retrieve path from object name
             # TODO: Add check for unsaved changes before closing
             tab_widget.removeTab(index)
             if path_to_remove in self.open_editors:
                  del self.open_editors[path_to_remove]
                  logger.info(f"WorkspaceManager: Closed tab {path_to_remove.name}")
                  self.editors_changed.emit()
             else:
                  logger.warning(f"WorkspaceManager: Closed tab for path {path_to_remove} not found in internal dict.")
             widget.deleteLater()

    def save_tab_content(self, editor: QPlainTextEdit) -> bool:
        """Saves the content of a specific editor widget to its file."""
        path_str = editor.objectName()
        if not path_str:
             logger.error("WorkspaceManager: Cannot save tab, editor has no path associated (objectName is empty).")
             self.file_operation_error.emit("Cannot save file: Path unknown.")
             return False
        current_path = Path(path_str)
        try:
            text = editor.toPlainText()
            current_path.write_text(text, encoding='utf-8')
            logger.info(f'WorkspaceManager: Saved {current_path}')
            self.file_saved.emit(current_path) # Signal success
             # TODO: Update tab title to remove modification indicator '*'
            return True
        except Exception as e:
            error_msg = f"Could not save file:\n{current_path}\n\nError: {e}"
            logger.error(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)
            return False

    def create_new_file(self, filename: str) -> Optional[Path]:
        """Creates a new empty file in the project directory."""
        if not filename: return None
        fpath = self._project_path / filename.strip()
        if fpath.exists():
             error_msg = f"File '{fpath.name}' already exists."
             logger.warning(f"WorkspaceManager: {error_msg}")
             self.file_operation_error.emit(error_msg)
             return None
        try:
            fpath.write_text('', encoding='utf-8')
            logger.info(f"WorkspaceManager: Created new file: {fpath}")
            # The caller (MainWindow) should handle refreshing the tree and loading the file
            return fpath
        except Exception as e:
             error_msg = f"Could not create file:\n{fpath}\n\nError: {e}"
             logger.error(f"WorkspaceManager: {error_msg}")
             self.file_operation_error.emit(error_msg)
             return None

    def apply_syntax_style(self, style_name: str):
        """Applies a new Pygments style to all currently open editors."""
        logger.info(f"WorkspaceManager: Applying syntax style '{style_name}' to {len(self.open_editors)} open editors.")
        if style_name not in AVAILABLE_PYGMENTS_STYLES:
            logger.warning(f"Cannot apply invalid style '{style_name}'. Falling back to '{DEFAULT_STYLE}'.")
            style_name = DEFAULT_STYLE

        for editor in self.open_editors.values():
            if hasattr(editor, 'highlighter') and isinstance(editor.highlighter, PygmentsHighlighter):
                try:
                    editor.highlighter.set_style(style_name)
                except Exception as e:
                    logger.error(f"Error applying style '{style_name}' to editor for {editor.objectName()}: {e}")
            else:
                 logger.warning(f"Editor for {editor.objectName()} has no valid PygmentsHighlighter.")