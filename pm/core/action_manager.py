# pm/core/action_manager.py
from typing import Optional
from PySide6.QtCore import QObject, Slot, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenuBar, QApplication, QPlainTextEdit
from loguru import logger
import qtawesome as qta

from ..core.logging_setup import LOG_PATH # For log action tooltip
from PySide6.QtGui import QDesktopServices  # For log action handler

class ActionManager(QObject):
    """Creates and manages global QActions and menus."""
    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self._main_window = parent
        logger.debug("Initializing ActionManager...")
        self._create_actions()
        logger.debug("ActionManager initialized.")

    def _create_actions(self):
        """Creates all QAction instances."""
        logger.debug("ActionManager: Creating actions...")
        # --- File Actions ---
        self.new_file_action = QAction(qta.icon('fa5s.file'), "&New File...", self._main_window, shortcut=QKeySequence.StandardKey.New, statusTip="Create a new file")
        self.new_file_action.setObjectName("new_file_action")
        self.open_project_action = QAction(qta.icon('fa5s.folder-open'), "&Open Project...", self._main_window, shortcut=QKeySequence.StandardKey.Open, statusTip="Open a project folder")
        self.open_project_action.setObjectName("open_project_action")
        self.save_file_action = QAction(qta.icon('fa5s.save'), "&Save", self._main_window, shortcut=QKeySequence.StandardKey.Save, statusTip="Save the current file")
        self.save_file_action.setObjectName("save_file_action")
        self.save_file_action.setEnabled(False) # Initially disabled
        self.quit_action = QAction("&Quit", self._main_window, shortcut=QKeySequence.StandardKey.Quit, statusTip="Exit the application")
        self.quit_action.setObjectName("quit_action")

        # --- Edit Actions ---
        self.undo_action = QAction(qta.icon('fa5s.undo'), "&Undo", self._main_window, shortcut=QKeySequence.StandardKey.Undo, statusTip="Undo last action")
        self.redo_action = QAction(qta.icon('fa5s.redo'), "&Redo", self._main_window, shortcut=QKeySequence.StandardKey.Redo, statusTip="Redo last undone action")
        self.cut_action = QAction(qta.icon('fa5s.cut'), "Cu&t", self._main_window, shortcut=QKeySequence.StandardKey.Cut, statusTip="Cut selection")
        self.copy_action = QAction(qta.icon('fa5s.copy'), "&Copy", self._main_window, shortcut=QKeySequence.StandardKey.Copy, statusTip="Copy selection")
        self.paste_action = QAction(qta.icon('fa5s.paste'), "&Paste", self._main_window, shortcut=QKeySequence.StandardKey.Paste, statusTip="Paste clipboard")

        # --- Settings Action ---
        self.settings_action = QAction(qta.icon('fa5s.cog'), "&Settings...", self._main_window, shortcut=QKeySequence.StandardKey.Preferences, statusTip="Open application settings")
        self.settings_action.setObjectName("settings_action")

        # --- Help Actions ---
        self.about_action = QAction("&About PatchMind...", self._main_window, statusTip="Show About dialog", triggered=self._main_window.show_about_dialog) # Connect directly
        self.show_logs_action = QAction("Show &Log Directory", self._main_window, statusTip=f"Open log directory ({LOG_PATH})", triggered=self._main_window.show_log_directory) # Connect directly

        # Connect standard edit actions to a helper slot
        self.undo_action.triggered.connect(lambda: self._call_editor_method('undo'))
        self.redo_action.triggered.connect(lambda: self._call_editor_method('redo'))
        self.cut_action.triggered.connect(lambda: self._call_editor_method('cut'))
        self.copy_action.triggered.connect(lambda: self._call_editor_method('copy'))
        self.paste_action.triggered.connect(lambda: self._call_editor_method('paste'))

        logger.debug("ActionManager: Actions created.")

    def create_menus(self, menu_bar: QMenuBar):
        """Creates and populates the main menus."""
        logger.debug("ActionManager: Creating menus...")
        # File Menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_file_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_file_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        # Edit Menu
        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.cut_action)
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)

        # Settings Menu
        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self.settings_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.show_logs_action)
        help_menu.addAction(self.about_action)
        logger.debug("ActionManager: Menus created.")

    def create_toolbars(self, main_window: QMainWindow):
        """Creates toolbars (if any)."""
        # No toolbars currently defined
        pass

    def _get_focused_editor(self) -> Optional[QPlainTextEdit]:
        """Helper to find the currently focused editor."""
        # This helper is needed here because edit actions are managed here.
        widget = QApplication.focusWidget()
        if isinstance(widget, QPlainTextEdit):
            # Check if it's one of the editors managed by WorkspaceManager (requires access)
            # For now, assume any focused QPlainTextEdit is the target
            return widget
        # Fallback: Check the current tab in the main editor tab widget
        # This requires access to the UIManager or the tab widget itself.
        # This part highlights the dependency issue. A better approach might be needed.
        # temp_tab_widget = self._main_window.ui.tab_widget # Accessing MainWindow's UI
        # current_tab_widget = temp_tab_widget.currentWidget()
        # if isinstance(current_tab_widget, QPlainTextEdit):
        #    return current_tab_widget
        return None

    @Slot(str)
    def _call_editor_method(self, method_name: str):
        """Calls a method on the currently focused editor."""
        editor = self._get_focused_editor()
        if editor:
            method = getattr(editor, method_name, None)
            if method and callable(method):
                logger.debug(f"ActionManager: Calling {method_name} on focused editor.")
                method()
            else:
                logger.warning(f"ActionManager: Focused editor has no method '{method_name}'.")
        else:
            logger.debug(f"ActionManager: Action '{method_name}' triggered, but no editor focused.")

    # --- Getters for specific actions needed by handlers ---
    @property
    def save_action(self) -> QAction: return self.save_file_action
    @property
    def new_file(self) -> QAction: return self.new_file_action
    @property
    def open_project(self) -> QAction: return self.open_project_action
    @property
    def quit(self) -> QAction: return self.quit_action
    @property
    def settings(self) -> QAction: return self.settings_action
    # Add others as needed

