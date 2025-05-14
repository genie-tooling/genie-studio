# pm/handlers/workspace_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer, QModelIndex
from PySide6.QtWidgets import ( QMainWindow, QTreeWidget, QTreeWidgetItem, QTabWidget,
                              QFileDialog, QMessageBox, QInputDialog,
                              QPlainTextEdit )
from PySide6.QtGui import QAction # Keep QAction for type hint if actions passed
from loguru import logger
from pathlib import Path
from typing import Optional

# --- Updated Imports ---
from ..core.app_core import AppCore
from ..core.workspace_manager import WorkspaceManager
from ..core.settings_service import SettingsService
from ..ui.controllers.status_bar_controller import StatusBarController
from ..core.action_manager import ActionManager # If passing ActionManager
from ..ui.main_window_ui import MainWindowUI # If passing UIManager

class WorkspaceActionHandler(QObject):
    """Handles file/project actions triggered by menus, toolbar, or file tree."""

    # Signals to MainWindow for dialogs or complex actions MainWindow still owns
    # show_status_message = Signal(str, int) # Replaced by direct StatusBarController interaction
    # show_error_message = Signal(str, str) # Replaced by direct QMessageBox calls

    def __init__(self,
                 # --- Dependencies ---
                 main_window: QMainWindow, # Still needed for dialog parent
                 core: AppCore,
                 ui: MainWindowUI,
                 actions: ActionManager, # Pass ActionManager
                 status_bar: StatusBarController,
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        self._main_window = main_window
        self._core = core
        self._ui = ui
        self._actions = actions
        self._status_bar = status_bar

        # --- Get Managers/Services/Widgets from dependencies ---
        self._workspace_manager: WorkspaceManager = core.workspace
        self._settings_service: SettingsService = core.settings
        self._file_tree: QTreeWidget = ui.file_tree
        self._tab_widget: QTabWidget = ui.tab_widget
        self._save_file_action: QAction = actions.save_action # Get specific action

        # --- Connect Menu Actions (from ActionManager) ---
        actions.new_file.triggered.connect(self.handle_new_file)
        actions.open_project.triggered.connect(self.handle_open_project)
        actions.save_action.triggered.connect(self.handle_save_active_file)
        actions.quit.triggered.connect(main_window.close) # Connect directly to MainWindow close

        # --- Connect File Tree Signals ---
        self._file_tree.itemDoubleClicked.connect(self.handle_tree_item_activated)
        # itemChanged connection is handled HERE now for check state logic
        self._file_tree.itemChanged.connect(self.handle_tree_item_changed)

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
        # (Logic remains the same)
        if not index.isValid(): return
        item = self._file_tree.itemFromIndex(index)
        if not item: return
        if index.column() == 0:
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                try:
                    path = Path(path_str)
                    if path.is_dir(): item.setExpanded(not item.isExpanded())
                except Exception as e: logger.warning(f"Error processing click: {e}")

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
                self._workspace_manager.populate_file_tree(self._file_tree) # Refresh tree
                editor = self._workspace_manager.load_file(new_file_path, self._tab_widget) # Open
                if editor: self._connect_current_editor_signals() # Connect signals for new editor
                self._status_bar.update_status(f"Created file: {file_name}", 3000) # Use status bar controller
        elif ok and not file_name:
             self._on_file_op_error("Filename cannot be empty.")

    @Slot()
    def handle_open_project(self):
        """Handles the 'Open Project Folder' action."""
        current_dir = str(self._workspace_manager.project_path or Path.home())
        new_dir = QFileDialog.getExistingDirectory(self._main_window, "Open Project Folder", current_dir)
        if new_dir:
            new_path = Path(new_dir)
            if not self.close_all_tabs(): return # User cancelled closing
            # Setting project path in WorkspaceManager triggers project_changed signal
            # SettingsService load is handled by MainWindow listening to workspace_manager.project_changed
            self._workspace_manager.set_project_path(new_path)
            # Let MainWindow handle SettingsService.load_project

    @Slot()
    def handle_save_active_file(self):
        """Handles the 'Save File' action for the currently active tab."""
        current_editor = self._tab_widget.currentWidget()
        if current_editor and isinstance(current_editor, QPlainTextEdit) and hasattr(current_editor, 'objectName') and current_editor.objectName():
            if current_editor.document().isModified():
                 saved = self._workspace_manager.save_tab_content(current_editor)
                 # _on_file_saved will show status message via status bar controller
                 # UI state update happens in _on_file_saved -> _update_ui_states
            else:
                 logger.debug("Save action triggered, but file not modified.")
                 self._status_bar.update_status("File not modified.", 2000) # Use status bar
        else:
            logger.debug("Save action triggered, but no valid editor is active.")
            self._status_bar.update_status("No active file to save.", 2000) # Use status bar

    @Slot(QTreeWidgetItem, int)
    def handle_tree_item_activated(self, item: QTreeWidgetItem, column: int):
        """Handles double-clicking or activating an item in the file tree."""
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str:
            path = Path(path_str)
            if path.is_file():
                logger.debug(f"Tree item activated: Loading file {path.name}")
                editor = self._workspace_manager.load_file(path, self._tab_widget)
                if editor: self._connect_current_editor_signals() # Connect signals

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
        # MainWindow handles title, SettingsService load. This handler updates tree & closes tabs.
        logger.info(f"WorkspaceActionHandler: Project changed to {new_project_path}. Refreshing tree.")
        self._workspace_manager.populate_file_tree(self._file_tree)
        self.close_all_tabs(confirm=False) # Force close without confirmation now
        self._update_ui_states()
        self._status_bar.update_status(f"Opened project: {new_project_path.name}", 3000) # Use status bar

    @Slot(Path)
    def _on_file_saved(self, file_path: Path):
        """Shows status message and updates UI state when file is saved."""
        self._status_bar.update_status(f"Saved: {file_path.name}", 2000) # Use status bar
        self._update_ui_states() # Update tab title and save button state

    @Slot(str)
    def _on_file_op_error(self, error_message: str):
        """Shows an error message dialog for file operation failures."""
        logger.error(f"WorkspaceActionHandler received file op error: {error_message}")
        # Show message box directly instead of emitting signal
        QMessageBox.critical(self._main_window, "File Operation Error", error_message)

    # --- UI State Updates ---
    @Slot()
    @Slot(bool) # Can be called by modificationChanged(bool) or directly
    def _update_ui_states(self, modified_state: Optional[bool] = None):
        """Updates the enabled state of actions and tab titles based on current context."""
        active_widget = self._tab_widget.currentWidget()
        has_active_editor = isinstance(active_widget, QPlainTextEdit)
        is_dirty = False
        if has_active_editor and hasattr(active_widget, 'document'):
             is_dirty = active_widget.document().isModified() if modified_state is None else modified_state

        # Update Save action state using the stored action
        self._save_file_action.setEnabled(has_active_editor and is_dirty)

        # Update tab title with dirty indicator '*'
        if has_active_editor:
             idx = self._tab_widget.indexOf(active_widget)
             if idx != -1:
                  tab_text = self._tab_widget.tabText(idx)
                  has_asterisk = tab_text.endswith('*')
                  if is_dirty and not has_asterisk: self._tab_widget.setTabText(idx, tab_text + '*')
                  elif not is_dirty and has_asterisk: self._tab_widget.setTabText(idx, tab_text[:-1])

    # --- Helper Methods ---
    def close_all_tabs(self, confirm: bool = True) -> bool:
         """Closes all open editor tabs, optionally confirming for unsaved changes."""
         # (Logic remains the same, using self._main_window for dialog parent)
         logger.debug(f"Attempting to close all tabs (Confirm: {confirm})...")
         unsaved_files = []
         indices_to_check = list(range(self._tab_widget.count()))
         for i in indices_to_check:
              widget = self._tab_widget.widget(i)
              if widget and isinstance(widget, QPlainTextEdit) and hasattr(widget, 'document') and widget.document().isModified():
                   tab_text = self._tab_widget.tabText(i).replace('*','')
                   unsaved_files.append(tab_text)
         if unsaved_files and confirm:
              reply = QMessageBox.warning(
                   self._main_window, "Unsaved Changes",
                   "The following files have unsaved changes:\n- " + "\n- ".join(unsaved_files) + "\n\nClose anyway?",
                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
              if reply == QMessageBox.StandardButton.Cancel: logger.info("User cancelled closing tabs."); return False
         while self._tab_widget.count() > 0:
              idx_to_close = self._tab_widget.count() - 1; widget_to_close = self._tab_widget.widget(idx_to_close)
              if widget_to_close:
                  if isinstance(widget_to_close, QPlainTextEdit) and hasattr(widget_to_close, 'document'):
                       try: widget_to_close.document().modificationChanged.disconnect(self._update_ui_states)
                       except RuntimeError: pass
                  self._workspace_manager.close_tab(idx_to_close, self._tab_widget)
              else: self._tab_widget.removeTab(idx_to_close)
         if self._workspace_manager.open_editors:
              logger.warning(f"open_editors dict not empty: {list(self._workspace_manager.open_editors.keys())}")
              self._workspace_manager.open_editors.clear(); self._workspace_manager.editors_changed.emit()
         return True

    # --- Recursive Check Handling ---
    @Slot(QTreeWidgetItem, int)
    def handle_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handles check state changes for recursive updates and status bar."""
        if column != 0 or not item: return

        # --- Update Status Bar ---
        # This is called frequently, debounce might be needed if performance issues arise
        #MainWindow handles token enforcement via its own connection to itemChanged
        # self._status_bar.update_token_count(...) # Needs calculation logic moved here or signal

        # --- Handle Recursive Directory Check ---
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str or not Path(path_str).is_dir(): return # Only dirs trigger recursion

        new_state = item.checkState(0)
        logger.debug(f"Directory '{item.text(0)}' changed state to {new_state}. Updating children...")
        tree = item.treeWidget()
        if not tree: return
        try:
            tree.blockSignals(True)
            self._set_child_check_state(item, new_state)
        finally:
            tree.blockSignals(False)
            # Trigger status update after recursive changes are done
            # MainWindow still handles enforcement

    def _set_child_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """Recursively sets the check state for all children."""
        # (Logic remains the same)
        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            if bool(child_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                child_item.setCheckState(0, state)
                child_path_str = child_item.data(0, Qt.ItemDataRole.UserRole)
                if child_path_str and Path(child_path_str).is_dir():
                    self._set_child_check_state(child_item, state)

