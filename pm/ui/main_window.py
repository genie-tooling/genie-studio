# pm/ui/main_window.py
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QApplication, QStatusBar, QSplitter, QPlainTextEdit,
                             QMessageBox, QFileDialog, QTreeWidget, QDockWidget,
                             QListWidget, QPushButton, QTabWidget, QLabel,
                             QHeaderView, QSizePolicy, QTreeWidgetItemIterator, QTreeWidgetItem,
                             QMenu)
from PySide6.QtGui import QAction, QKeySequence, QFont, QIcon, QDesktopServices, QCursor
from PySide6.QtCore import Qt, Slot, QSize, QTimer, QUrl, QPoint
from loguru import logger
import qtawesome as qta
from functools import partial

# --- Core Components ---
from ..core.logging_setup import LOG_PATH
from ..core.settings_service import SettingsService
from ..core.llm_service_provider import LLMServiceProvider
from ..core.model_list_service import ModelListService
from ..core.workspace_manager import WorkspaceManager
from ..core.chat_manager import ChatManager
from ..core.task_manager import BackgroundTaskManager
from ..core.constants import TOKEN_COUNT_ROLE

# --- UI Components ---
from .config_dock import ConfigDock

# --- Handlers ---
from ..handlers.chat_action_handler import ChatActionHandler
from ..handlers.workspace_action_handler import WorkspaceActionHandler
from ..handlers.prompt_action_handler import PromptActionHandler
from ..handlers.settings_action_handler import SettingsActionHandler


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow...")
        self._enforce_limit_timer = QTimer(self)
        self._enforce_limit_timer.setSingleShot(True)
        self._enforce_limit_timer.setInterval(150)
        self._enforce_limit_timer.timeout.connect(self._check_and_enforce_token_limit)

        # --- Initialize Core Services and Managers ---
        self.settings_service = SettingsService(self)
        self.llm_provider = LLMServiceProvider(self.settings_service, self)
        self.model_list_service = ModelListService(self)
        initial_path = Path(self.settings_service.get_setting('last_project_path', str(Path.cwd())))
        if not initial_path.is_dir():
             initial_path = Path.cwd()
        self.workspace_manager = WorkspaceManager(initial_path, self.settings_service.get_all_settings(), self)
        self.chat_manager = ChatManager(self)
        self.task_manager = BackgroundTaskManager(self.settings_service, self)

        # Load initial project settings
        if not self.settings_service.load_project(initial_path):
             QMessageBox.warning(self, "Project Load Error", f"Could not load settings for initial path:\n{initial_path}\nUsing default settings.")
             self.workspace_manager.set_project_path(Path.cwd()) # Set to CWD if load fails

        # Update task manager services *after* project load
        self.task_manager.set_services(self.llm_provider.get_model_service(), self.llm_provider.get_summarizer_service())

        # --- Initialize UI ---
        self._setup_ui() # ConfigDock created here, gets initial settings
        self._create_actions()
        self._create_menus()
        self._create_toolbars()

        # --- Initialize Action Handlers ---
        self._init_handlers()

        # --- Connect Signals ---
        self._connect_signals()

        # --- Final Setup & State ---
        geom = self.settings_service.get_setting("main_window_geometry")
        state = self.settings_service.get_setting("main_window_state")
        if geom:
             self.restoreGeometry(geom)
        if state:
             self.restoreState(state)
        self._populate_initial_state() # Populates tree, dock, etc.

        logger.info("MainWindow initialization complete.")
        self.show()


    # --- UI Setup Methods ---
    def _setup_ui(self):
        logger.debug("Setting up UI...")
        self.setWindowTitle(f"PatchMind IDE")
        self.setMinimumSize(1200, 700)

        # Column 1: File Tree & Controls
        self.file_tree_container = QWidget()
        file_tree_layout = QVBoxLayout(self.file_tree_container)
        file_tree_layout.setContentsMargins(0,0,0,0)
        file_tree_layout.setSpacing(2)
        self.file_tree_widget = QTreeWidget()
        self.file_tree_widget.setObjectName("file_tree")
        self.file_tree_widget.setColumnCount(2)
        self.file_tree_widget.setHeaderLabels(["Name", "Tokens"])
        self.file_tree_widget.header().setStretchLastSection(False)
        self.file_tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree_widget.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.file_tree_widget.header().resizeSection(1, 70)
        self.file_tree_widget.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.file_tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        file_tree_layout.addWidget(self.file_tree_widget, 1)

        tree_button_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.deselect_all_button = QPushButton("Deselect All")
        tree_button_layout.addWidget(self.select_all_button)
        tree_button_layout.addWidget(self.deselect_all_button)
        file_tree_layout.addLayout(tree_button_layout)

        # Column 2: Editor Tabs
        self.editor_tab_widget = QTabWidget()
        self.editor_tab_widget.setObjectName("editor_tabs")
        self.editor_tab_widget.setTabsClosable(True)
        self.editor_tab_widget.setMovable(True)
        self.editor_tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Column 3: Chat Area
        self.chat_area_widget = QWidget()
        chat_layout = QVBoxLayout(self.chat_area_widget)
        chat_layout.setContentsMargins(5,5,5,5)
        chat_layout.setSpacing(5)
        self.chat_list_widget = QListWidget()
        self.chat_list_widget.setObjectName("chat_list_widget")
        self.chat_list_widget.setAlternatingRowColors(True)
        self.chat_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        chat_layout.addWidget(self.chat_list_widget, 1)

        chat_input_layout = QHBoxLayout()
        chat_input_layout.setSpacing(5)
        self.chat_input_edit = QPlainTextEdit()
        self.chat_input_edit.setObjectName("chat_input")
        self.chat_input_edit.setPlaceholderText("Enter your message or /command...")
        self.chat_input_edit.setFixedHeight(60)
        self.chat_input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        chat_input_layout.addWidget(self.chat_input_edit, 1)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("send_btn")
        self.send_button.setIcon(qta.icon('fa5s.paper-plane', color='white'))
        self.send_button.setFixedHeight(60)
        self.send_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        chat_input_layout.addWidget(self.send_button)
        chat_layout.addLayout(chat_input_layout)
        self.chat_area_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Column 4: Config Dock (Widget)
        # ConfigDock is passed the current effective settings
        self.config_dock = ConfigDock(self.settings_service.get_all_settings(), self)
        self.config_dock.setObjectName("config_dock")
        self.config_dock.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)

        # Main Horizontal Splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.main_splitter.addWidget(self.file_tree_container)
        self.main_splitter.addWidget(self.editor_tab_widget)
        self.main_splitter.addWidget(self.chat_area_widget)
        self.main_splitter.addWidget(self.config_dock)
        self.setCentralWidget(self.main_splitter)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Ready.")
        self.status_bar.addWidget(self.status_label, 1)
        self.token_label = QLabel("Selected: 0 / 0")
        self.token_label.setObjectName("token_label")
        self.token_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status_bar.addPermanentWidget(self.token_label)

        # Initial Splitter Sizes
        tree_width = 200
        editor_width = 400
        chat_width = 400
        config_width = 250
        self.main_splitter.setSizes([tree_width, editor_width, chat_width, config_width])
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setCollapsible(3, False)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 1)

        logger.debug("UI setup complete.")


    def _init_handlers(self):
        """Create handler instances."""
        logger.debug("Initializing handlers...")
        self.chat_handler = ChatActionHandler(
            chat_input=self.chat_input_edit,
            send_button=self.send_button,
            chat_list_widget=self.chat_list_widget,
            chat_manager=self.chat_manager,
            task_manager=self.task_manager,
            get_checked_files_callback=self._get_checked_file_paths,
            get_project_path_callback=lambda: self.workspace_manager.project_path,
            parent=self
        )
        self.workspace_handler = WorkspaceActionHandler(
            main_window=self,
            workspace_manager=self.workspace_manager,
            settings_service=self.settings_service,
            file_tree=self.file_tree_widget,
            tab_widget=self.editor_tab_widget,
            new_file_action=self.new_file_action,
            open_project_action=self.open_project_action,
            save_file_action=self.save_file_action,
            quit_action=self.quit_action,
            parent=self
        )
        self.prompt_handler = PromptActionHandler(
             main_window=self,
             settings_service=self.settings_service,
             config_dock=self.config_dock,
             parent=self
        )
        self.settings_handler = SettingsActionHandler(
             main_window=self,
             settings_service=self.settings_service,
             model_list_service=self.model_list_service,
             workspace_manager=self.workspace_manager,
             open_settings_action=self.settings_action,
             parent=self
        )
        logger.debug("Handlers initialized.")


    def _create_actions(self):
        logger.debug("Creating actions...")
        self.new_file_action = QAction(qta.icon('fa5s.file'), "&New File...", self, shortcut=QKeySequence.StandardKey.New, statusTip="Create a new file")
        self.new_file_action.setObjectName("new_file_action")
        self.open_project_action = QAction(qta.icon('fa5s.folder-open'), "&Open Project...", self, shortcut=QKeySequence.StandardKey.Open, statusTip="Open a project folder")
        self.open_project_action.setObjectName("open_project_action")
        self.save_file_action = QAction(qta.icon('fa5s.save'), "&Save", self, shortcut=QKeySequence.StandardKey.Save, statusTip="Save the current file")
        self.save_file_action.setObjectName("save_file_action")
        self.save_file_action.setEnabled(False)
        self.quit_action = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit, statusTip="Exit the application")
        self.quit_action.setObjectName("quit_action")
        self.undo_action = QAction(qta.icon('fa5s.undo'), "&Undo", self, shortcut=QKeySequence.StandardKey.Undo, statusTip="Undo last action")
        self.redo_action = QAction(qta.icon('fa5s.redo'), "&Redo", self, shortcut=QKeySequence.StandardKey.Redo, statusTip="Redo last undone action")
        self.cut_action = QAction(qta.icon('fa5s.cut'), "Cu&t", self, shortcut=QKeySequence.StandardKey.Cut, statusTip="Cut selection")
        self.copy_action = QAction(qta.icon('fa5s.copy'), "&Copy", self, shortcut=QKeySequence.StandardKey.Copy, statusTip="Copy selection")
        self.paste_action = QAction(qta.icon('fa5s.paste'), "&Paste", self, shortcut=QKeySequence.StandardKey.Paste, statusTip="Paste clipboard")
        self.settings_action = QAction(qta.icon('fa5s.cog'), "&Settings...", self, shortcut=QKeySequence.StandardKey.Preferences, statusTip="Open application settings")
        self.settings_action.setObjectName("settings_action")
        self.about_action = QAction("&About PatchMind...", self, statusTip="Show About dialog", triggered=self.show_about_dialog)
        self.show_logs_action = QAction("Show &Log Directory", self, statusTip=f"Open log directory ({LOG_PATH})", triggered=self.show_log_directory)

        # Editor actions connected here for simplicity
        self.undo_action.triggered.connect(lambda: self._call_editor_method('undo'))
        self.redo_action.triggered.connect(lambda: self._call_editor_method('redo'))
        self.cut_action.triggered.connect(lambda: self._call_editor_method('cut'))
        self.copy_action.triggered.connect(lambda: self._call_editor_method('copy'))
        self.paste_action.triggered.connect(lambda: self._call_editor_method('paste'))
        logger.debug("Actions created.")


    def _call_editor_method(self, method_name: str):
        editor = self._get_focused_editor()
        if editor:
            method = getattr(editor, method_name, None)
            if method and callable(method):
                 method()
            else:
                 logger.warning(f"Focused editor has no method '{method_name}'")
        else:
            logger.debug(f"Action '{method_name}', but no editor focused.")


    def _create_menus(self):
        logger.debug("Creating menus...")
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_file_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_file_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.cut_action)
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self.settings_action)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.show_logs_action)
        help_menu.addAction(self.about_action)
        logger.debug("Menus created.")


    def _create_toolbars(self):
        # No toolbar for now
        pass


    # --- Signal Connections ---
    def _connect_signals(self):
        logger.debug("Connecting MainWindow signals...")
        # Task Manager -> UI updates
        self.task_manager.status_update.connect(self._update_status_bar)
        self.task_manager.generation_started.connect(self._disable_ui_for_generation)
        self.task_manager.generation_finished.connect(self._enable_ui_after_generation)
        self.task_manager.stream_error.connect(self._handle_task_error)

        # Settings service -> UI updates / Repopulate Dock
        self.settings_service.project_path_changed.connect(lambda path: self.setWindowTitle(f"PatchMind IDE - {path.name}"))
        self.settings_service.settings_loaded.connect(self._populate_config_dock_from_settings)
        self.settings_service.settings_changed.connect(self._handle_setting_change_for_dock)

        # LLM Provider -> Update ConfigDock and Status Bar limits
        self.llm_provider.context_limit_changed.connect(self.config_dock.update_context_limit_display)
        self.llm_provider.context_limit_changed.connect(self._update_token_display_limit)
        self.llm_provider.services_updated.connect(
            lambda: self.task_manager.set_services(
                self.llm_provider.get_model_service(),
                self.llm_provider.get_summarizer_service()
            )
        )

        # File Tree -> Handlers & Internal Slots
        self.file_tree_widget.itemChanged.connect(self._handle_tree_item_changed)
        self.file_tree_widget.itemChanged.connect(self.workspace_handler.handle_tree_item_changed)
        self.file_tree_widget.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.select_all_button.clicked.connect(self._select_all_tree_items)
        self.deselect_all_button.clicked.connect(self._deselect_all_tree_items)

        # Workspace handler -> Status/Error Feedback
        self.workspace_handler.show_status_message.connect(self._update_status_bar)
        self.workspace_handler.show_error_message.connect(self._show_error_message)

        # Config Dock -> Settings Service (signals SETTING changes)
        self.config_dock.provider_changed.connect(lambda p: self.settings_service.set_setting('provider', p))
        self.config_dock.model_changed.connect(lambda m: self.settings_service.set_setting('model', m))
        self.config_dock.llm_params_changed.connect(self._update_llm_params_from_dock)
        self.config_dock.rag_toggle_changed.connect(lambda key, state: self.settings_service.set_setting(key, state))

        # Config Dock -> Model List Request
        self.config_dock.request_model_list_refresh.connect(self._refresh_config_dock_models)

        # Prompt signals connected in PromptActionHandler

        # Model List Service -> Update Config Dock UI
        self.model_list_service.llm_models_updated.connect(self._update_config_dock_model_list)
        self.model_list_service.model_refresh_error.connect(self._handle_config_dock_model_error)

        logger.debug("MainWindow signals connected.")


    # --- Initial State Population ---
    def _populate_initial_state(self):
        """Populates UI elements based on the initially loaded state."""
        logger.debug("Populating initial state...")
        self.workspace_manager.populate_file_tree(self.file_tree_widget)

        logger.debug("Explicitly updating context limit displays post-init...")
        initial_limit = self.llm_provider.get_context_limit()
        self.config_dock.update_context_limit_display(initial_limit)
        self._update_status_token_display() # Update status bar

        self._refresh_config_dock_models() # Trigger model list refresh
        QTimer.singleShot(50, self._check_and_enforce_token_limit)
        logger.debug("Initial state populated and displays updated.")


    # --- Slots for Handling Signals ---
    @Slot(str)
    @Slot(str, int)
    def _update_status_bar(self, message: str, timeout: int = 0):
        logger.debug(f"Updating status bar: '{message}' (Timeout: {timeout}ms)")
        self.status_label.setText(message)
        if timeout > 0:
            expected_message = message
            QTimer.singleShot(timeout, lambda: self.status_label.setText("Ready.") if self.status_label.text() == expected_message else None)


    @Slot(int)
    def _update_token_display_limit(self, max_tokens: int):
         """Handles the context_limit_changed signal to update UI and enforce."""
         logger.debug(f"Slot _update_token_display_limit received max_tokens={max_tokens}.")
         self._update_status_token_display()
         self._check_and_enforce_token_limit()


    @Slot()
    def _update_status_token_display(self):
         """Calculates and updates the token count display for CHECKED items."""
         total_tokens = self._get_checked_tokens()
         max_tokens = self.llm_provider.get_context_limit()
         logger.trace(f"Updating status token display: Selected={total_tokens} / Max={max_tokens}")
         self.token_label.setText(f"Selected: {total_tokens:,} / {max_tokens:,}")
         if total_tokens > max_tokens and max_tokens > 0:
              self.token_label.setStyleSheet("color: orange;")
         else:
              self.token_label.setStyleSheet("") # Reset style


    @Slot(str, str)
    def _show_error_message(self, title: str, message: str):
        logger.error(f"Displaying Error - Title: {title}, Message: {message}")
        QMessageBox.critical(self, title, message)


    @Slot(str)
    def _handle_task_error(self, error_message: str):
        self._show_error_message("LLM Task Error", error_message)
        self._enable_ui_after_generation(False)


    @Slot()
    def _disable_ui_for_generation(self):
        logger.debug("Disabling UI during generation.")
        self.settings_action.setEnabled(False)
        self.config_dock.setEnabled(False)
        self.chat_input_edit.setEnabled(False)
        try:
            self.send_button.clicked.disconnect()
            logger.trace("Disconnected existing send_button click signal.")
        except RuntimeError:
            logger.trace("No existing send_button click signal to disconnect.")
        except Exception as e:
            logger.warning(f"Unexpected error disconnecting send_button: {e}")

        self.send_button.setText("Stop")
        self.send_button.setIcon(qta.icon('fa5s.stop-circle', color='red'))
        self.send_button.setEnabled(True)
        try:
            self.send_button.clicked.connect(self.task_manager.stop_generation)
            logger.trace("Connected stop_generation to send_button.")
        except Exception as e:
            logger.error(f"Error connecting stop_generation: {e}")
            self.send_button.setEnabled(False)
            self.send_button.setText("Error")


    @Slot(bool)
    def _enable_ui_after_generation(self, stopped_by_user: bool):
        logger.debug(f"Re-enabling UI after generation. Stopped by user: {stopped_by_user}")
        self.settings_action.setEnabled(True)
        self.config_dock.setEnabled(True)
        self.chat_input_edit.setEnabled(True)
        try:
            self.send_button.clicked.disconnect()
            logger.trace("Disconnected existing send_button click signal (likely stop).")
        except RuntimeError:
            logger.trace("No existing send_button click signal to disconnect.")
        except Exception as e:
             logger.warning(f"Unexpected error disconnecting send_button: {e}")

        self.send_button.setText("Send")
        self.send_button.setIcon(qta.icon('fa5s.paper-plane', color='white'))
        try:
            self.send_button.clicked.connect(self.chat_handler.handle_send_button_click)
            logger.trace("Connected handle_send_button_click to send_button.")
        except Exception as e:
            logger.error(f"Error connecting handle_send_button_click: {e}")
            self.send_button.setEnabled(False)
            self.send_button.setText("Error")
            return # Avoid further updates if connection failed

        if hasattr(self, 'chat_handler') and self.chat_handler:
            self.chat_handler._update_send_button_state()
        else:
            self.send_button.setEnabled(bool(self.chat_input_edit.toPlainText().strip()))

        self.chat_input_edit.setFocus()


    # --- Config Dock / Settings Related Slots ---
    @Slot()
    def _update_llm_params_from_dock(self):
         """Handles changes from ConfigDock's temp/topk spins"""
         temp = self.config_dock.temp_spin.value()
         topk = self.config_dock.topk_spin.value()
         self.settings_service.set_setting('temperature', temp)
         self.settings_service.set_setting('top_k', topk)
         logger.debug(f"Updated LLM params from dock: Temp={temp}, TopK={topk}")


    @Slot()
    def _populate_config_dock_from_settings(self):
         """Called when settings are loaded (e.g., project switch)"""
         logger.debug("Populating ConfigDock from SettingsService...")
         settings_dict = self.settings_service.get_all_settings()
         self.config_dock.populate_controls(settings_dict)
         # Trigger model refresh based on newly loaded settings
         self._refresh_config_dock_models()


    @Slot(str, object)
    def _handle_setting_change_for_dock(self, key: str, value: object):
         """Handles live updates if a setting changes (e.g., via SettingsDialog)"""
         logger.debug(f"Handling setting change '{key}' for ConfigDock update.")
         if key in ['provider', 'model', 'temperature', 'top_k'] or key.startswith('rag_'):
              logger.info(f"Setting '{key}' changed, repopulating entire ConfigDock.")
              self._populate_config_dock_from_settings()
         elif key == 'prompts':
             logger.debug("Prompt definitions changed, repopulating ConfigDock prompts.")
             all_prompts = self.settings_service.get_setting('prompts', [])
             selected_ids = self.settings_service.get_setting('selected_prompt_ids', [])
             self.config_dock.populate_available_prompts(all_prompts)
             self.config_dock.populate_selected_prompts(selected_ids, all_prompts)
         elif key == 'selected_prompt_ids':
             logger.debug("Selected prompt IDs changed, repopulating ConfigDock selected list.")
             all_prompts = self.settings_service.get_setting('prompts', [])
             selected_ids = self.settings_service.get_setting('selected_prompt_ids', [])
             self.config_dock.populate_selected_prompts(selected_ids, all_prompts)


    @Slot()
    def _refresh_config_dock_models(self):
        logger.debug("Refreshing ConfigDock model list triggered...")
        provider = self.settings_service.get_setting('provider', 'Ollama')
        api_key = self.settings_service.get_setting('api_key') if provider.lower() == 'gemini' else None
        self.config_dock.update_model_list(["⏳ loading..."], "")
        self.config_dock.model_combo.setEnabled(False)
        self.model_list_service.refresh_models('llm', provider, api_key)


    @Slot(list)
    def _update_config_dock_model_list(self, models: list):
        logger.debug(f"Updating ConfigDock model list with {len(models)} models.")
        current_model = self.settings_service.get_setting('model', '')
        self.config_dock.update_model_list(models, current_model)
        self.config_dock.model_combo.setEnabled(True)


    @Slot(str, str)
    def _handle_config_dock_model_error(self, provider_type: str, error_message: str):
         if provider_type == 'llm':
              logger.error(f"Error loading models for ConfigDock: {error_message}")
              self.config_dock.update_model_list([], "Error loading")
              self.config_dock.model_combo.setEnabled(False)


    # --- Helper Methods & Event Handlers ---
    def _get_checked_file_paths(self) -> List[Path]:
        checked_paths = []
        iterator = QTreeWidgetItemIterator(self.file_tree_widget)
        while iterator.value():
            item = iterator.value()
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                 try:
                      path = Path(path_str)
                      is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                      is_checked = item.checkState(0) == Qt.CheckState.Checked
                      if is_checkable and is_checked and (path.is_file() or path.is_dir()):
                           checked_paths.append(path)
                 except Exception as e:
                      logger.warning(f"Error processing tree item path '{path_str}': {e}")
            iterator += 1
        return checked_paths


    def _get_checked_tokens(self) -> int:
         total_tokens = 0
         iterator = QTreeWidgetItemIterator(self.file_tree_widget, QTreeWidgetItemIterator.IteratorFlag.All)
         while iterator.value():
              item = iterator.value()
              is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
              is_checked = item.checkState(0) == Qt.CheckState.Checked
              if is_checkable and is_checked:
                   path_str = item.data(0, Qt.ItemDataRole.UserRole)
                   if path_str:
                        try:
                            if Path(path_str).is_file():
                                token_count = item.data(0, TOKEN_COUNT_ROLE)
                                if isinstance(token_count, int) and token_count >= 0:
                                     total_tokens += token_count
                        except Exception as e:
                            logger.warning(f"Error checking path during token calc for '{path_str}': {e}")
              iterator += 1
         return total_tokens


    @Slot(QTreeWidgetItem, int)
    def _handle_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column == 0:
            logger.trace(f"Item changed: {item.text(0)}, state: {item.checkState(0)}")
            self._update_status_token_display()
            self._enforce_limit_timer.start()


    @Slot()
    def _check_and_enforce_token_limit(self):
        logger.debug("Checking and enforcing token limit...")
        max_tokens = self.llm_provider.get_context_limit()
        if max_tokens <= 0:
             logger.debug("Skipping token enforcement: Max tokens is zero or unset.")
             self._update_status_token_display()
             return

        cumulative_tokens = 0
        items_deselected = []
        deselection_needed = False

        self.file_tree_widget.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(self.file_tree_widget, QTreeWidgetItemIterator.IteratorFlag.All)
            while iterator.value():
                item = iterator.value()
                is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                is_checked = item.checkState(0) == Qt.CheckState.Checked

                if not is_checkable:
                     iterator += 1
                     continue

                item_tokens = 0
                path_str = item.data(0, Qt.ItemDataRole.UserRole)
                if path_str and Path(path_str).is_file():
                    token_data = item.data(0, TOKEN_COUNT_ROLE)
                    if isinstance(token_data, int) and token_data >= 0:
                        item_tokens = token_data

                if is_checked:
                    if cumulative_tokens + item_tokens > max_tokens:
                        item.setCheckState(0, Qt.CheckState.Unchecked)
                        items_deselected.append(item.text(0))
                        deselection_needed = True
                    else:
                        cumulative_tokens += item_tokens
                iterator += 1
        finally:
            self.file_tree_widget.blockSignals(False)

        self._update_status_token_display()

        if deselection_needed:
            warning_msg = (f"Token limit ({max_tokens:,}) exceeded. "
                           f"Automatically deselected {len(items_deselected)} item(s).")
            logger.warning(warning_msg)
            self._update_status_bar(warning_msg, 5000)

        logger.debug(f"Token limit enforcement finished. Final selected tokens: {cumulative_tokens}")


    @Slot()
    def _select_all_tree_items(self):
        logger.debug("Selecting all checkable tree items.")
        self.file_tree_widget.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(self.file_tree_widget, QTreeWidgetItemIterator.IteratorFlag.All)
            while iterator.value():
                item = iterator.value()
                if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    item.setCheckState(0, Qt.CheckState.Checked)
                iterator += 1
        finally:
            self.file_tree_widget.blockSignals(False)
            self._update_status_token_display()
            self._check_and_enforce_token_limit()


    @Slot()
    def _deselect_all_tree_items(self):
        logger.debug("Deselecting all checkable tree items.")
        self.file_tree_widget.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(self.file_tree_widget, QTreeWidgetItemIterator.IteratorFlag.All)
            while iterator.value():
                item = iterator.value()
                if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                iterator += 1
        finally:
            self.file_tree_widget.blockSignals(False)
            self._update_status_token_display()


    @Slot(QPoint)
    def _show_tree_context_menu(self, pos: QPoint):
        item = self.file_tree_widget.itemAt(pos)
        if not item:
             return
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
             return
        path = Path(path_str)
        menu = QMenu(self)
        if path.is_file():
            open_action = menu.addAction(qta.icon('fa5s.folder-open'), "Open")
            open_action.triggered.connect(lambda: self.workspace_handler.handle_tree_item_activated(item, 0))
        else:
             expand_action = menu.addAction("Expand/Collapse")
             expand_action.triggered.connect(lambda: item.setExpanded(not item.isExpanded()))
        menu.addSeparator()
        check_state = item.checkState(0)
        is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        if is_checkable:
            if check_state == Qt.CheckState.Checked:
                 uncheck_action = menu.addAction(qta.icon('fa5s.minus-square'), "Uncheck")
                 uncheck_action.triggered.connect(lambda: item.setCheckState(0, Qt.CheckState.Unchecked))
            else:
                 check_action = menu.addAction(qta.icon('fa5s.check-square'), "Check")
                 check_action.triggered.connect(lambda: item.setCheckState(0, Qt.CheckState.Checked))
            if path.is_dir():
                menu.addSeparator()
                check_children_action = menu.addAction("Check All Children")
                uncheck_children_action = menu.addAction("Uncheck All Children")
                check_children_action.triggered.connect(lambda: self._set_child_check_state_recursive(item, Qt.CheckState.Checked))
                uncheck_children_action.triggered.connect(lambda: self._set_child_check_state_recursive(item, Qt.CheckState.Unchecked))
        menu.exec(self.file_tree_widget.mapToGlobal(pos))


    def _set_child_check_state_recursive(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
         self.file_tree_widget.blockSignals(True)
         try:
             self.workspace_handler._set_child_check_state(parent_item, state)
         finally:
             self.file_tree_widget.blockSignals(False)
             self._update_status_token_display()
             self._check_and_enforce_token_limit()


    def _get_focused_editor(self) -> Optional[QPlainTextEdit]:
         widget = QApplication.focusWidget()
         if isinstance(widget, QPlainTextEdit) and widget in self.workspace_manager.open_editors.values():
              return widget
         current_tab_widget = self.editor_tab_widget.currentWidget()
         if isinstance(current_tab_widget, QPlainTextEdit):
              return current_tab_widget
         return None


    @Slot()
    def show_about_dialog(self):
        about_text = """
        <h2>PatchMind IDE</h2>
        <p>Version 0.2.8 (Global/Project Settings Split)</p>
        <p>An AI-enhanced code editor with inline LLM support, RAG context, and more.</p>
        <p>Developed by Kal Aeolian.</p>
        <p>Icons by <a href='https://fontawesome.com/'>Font Awesome</a> via Qtawesome.</p>
        <p>Using Qt via PySide6.</p>
        """
        QMessageBox.about(self, "About PatchMind IDE", about_text)


    @Slot()
    def show_log_directory(self):
         try:
              log_url = QUrl.fromLocalFile(str(LOG_PATH.resolve()))
              if not QDesktopServices.openUrl(log_url):
                   raise RuntimeError("QDesktopServices failed to open URL.")
              self._update_status_bar(f"Opened log directory: {LOG_PATH}", 3000)
         except Exception as e:
              logger.error(f"Failed to open log directory '{LOG_PATH}': {e}")
              self._show_error_message("Error", f"Could not open log directory:\n{LOG_PATH}\n\nError: {e}")


    # --- Application Exit Handling ---
    def closeEvent(self, event):
        logger.info("Close event triggered.")
        if not self.workspace_handler.close_all_tabs(confirm=True):
             logger.debug("Close event ignored due to user cancellation.")
             event.ignore()
             return

        logger.debug("Requesting Task Manager stop...")
        if hasattr(self, 'task_manager') and self.task_manager:
            self.task_manager.stop_generation()

        logger.debug("Saving window state and project settings...")
        self.settings_service.set_setting("main_window_geometry", self.saveGeometry())
        self.settings_service.set_setting("main_window_state", self.saveState())

        if not self.settings_service.save_settings():
            logger.error("Failed to save project settings on close.")
            # Optionally warn user?

        logger.info("Accepting close event.")
        event.accept()


# --- Entry Point ---
def launch_app():
    initial_theme = 'dark'
    QApplication.setApplicationName("PatchMind IDE")
    QApplication.setOrganizationName("PatchMind")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.exception("Unhandled exception caught:")
        error_details = f"{exc_type.__name__}: {exc_value}"
        QMessageBox.critical(None, "Critical Error", f"An unhandled exception occurred:\n{error_details}\n\nPlease check the logs for details.")

    sys.excepthook = handle_exception

    try:
         temp_settings = SettingsService()
         last_path_str = temp_settings.get_setting('last_project_path', str(Path.cwd()))
         last_path = Path(last_path_str)
         if not last_path.is_dir():
              last_path = Path.cwd()
         temp_settings.load_project(last_path)
         theme_from_settings = temp_settings.get_setting('theme', 'Dark')
         initial_theme = theme_from_settings.lower()
         import qdarktheme
         app.setStyleSheet(qdarktheme.load_stylesheet(initial_theme))
         logger.info(f"Applied initial theme: {initial_theme}")
    except Exception as e:
         logger.error(f"Failed to apply initial theme: {e}. Using default styling.")

    main_window = MainWindow()
    logger.info("Starting application event loop...")
    sys.exit(app.exec())