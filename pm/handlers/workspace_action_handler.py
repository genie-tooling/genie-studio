# pm/handlers/workspace_action_handler.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer, QModelIndex, QTimer
from PyQt6.QtWidgets import ( QMainWindow, QTreeWidget, QTreeWidgetItem, QTabWidget,
                              QFileDialog, QMessageBox, QInputDialog,
                            QWidget,  # QPlainTextEdit removed
                              )
from PyQt6.QtGui import QAction # Keep QAction for type hint if actions passed
from PyQt6.Qsci import QsciScintilla # Import QScintilla
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

    def __init__(self,
                 main_window: QMainWindow,
                 core: AppCore,
                 ui: MainWindowUI,
                 actions: ActionManager,
                 status_bar: StatusBarController,
                 parent: Optional[QObject] = None):
        super().__init__(parent)

        self._main_window = main_window
        self._core = core
        self._ui = ui
        self._actions = actions
        self._status_bar = status_bar

        self._workspace_manager: WorkspaceManager = core.workspace
        self._settings_service: SettingsService = core.settings
        self._file_tree: QTreeWidget = ui.file_tree
        self._tab_widget: QTabWidget = ui.tab_widget
        self._save_file_action: QAction = actions.save_action

        # Connect Menu Actions
        actions.new_file.triggered.connect(self.handle_new_file)
        actions.open_project.triggered.connect(self.handle_open_project)
        actions.save_action.triggered.connect(self.handle_save_active_file)
        actions.quit.triggered.connect(main_window.close)

        # Connect File Tree pyqtSignals
        self._file_tree.itemDoubleClicked.connect(self.handle_tree_item_activated)
        self._file_tree.itemChanged.connect(self.handle_tree_item_changed) # Keep connection

        # Connect Tab Widget pyqtSignals
        self._tab_widget.tabCloseRequested.connect(self.handle_close_tab_request)
        self._tab_widget.currentChanged.connect(self.handle_tab_changed)
        # Connect QScintilla's modificationChanged pyqtSignal
        self._tab_widget.currentChanged.connect(self._connect_current_editor_pyqtSignals)
        self._connect_current_editor_pyqtSignals() # Initial connect

        # Connect WorkspaceManager pyqtSignals
        self._workspace_manager.project_changed.connect(self._on_project_changed)
        self._workspace_manager.file_saved.connect(self._on_file_saved)
        self._workspace_manager.file_operation_error.connect(self._on_file_op_error)
        self._workspace_manager.editors_changed.connect(self._update_ui_states)

        self._update_ui_states()
        logger.info("WorkspaceActionHandler initialized and connected.")

    @pyqtSlot()
    def _connect_current_editor_pyqtSignals(self):
        """Connects modificationChanged pyqtSignal for the currently active QScintilla editor."""
        current_editor = self._tab_widget.currentWidget()
        if isinstance(current_editor, QsciScintilla):
            # Disconnect previous connections if any (safer)
            try: current_editor.modificationChanged.disconnect(self._update_ui_states)
            except (RuntimeError, TypeError): pass # Ignore if not connected or already gone
            # Connect the pyqtSignal
            current_editor.modificationChanged.connect(self._update_ui_states)
            logger.debug(f"Connected modificationChanged for QScintilla editor: {current_editor.objectName()}")

    @pyqtSlot()
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
                if editor: self._connect_current_editor_pyqtSignals() # Connect pyqtSignals for new editor
                self._status_bar.update_status(f"Created file: {file_name}", 3000)
        elif ok and not file_name:
             self._on_file_op_error("Filename cannot be empty.")

    @pyqtSlot()
    def handle_open_project(self):
        """Handles the 'Open Project Folder' action."""
        current_dir = str(self._workspace_manager.project_path or Path.home())
        new_dir = QFileDialog.getExistingDirectory(self._main_window, "Open Project Folder", current_dir)
        if new_dir:
            new_path = Path(new_dir)
            if not self.close_all_tabs(): return
            self._workspace_manager.set_project_path(new_path)

    @pyqtSlot()
    def handle_save_active_file(self):
        """Handles the 'Save File' action for the currently active tab."""
        current_editor = self._tab_widget.currentWidget()
        # Check if it's a QsciScintilla instance and has an object name (path)
        if isinstance(current_editor, QsciScintilla) and current_editor.objectName():
            # Use QScintilla's isModified method
            if current_editor.isModified():
                 saved = self._workspace_manager.save_tab_content(current_editor)
            else:
                 logger.debug("Save action triggered, but file not modified.")
                 self._status_bar.update_status("File not modified.", 2000)
        else:
            logger.debug("Save action triggered, but no valid QScintilla editor is active.")
            self._status_bar.update_status("No active file to save.", 2000)

    @pyqtSlot(QTreeWidgetItem, int)
    def handle_tree_item_activated(self, item: QTreeWidgetItem, column: int):
        """Handles double-clicking or activating an item in the file tree."""
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str:
            path = Path(path_str)
            if path.is_file():
                logger.debug(f"Tree item activated: Loading file {path.name}")
                editor = self._workspace_manager.load_file(path, self._tab_widget)
                if editor: self._connect_current_editor_pyqtSignals()

    @pyqtSlot(int)
    def handle_close_tab_request(self, index: int):
        """Handles the request to close a tab."""
        widget_to_close = self._tab_widget.widget(index)
        # Check if it's a QsciScintilla instance and if modified
        if isinstance(widget_to_close, QsciScintilla) and widget_to_close.isModified():
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

    @pyqtSlot(int)
    def handle_tab_changed(self, index: int):
         """Handles switching between tabs."""
         self._connect_current_editor_pyqtSignals()
         self._update_ui_states()

    @pyqtSlot(Path)
    def _on_project_changed(self, new_project_path: Path):
        """Updates UI elements when the project path changes."""
        logger.info(f"WorkspaceActionHandler: Project changed to {new_project_path}. Refreshing tree.")
        self._workspace_manager.populate_file_tree(self._file_tree)
        self.close_all_tabs(confirm=False)
        self._update_ui_states()
        self._status_bar.update_status(f"Opened project: {new_project_path.name}", 3000)

    @pyqtSlot(Path)
    def _on_file_saved(self, file_path: Path):
        """Shows status message and updates UI state when file is saved."""
        self._status_bar.update_status(f"Saved: {file_path.name}", 2000)
        self._update_ui_states()

    @pyqtSlot(str)
    def _on_file_op_error(self, error_message: str):
        """Shows an error message dialog for file operation failures."""
        logger.error(f"WorkspaceActionHandler received file op error: {error_message}")
        QMessageBox.critical(self._main_window, "File Operation Error", error_message)

    @pyqtSlot()
    @pyqtSlot(bool) # QScintilla's modificationChanged pyqtSignal emits bool
    def _update_ui_states(self, modified_state: Optional[bool] = None):
        """Updates the enabled state of actions and tab titles based on current context."""
        active_widget = self._tab_widget.currentWidget()
        has_active_editor = isinstance(active_widget, QsciScintilla)
        is_dirty = False
        if has_active_editor:
             # Use modificationChanged pyqtSignal's value if provided, otherwise query widget
             is_dirty = modified_state if modified_state is not None else active_widget.isModified()

        self._save_file_action.setEnabled(has_active_editor and is_dirty)

        if has_active_editor:
             idx = self._tab_widget.indexOf(active_widget)
             if idx != -1:
                  tab_text = self._tab_widget.tabText(idx)
                  has_asterisk = tab_text.endswith('*')
                  if is_dirty and not has_asterisk: self._tab_widget.setTabText(idx, tab_text + '*')
                  elif not is_dirty and has_asterisk: self._tab_widget.setTabText(idx, tab_text[:-1])

    def close_all_tabs(self, confirm: bool = True) -> bool:
         """Closes all open editor tabs, optionally confirming for unsaved changes."""
         logger.debug(f"Attempting to close all tabs (Confirm: {confirm})...")
         unsaved_files = []
         indices_to_check = list(range(self._tab_widget.count()))
         for i in indices_to_check:
              widget = self._tab_widget.widget(i)
              if isinstance(widget, QsciScintilla) and widget.isModified():
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
                  # Disconnect pyqtSignal before closing
                  if isinstance(widget_to_close, QsciScintilla):
                      try: widget_to_close.modificationChanged.disconnect(self._update_ui_states)
                      except (RuntimeError, TypeError): pass
                  self._workspace_manager.close_tab(idx_to_close, self._tab_widget)
              else: self._tab_widget.removeTab(idx_to_close)
         if self._workspace_manager.open_editors:
              logger.warning(f"open_editors dict not empty after closing tabs: {list(self._workspace_manager.open_editors.keys())}")
              self._workspace_manager.open_editors.clear(); self._workspace_manager.editors_changed.emit()
         return True

    @pyqtSlot(QTreeWidgetItem, int)
    def handle_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handles check state changes for recursive updates."""
        # Status bar update is handled by MainWindow connecting to this pyqtSignal
        if column != 0 or not item: return

        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str or not Path(path_str).is_dir(): return

        new_state = item.checkState(0)
        logger.debug(f"Directory '{item.text(0)}' changed state to {new_state}. Updating children...")
        tree = item.treeWidget()
        if not tree: return
        try:
            tree.blockSignals(True)
            self._set_child_check_state(item, new_state)
        finally:
            tree.blockSignals(False)
            # MainWindow handles token enforcement

    def _set_child_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """Recursively sets the check state for all children."""
        for i in range(parent_item.childCount()):
            child_item = parent_item.child(i)
            if bool(child_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                child_item.setCheckState(0, state)
                child_path_str = child_item.data(0, Qt.ItemDataRole.UserRole)
                if child_path_str and Path(child_path_str).is_dir():
                    self._set_child_check_state(child_item, state)
