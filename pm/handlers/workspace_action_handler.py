# pm/handlers/workspace_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer, QModelIndex # Added QTimer
from PySide6.QtWidgets import ( QMainWindow, QTreeWidget, QTreeWidgetItem, QTabWidget,
                              QFileDialog, QMessageBox, QLineEdit, QInputDialog,
                              QPlainTextEdit ) # Added QPlainTextEdit
from PySide6.QtGui import QAction
from loguru import logger
from pathlib import Path
from typing import Optional

from ..core.workspace_manager import WorkspaceManager
from ..core.settings_service import SettingsService # Needed to get project path

class WorkspaceActionHandler(QObject):
    """Handles file/project actions triggered by menus, toolbar, or file tree."""

    # Signals to MainWindow for actions requiring top-level handling
    show_status_message = Signal(str, int) # message, timeout_ms
    show_error_message = Signal(str, str) # title, message

    def __init__(self,
                 main_window: QMainWindow, # For dialogs, status bar access
                 workspace_manager: WorkspaceManager,
                 settings_service: SettingsService, # To get/set project path
                 file_tree: QTreeWidget,
                 tab_widget: QTabWidget,
                 # --- Menu Actions (pass from MainWindow) ---
                 new_file_action: QAction,
                 open_project_action: QAction,
                 save_file_action: QAction, # Passed in
                 quit_action: QAction,
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        self._main_window = main_window # Store reference for later use
        self._workspace_manager = workspace_manager
        self._settings_service = settings_service
        self._file_tree = file_tree
        self._tab_widget = tab_widget
        # --- *** STORE THE ACTION *** ---
        self._save_file_action = save_file_action # Store as instance variable

        # --- Connect Menu Actions ---
        new_file_action.triggered.connect(self.handle_new_file)
        open_project_action.triggered.connect(self.handle_open_project)
        # Use the passed-in action directly for the connection
        save_file_action.triggered.connect(self.handle_save_active_file)
        quit_action.triggered.connect(main_window.close) # Connect directly

        # --- Connect File Tree Signals ---
        self._file_tree.itemDoubleClicked.connect(self.handle_tree_item_activated)
        # itemChanged connection is handled in MainWindow

        # --- Connect Tab Widget Signals ---
        self._tab_widget.tabCloseRequested.connect(self.handle_close_tab_request)
        self._tab_widget.currentChanged.connect(self.handle_tab_changed) # Update save button state
        # Connect document modification signal to update UI state
        self._tab_widget.currentChanged.connect(self._connect_current_editor_signals) # Connect on tab change
        # Also connect for the initial widget if any
        self._connect_current_editor_signals()


        # --- Connect WorkspaceManager Signals ---
        self._workspace_manager.project_changed.connect(self._on_project_changed)
        self._workspace_manager.file_saved.connect(self._on_file_saved)
        self._workspace_manager.file_operation_error.connect(self._on_file_op_error)
        self._workspace_manager.editors_changed.connect(self._update_ui_states) # Update save button

        # --- Initial State ---
        self._update_ui_states()
        logger.info("WorkspaceActionHandler initialized and connected.")

    # --- Slot to connect editor signals ---
    @Slot()
    def _connect_current_editor_signals(self):
        """Connects modificationChanged signal for the currently active editor."""
        current_editor = self._tab_widget.currentWidget()
        if isinstance(current_editor, QPlainTextEdit) and hasattr(current_editor, 'document'):
             # Disconnect previous connections if any (optional, but safer)
             # try: current_editor.document().modificationChanged.disconnect(self._update_ui_states)
             # except RuntimeError: pass
             # Connect the signal
             current_editor.document().modificationChanged.connect(self._update_ui_states)
             logger.debug(f"Connected modificationChanged for editor: {current_editor.objectName()}")


    # --- Action Handlers (Slots) ---
    @Slot(QModelIndex)
    def handle_tree_item_clicked(self, index: QModelIndex):
        """Handles single-clicking on an item, toggling directory expansion if name clicked."""
        if not index.isValid():
            return

        item = self._file_tree.itemFromIndex(index)
        if not item:
            return

        # Check if the click was specifically on column 0 (the name column)
        if index.column() == 0:
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                try:
                    path = Path(path_str)
                    # If it's a directory, toggle its expansion state
                    if path.is_dir():
                        is_expanded = item.isExpanded()
                        item.setExpanded(not is_expanded)
                        logger.trace(f"Toggled expansion for directory '{item.text(0)}' via click.")
                        # Prevent the double-click from also firing immediately after? (Optional)
                        # QApplication.processEvents() # Might help, might cause issues. Test if needed.

                    # If it was a file click on column 0, do nothing extra here.
                    # The default selection behavior will still happen.

                except Exception as e:
                    logger.warning(f"Error processing click on tree item {item.text(0)}: {e}")

    @Slot()
    def handle_new_file(self):
        """Handles the 'New File' action."""
        if not self._workspace_manager.project_path:
             self._on_file_op_error("Cannot create file: No project open.")
             return

        file_name, ok = QInputDialog.getText(self._main_window, "New File", "Enter filename:")
        if ok and file_name:
            new_file_path = self._workspace_manager.create_new_file(file_name)
            if new_file_path:
                # Refresh tree and open the new file
                self._workspace_manager.populate_file_tree(self._file_tree) # Refresh tree
                editor = self._workspace_manager.load_file(new_file_path, self._tab_widget) # Open in editor
                if editor: self._connect_current_editor_signals() # Connect signals for new editor
                self.show_status_message.emit(f"Created file: {file_name}", 3000)
        elif ok and not file_name:
             self._on_file_op_error("Filename cannot be empty.")


    @Slot()
    def handle_open_project(self):
        """Handles the 'Open Project Folder' action."""
        current_dir = str(self._workspace_manager.project_path or Path.home())
        new_dir = QFileDialog.getExistingDirectory(
            self._main_window, "Open Project Folder", current_dir
        )
        if new_dir:
            new_path = Path(new_dir)
            if not self.close_all_tabs(): return # User cancelled closing

            self._workspace_manager.set_project_path(new_path)
            if not self._settings_service.load_project(new_path):
                 self._on_file_op_error(f"Failed to load settings for {new_path.name}")


    @Slot()
    def handle_save_active_file(self):
        """Handles the 'Save File' action for the currently active tab."""
        current_editor = self._tab_widget.currentWidget()
        if current_editor and isinstance(current_editor, QPlainTextEdit) and hasattr(current_editor, 'objectName') and current_editor.objectName():
            # Only save if modified
            if current_editor.document().isModified():
                 saved = self._workspace_manager.save_tab_content(current_editor)
                 if saved:
                      # _on_file_saved will show status message
                      # Update UI state (which will remove dirty indicator)
                      self._update_ui_states()
            else:
                 logger.debug("Save action triggered, but file not modified.")
                 self.show_status_message.emit("File not modified.", 2000)

        else:
            logger.debug("Save action triggered, but no valid editor is active.")
            self.show_status_message.emit("No active file to save.", 2000)


    @Slot(QTreeWidgetItem, int)
    def handle_tree_item_activated(self, item: QTreeWidgetItem, column: int):
        """Handles double-clicking or activating an item in the file tree."""
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str:
            path = Path(path_str)
            if path.is_file():
                logger.debug(f"Tree item activated: Loading file {path.name}")
                editor = self._workspace_manager.load_file(path, self._tab_widget)
                if editor: self._connect_current_editor_signals()


    @Slot(int)
    def handle_close_tab_request(self, index: int):
        """Handles the request to close a tab (e.g., clicking the 'x' button)."""
        widget_to_close = self._tab_widget.widget(index)
        if widget_to_close and isinstance(widget_to_close, QPlainTextEdit) and hasattr(widget_to_close, 'document') and widget_to_close.document().isModified():
            reply = QMessageBox.question(
                self._main_window, "Unsaved Changes",
                f"Save changes to '{self._tab_widget.tabText(index).replace('*','')}' before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel: return
            if reply == QMessageBox.StandardButton.Save:
                if not self._workspace_manager.save_tab_content(widget_to_close):
                    self._on_file_op_error(f"Failed to save {self._tab_widget.tabText(index)} on close.")
                    return # Don't close if save failed

        logger.info(f"Closing tab at index {index}")
        self._workspace_manager.close_tab(index, self._tab_widget)


    @Slot(int)
    def handle_tab_changed(self, index: int):
         """Handles switching between tabs."""
         self._connect_current_editor_signals() # Connect signals for the newly focused editor
         self._update_ui_states() # Update save button enable state


    # --- WorkspaceManager Signal Handlers ---

    @Slot(Path)
    def _on_project_changed(self, new_project_path: Path):
        """Updates UI elements when the project path changes."""
        logger.info(f"WorkspaceActionHandler: Project changed to {new_project_path}. Refreshing tree.")
        self._main_window.setWindowTitle(f"PatchMind IDE - {new_project_path.name}")
        self._workspace_manager.populate_file_tree(self._file_tree)
        self.close_all_tabs(confirm=False) # Force close without confirmation now
        self._update_ui_states()
        self.show_status_message.emit(f"Opened project: {new_project_path.name}", 3000)

    @Slot(Path)
    def _on_file_saved(self, file_path: Path):
        """Shows a status message when a file is saved successfully."""
        self.show_status_message.emit(f"Saved: {file_path.name}", 2000)
        # Update tab title to remove dirty indicator '*' - Handled by _update_ui_states now
        # Update UI state directly after save confirms modified is false
        self._update_ui_states()


    @Slot(str)
    def _on_file_op_error(self, error_message: str):
        """Shows an error message dialog for file operation failures."""
        logger.error(f"WorkspaceActionHandler received file op error: {error_message}")
        self.show_error_message.emit("File Operation Error", error_message)


    # --- UI State Updates ---

    @Slot()
    @Slot(bool) # Can be called by modificationChanged(bool) or directly
    def _update_ui_states(self, modified_state: Optional[bool] = None):
        """Updates the enabled state of actions and tab titles based on current context."""
        active_widget = self._tab_widget.currentWidget()
        has_active_editor = isinstance(active_widget, QPlainTextEdit)
        is_dirty = False

        if has_active_editor and hasattr(active_widget, 'document'):
             # Use the signal's argument if available, otherwise query the document
             if modified_state is not None:
                 is_dirty = modified_state
             else:
                 is_dirty = active_widget.document().isModified()

        # Update Save action state using the stored action
        # --- *** USE THE STORED ACTION *** ---
        if self._save_file_action:
            self._save_file_action.setEnabled(has_active_editor and is_dirty)
        # --- ************************** ---


        # Update tab title with dirty indicator '*'
        if has_active_editor:
             idx = self._tab_widget.indexOf(active_widget)
             if idx != -1:
                  tab_text = self._tab_widget.tabText(idx)
                  # Ensure we don't add multiple asterisks
                  has_asterisk = tab_text.endswith('*')
                  if is_dirty and not has_asterisk:
                       self._tab_widget.setTabText(idx, tab_text + '*')
                  elif not is_dirty and has_asterisk:
                       self._tab_widget.setTabText(idx, tab_text[:-1])


    # --- Helper Methods ---

    def close_all_tabs(self, confirm: bool = True) -> bool:
         """Closes all open editor tabs, optionally confirming for unsaved changes."""
         logger.debug(f"Attempting to close all tabs (Confirm: {confirm})...")
         unsaved_files = []
         indices_to_check = list(range(self._tab_widget.count())) # Get indices before modification

         for i in indices_to_check:
              widget = self._tab_widget.widget(i)
              if widget and isinstance(widget, QPlainTextEdit) and hasattr(widget, 'document') and widget.document().isModified():
                   tab_text = self._tab_widget.tabText(i).replace('*','')
                   unsaved_files.append(tab_text)

         if unsaved_files and confirm:
              reply = QMessageBox.warning(
                   self._main_window,
                   "Unsaved Changes",
                   "The following files have unsaved changes:\n- " + "\n- ".join(unsaved_files) + "\n\nClose anyway?",
                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                   QMessageBox.StandardButton.Cancel
              )
              if reply == QMessageBox.StandardButton.Cancel:
                   logger.info("User cancelled closing tabs due to unsaved changes.")
                   return False # User cancelled

         # Close tabs safely, iterating backwards by index
         while self._tab_widget.count() > 0:
              idx_to_close = self._tab_widget.count() - 1
              widget_to_close = self._tab_widget.widget(idx_to_close)
              if widget_to_close:
                  # Disconnect modification signal before closing to avoid issues
                  if isinstance(widget_to_close, QPlainTextEdit) and hasattr(widget_to_close, 'document'):
                       try: widget_to_close.document().modificationChanged.disconnect(self._update_ui_states)
                       except RuntimeError: pass
                  self._workspace_manager.close_tab(idx_to_close, self._tab_widget)
              else:
                  logger.warning(f"Widget at index {idx_to_close} was None during close_all_tabs. Removing tab entry.")
                  self._tab_widget.removeTab(idx_to_close)

         # Double check editor dict is empty
         if self._workspace_manager.open_editors:
              logger.warning(f"open_editors dict not empty after close_all_tabs: {list(self._workspace_manager.open_editors.keys())}")
              self._workspace_manager.open_editors.clear()
              self._workspace_manager.editors_changed.emit()

         return True

    # --- Slot for Recursive Check Handling ---
    @Slot(QTreeWidgetItem, int)
    def handle_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handles check state changes for recursive updates."""
        if column != 0 or not item: # Only handle changes in the checkbox column
            return

        # Check if it's a directory item that was changed
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str or not Path(path_str).is_dir():
            return # Only directories trigger recursive changes

        new_state = item.checkState(0)
        logger.debug(f"Directory '{item.text(0)}' changed state to {new_state}. Updating children...")

        # Block signals during recursive update
        tree = item.treeWidget()
        if not tree: return
        try:
            tree.blockSignals(True)
            self._set_child_check_state(item, new_state)
        finally:
            tree.blockSignals(False)
            # Status bar token update is handled by MainWindow's connection


    def _set_child_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """Recursively sets the check state for all children."""
        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            # Only change if the item is actually checkable
            if bool(child_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                child_item.setCheckState(0, state)
                # Recurse only if the child is also a directory
                child_path_str = child_item.data(0, Qt.ItemDataRole.UserRole)
                if child_path_str and Path(child_path_str).is_dir():
                    self._set_child_check_state(child_item, state)

