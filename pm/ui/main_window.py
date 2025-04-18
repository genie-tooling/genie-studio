# pm/ui/main_window.py
from PySide6.QtCore import Qt  # Ensure Qt is imported for flags/roles
# Ensure used types are imported
from PySide6.QtWidgets import QTreeWidget, QTabWidget, QTextEdit
import os
import sys
import re
import uuid
import datetime
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QPlainTextEdit, QTextEdit, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTabWidget,
    QFileDialog, QMessageBox, QLabel, QMenuBar, QPushButton, QDialog,
    QDockWidget, QCheckBox, QToolButton, QSizePolicy, QSpacerItem,
    QFontComboBox, QSpinBox, QComboBox, QToolBar, QDoubleSpinBox, QInputDialog,
    QStatusBar, QGroupBox, QFormLayout, QMenu, QHeaderView
)
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QFont, QIcon, QMovie, QDesktopServices
from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool, QThread, QSize, QTimer, QPoint, Slot, QUrl

from loguru import logger
import qdarktheme
import qtawesome as qta
import shutil

# --- Core Imports ---
from ..core.logging_setup import logger as log_setup
from ..core.token_utils import count_tokens
from ..core.gemini_service import GeminiService
from ..core.ollama_service import OllamaService
from ..core.project_config import load_project_config, save_project_config, DEFAULT_CONFIG
from ..core.model_registry import list_models, resolve_context_limit
from ..core.chat_manager import ChatManager
from ..core.workspace_manager import WorkspaceManager
from ..core.task_manager import BackgroundTaskManager

# --- UI Imports ---
from ..ui.highlighter import PygmentsHighlighter
from ..ui.settings_dialog import SettingsDialog
from ..ui.benchmark_dialog import BenchmarkDialog
from ..ui.diff_dialog import DiffDialog
from .chat_message_widget import ChatMessageWidget
from .config_dock import ConfigDock
from ..core.constants import TOKEN_COUNT_ROLE, TREE_TOKEN_SIZE_LIMIT

# Constants
RESERVE_FOR_IO = 1024

# Background Task for REFRESHING MODELS


class _ModelRefreshTask(QRunnable):
    def __init__(self, provider: str, api_key: Optional[str], callback_signal: Signal):
        super().__init__()
        self.provider = provider
        self.api_key = api_key; self.callback_signal = callback_signal

    def run(self):
        models = []
        logger.debug(f"ModelRefreshTask running for provider: {self.provider}")
        try:
            models = list_models(self.provider.lower(),
                                 api_key=self.api_key, force_no_cache=True)
        except Exception as e:
            logger.error(f"Error fetching models for {self.provider}: {e}")
        finally:
            logger.debug(
                f"ModelRefreshTask emitting models: {models}")
            self.callback_signal.emit(models)

# ───────────────────────── Main Window ─────────────────────────


class MainWindow(QMainWindow):
    _model_list_ready = Signal(list)

    def __init__(self):
        super().__init__()
        initial_project_path = Path(load_project_config(
            Path.cwd()).get('last_project_path', Path.cwd()))
        self.project_path = initial_project_path
        self.settings = load_project_config(self.project_path)
        self.chat_manager = ChatManager(parent=self)
        self.workspace_manager = WorkspaceManager(
            self.project_path, self.settings, parent=self)
        self.task_manager = BackgroundTaskManager(self.settings, parent=self)
        self.current_ai_message_id = None
        self.last_ai_response_raw_text = ""
        self.last_code_block_content = ""

        self.setWindowTitle('PatchMind IDE')
        self.resize(1600, 1000)
        self._apply_initial_theme()
        self._build_ui()
        self._build_docks()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._init_shortcuts()
        self._connect_signals()
        QTimer.singleShot(0, self._initial_workspace_setup)

    # pm/ui/main_window.py

# ... (other imports) ...


class MainWindow(QMainWindow):
    # ... (__init__ and other methods) ...

    def _connect_signals(self):
        """Connects all signals for the main window."""
        logger.critical("--- ENTERING _connect_signals ---")

        if hasattr(self, 'file_tree') and isinstance(self.file_tree, QTreeWidget):
            logger.info("Connecting file_tree signals...")
            self.file_tree.itemDoubleClicked.connect(
                self._handle_file_double_click)
            self.file_tree.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            self.file_tree.customContextMenuRequested.connect(
                self._show_file_tree_context_menu)

            # Keep itemChanged lambda test
            logger.debug("Connecting file_tree.itemChanged to lambda...")
            try:
                self.file_tree.itemChanged.connect(
                    lambda item, col: logger.critical(
                        f"**** itemChanged SIGNAL RECEIVED for item '{item.text(0)}', col {col} ****")
                )
                logger.info(
                    ">>> Connected file_tree.itemChanged to test LAMBDA.")
            except Exception as e:
                logger.error(
                    f"!!! EXCEPTION connecting file_tree.itemChanged: {e}")

            # *** ADD itemClicked Connection ***
            logger.debug("Connecting file_tree.itemClicked to test slot...")
            try:
                self.file_tree.itemClicked.connect(
                    self._debug_item_clicked)  # Connect to new debug slot
                logger.info(
                    ">>> Connected file_tree.itemClicked to _debug_item_clicked.")
            except Exception as e:
                logger.error(
                    f"!!! EXCEPTION connecting file_tree.itemClicked: {e}")
            # *** END ADDED Connection ***

        else:
            logger.error(
                "Connect Signals: file_tree widget not found or not a QTreeWidget.")

        # Tab Editor Signals
        if hasattr(self, 'tab_editor') and isinstance(self.tab_editor, QTabWidget):
            logger.debug("Connecting tab_editor signals...")
            self.tab_editor.tabCloseRequested.connect(self._close_tab_request)
        else:
            logger.error(
                "Connect Signals: tab_editor widget not found or not a QTabWidget.")

        # Chat Manager Signals
        logger.debug("Connecting chat_manager signals...")
        self.chat_manager.history_changed.connect(self._render_chat_history)
        self.chat_manager.message_content_updated.connect(
            self._handle_message_content_update)
        self.chat_manager.history_changed.connect(
            self._update_statusbar_context)  # Update context on any history change
        self.chat_manager.history_truncated.connect(
            self._update_statusbar_context)  # Update context when truncated

        # Workspace Manager Signals
        logger.debug("Connecting workspace_manager signals...")
        self.workspace_manager.project_changed.connect(
            self._on_project_changed)
        self.workspace_manager.editors_changed.connect(
            self._update_editor_related_ui)  # e.g., enable/disable save action
        self.workspace_manager.file_saved.connect(self._on_file_saved)
        self.workspace_manager.file_operation_error.connect(
            self._show_file_error)

        # Internal signal for background model list refresh
        logger.debug("Connecting _model_list_ready signal...")
        self._model_list_ready.connect(self._on_model_list_ready_for_dock)

        # Config Dock Signals (handled by specific method)
        # Note: _connect_config_dock_signals itself logs messages
        self._connect_config_dock_signals()

        # Chat Input Signals
        if hasattr(self, 'chat_input') and isinstance(self.chat_input, QTextEdit):
            logger.debug("Connecting chat_input signals...")
            self.chat_input.textChanged.connect(
                self._update_input_token_count)  # Update token count live
        else:
            logger.error(
                "Connect Signals: chat_input widget not found or not a QTextEdit.")

        # Task Manager Signals (Background Worker)
        logger.debug("Connecting task_manager signals...")
        self.task_manager.generation_started.connect(
            self._on_generation_started)
        self.task_manager.generation_finished.connect(
            self._on_generation_finished)
        self.task_manager.status_update.connect(self._update_status_label)
        self.task_manager.context_info.connect(
            self._handle_worker_context_info)
        self.task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self.task_manager.stream_error.connect(self._handle_stream_error)

        # *** STEP 1: Confirm method execution ***
        logger.critical("--- EXITING _connect_signals ---")
        logger.info("MainWindow signals connected.")  # Final confirmation

    @Slot(QTreeWidgetItem, int)
    def _debug_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Slot connected to itemClicked for debugging checkbox issues."""
        if not item:
            return

        item_text = item.text(0)
        current_flags = item.flags()
        is_checkable = bool(current_flags & Qt.ItemIsUserCheckable)
        current_state = item.checkState(0)

        logger.critical(f"--- _debug_item_clicked ---")
        logger.critical(f"  Item: '{item_text}', Column Clicked: {column}")
        logger.critical(
            f"  Item Flags: {current_flags} ({bin(current_flags)})")
        logger.critical(
            f"  Is Checkable (Qt.ItemIsUserCheckable flag present?): {is_checkable}")
        logger.critical(
            f"  Current Check State (Qt.CheckState enum): {current_state}")
        logger.critical(f"--------------------------")

    # --- UI Building Methods (mostly unchanged) ---
    def _apply_initial_theme(self):
        try:
            theme_name = self.settings.get('theme', 'Dark').lower()
            logger.info(f"Applying initial theme: {theme_name}"); style_sheet = qdarktheme.load_stylesheet(
                theme_name); app = QApplication.instance(); app.setStyleSheet(style_sheet) if app else logger.error("QApp instance missing")
        except Exception as e:
            logger.error(
                f"Failed apply initial theme '{self.settings.get('theme')}': {e}")

    def _build_docks(self):
        logger.debug("Building docks...")
        self.config_dock = ConfigDock(self.settings, self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.config_dock)

    def _connect_config_dock_signals(self):
        if not hasattr(self, 'config_dock'):
            logger.error("No dock to connect signals.")
            return
        logger.debug("Connecting ConfigDock signals...")
        d = self.config_dock
        d.provider_changed.connect(self._handle_provider_change_from_dock)
        d.model_changed.connect(self._handle_model_change_from_dock)
        d.llm_params_changed.connect(self._handle_llm_params_change_from_dock)
        d.request_model_list_refresh.connect(self._refresh_models_for_dock)
        d.rag_toggle_changed.connect(
            self._handle_rag_toggle_from_dock); d.selected_prompts_changed.connect(self._handle_selected_prompts_change_from_dock)  # Phase 5 signals commented


class MainWindow(QMainWindow):
    _model_list_ready = Signal(list)

    def __init__(self):
        super().__init__()
        # Load initial project path from config or default to current directory
        initial_project_path = Path(load_project_config(
            Path.cwd()).get('last_project_path', Path.cwd()))
        self.project_path = initial_project_path
        # Load settings for the identified project path
        self.settings = load_project_config(self.project_path)
        # Initialize managers, passing necessary references
        self.chat_manager = ChatManager(parent=self)
        self.workspace_manager = WorkspaceManager(
            self.project_path, self.settings, parent=self)
        self.task_manager = BackgroundTaskManager(self.settings, parent=self)
        # Initialize state variables
        self.current_ai_message_id = None
        self.last_ai_response_raw_text = ""
        self.last_code_block_content = ""
        # Start as true (no generation running)
        self._generation_complete = True
        self._last_finished_message_id = None  # Store ID of last finished message
        self._is_adjusting_checks = False
        self._is_cascading_checks = False  # Flag to prevent cascade loops
        self.setWindowTitle('PatchMind IDE')
        self.resize(1600, 1000)  # Initial size

        # Build UI components in order
        self._apply_initial_theme()  # Apply theme first
        self._build_ui()            # Build central widget and main layout
        self._build_docks()         # Build dock widgets (like config panel)
        self._build_menu()          # Build the main menu bar
        self._build_toolbar()       # Build the toolbar (theme, font)
        self._build_status_bar()    # Build the status bar
        self._init_shortcuts()      # Set up keyboard shortcuts
        self._connect_signals()     # Connect signals/slots AFTER UI elements exist

        # Schedule initial setup tasks after the event loop starts
        QTimer.singleShot(0, self._initial_workspace_setup)

    def _connect_signals(self):
        """Connects all signals for the main window."""
        # File Tree Signals
        if hasattr(self, 'file_tree'):
            self.file_tree.itemDoubleClicked.connect(
                self._handle_file_double_click)
            self.file_tree.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            self.file_tree.customContextMenuRequested.connect(
                self._show_file_tree_context_menu)
            # Connect itemChanged for checkbox state affecting context status bar
            # Potential connection for cascade_checks if needed: self.file_tree.itemChanged.connect(self._cascade_checks)
            self.file_tree.itemChanged.connect(self._update_statusbar_context)
            self.file_tree.itemChanged.connect(
                self._cascade_checks)  # Connect this signal
        else:
            logger.error("Connect Signals: file_tree widget not found.")

        # Tab Editor Signals
        if hasattr(self, 'tab_editor'):
            self.tab_editor.tabCloseRequested.connect(self._close_tab_request)
        else:
            logger.error("Connect Signals: tab_editor widget not found.")

        # Chat Manager Signals
        self.chat_manager.history_changed.connect(self._render_chat_history)
        self.chat_manager.message_content_updated.connect(
            self._handle_message_content_update)
        self.chat_manager.history_changed.connect(
            self._update_statusbar_context)  # Update context on any history change
        self.chat_manager.history_truncated.connect(
            self._update_statusbar_context)  # Update context when truncated

        # Workspace Manager Signals
        self.workspace_manager.project_changed.connect(
            self._on_project_changed)
        self.workspace_manager.editors_changed.connect(
            self._update_editor_related_ui)  # e.g., enable/disable save action
        self.workspace_manager.file_saved.connect(self._on_file_saved)
        self.workspace_manager.file_operation_error.connect(
            self._show_file_error)

        # Internal signal for background model list refresh
        self._model_list_ready.connect(self._on_model_list_ready_for_dock)

        # Config Dock Signals (handled by specific method)
        self._connect_config_dock_signals()

        # Chat Input Signals
        self.chat_input.textChanged.connect(
            self._update_input_token_count)  # Update token count live

        # Task Manager Signals (Background Worker)
        self.task_manager.generation_started.connect(
            self._on_generation_started)
        self.task_manager.generation_finished.connect(
            self._on_generation_finished)
        self.task_manager.status_update.connect(self._update_status_label)
        self.task_manager.context_info.connect(
            self._handle_worker_context_info)
        self.task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self.task_manager.stream_error.connect(self._handle_stream_error)

        logger.debug("MainWindow signals connected.")

    # --- UI Building Methods (mostly unchanged) ---

    def _set_check_state_recursive(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        """
        Recursively applies the check state to all checkable descendants of a parent item.
        Includes detailed logging for debugging.
        """
        parent_name = parent_item.text(
            0) if parent_item else "ROOT"  # Handle case if called on root somehow
        logger.debug(
            f"Recursive check set starting for parent '{parent_name}', Target State: {state}")

        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            if child:
                child_name = child.text(0)
                # Explicitly check flags - Use standard flags() method
                child_flags = child.flags()
                is_checkable = bool(child_flags & Qt.ItemIsUserCheckable)
                # Check if item is enabled
                is_enabled = bool(child_flags & Qt.ItemIsEnabled)

                current_state = child.checkState(0)
                logger.trace(
                    f"  Checking child '{child_name}': Flags={child_flags}, Checkable={is_checkable}, Enabled={is_enabled}, CurrentState={current_state}, TargetState={state}")

                # Only attempt to change checkable items whose state is different
                if is_checkable and current_state != state:
                    logger.debug(
                        f"    >>> Attempting to set state for '{child_name}' from {current_state} to {state}")
                    try:
                        # --- The core action ---
                        child.setCheckState(0, state)
                        # -----------------------

                        # Check immediately after setting if the state was accepted internally
                        new_state_check = child.checkState(0)
                        if new_state_check == state:
                            logger.debug(
                                f"        State successfully set internally for '{child_name}'.")
                        else:
                            # This would be very strange - indicates setCheckState itself failed
                            logger.error(
                                f"        !!! FAILED to internally set state for '{child_name}'. State reads {new_state_check} immediately after setting to {state}.")

                    except Exception as e:
                        # Catch potential errors during setCheckState itself
                        logger.exception(
                            f"        !!! EXCEPTION occurred calling setCheckState for '{child_name}': {e}")

                else:
                    # Log reasons for skipping
                    if not is_checkable:
                        logger.trace(
                            f"    Skipping '{child_name}' (Item Flag Qt.ItemIsUserCheckable is NOT set).")
                    elif current_state == state:
                        logger.trace(
                            f"    Skipping '{child_name}' (State is already {state}).")

                # Recurse into subdirectories, regardless of parent's checkable state (children might be checkable)
                if child.childCount() > 0:
                    # Optional: Check if it's really a directory based on path data if available
                    child_path = self._get_path_from_item(child)
                    if child_path and child_path.is_dir():
                        # logger.trace(f"  Recursing into subdirectory '{child_name}'...") # Keep commented unless needed - very verbose
                        self._set_check_state_recursive(child, state)
                    # else: logger.trace(f"  Not recursing into '{child_name}' (not a directory or no path).")

        logger.debug(
            f"Finished recursive check set for parent '{parent_name}'")

    def _apply_initial_theme(self):
        try:
            theme_name = self.settings.get('theme', 'Dark').lower()
            logger.info(f"Applying initial theme: {theme_name}")
            style_sheet = qdarktheme.load_stylesheet(theme_name)
            app = QApplication.instance()
            if app:
                app.setStyleSheet(style_sheet)
            else:
                logger.error(
                    "QApplication instance not found during initial theme application.")
        except Exception as e:
            logger.error(
                f"Failed to apply initial theme '{self.settings.get('theme')}': {e}")

    def _build_docks(self):
        logger.debug("Building docks...")
        # Create and add the ConfigDock
        # Pass settings reference and parent
        self.config_dock = ConfigDock(self.settings, self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.config_dock)
        # Add other docks here if needed in the future

    def _connect_config_dock_signals(self):
        if not hasattr(self, 'config_dock'):
            logger.error("ConfigDock not found, cannot connect its signals.")
            return

        logger.debug("Connecting ConfigDock signals...")
        dock = self.config_dock
        # Connect signals from the dock to slots in MainWindow
        dock.provider_changed.connect(self._handle_provider_change_from_dock)
        dock.model_changed.connect(self._handle_model_change_from_dock)
        dock.llm_params_changed.connect(
            self._handle_llm_params_change_from_dock)
        dock.request_model_list_refresh.connect(self._refresh_models_for_dock)
        dock.rag_toggle_changed.connect(self._handle_rag_toggle_from_dock)
        dock.selected_prompts_changed.connect(
            self._handle_selected_prompts_change_from_dock)

    def _build_menu(self):
        logger.debug("Building menu...")
        mb = self.menuBar()
        fm = mb.addMenu('&File')

        # Create and assign the save action *before* using it in the list
        self.save_file_action = QAction(
            qta.icon('fa5s.save'), 'Save', self,
            shortcut=QKeySequence.Save,
            triggered=self._save_current_tab,
            enabled=False  # Start disabled
        )

        # Now add actions using the created variable
        file_actions = [
            QAction(qta.icon('fa5s.folder-open'), 'Open Project…', self,
                    shortcut=QKeySequence.Open, triggered=self._open_project),
            QAction(qta.icon('fa5s.file'), 'New', self,
                    shortcut=QKeySequence.New, triggered=self._new_file),
            self.save_file_action  # Use the pre-assigned variable
        ]
        for action in file_actions:
            fm.addAction(action)

        fm.addSeparator()
        settings_actions = [
            QAction(qta.icon('fa5s.cogs'), 'Save Settings',
                    self, triggered=self._save_project_settings),
            QAction(qta.icon('fa5s.cog'), 'Settings…',
                    self, triggered=self._open_settings)
        ]
        for action in settings_actions:
            fm.addAction(action)

        fm.addSeparator()
        fm.addAction(QAction(qta.icon('fa5s.times-circle'), 'Quit',
                     self, shortcut=QKeySequence.Quit, triggered=self.close))

        mb.addMenu('&Edit')  # Placeholder for Edit menu actions if any

        vm = mb.addMenu('&View')
        # *** FIX: Get the action first, then modify it ***
        if hasattr(self, 'config_dock'):
            # Get the default toggle action from the dock widget
            toggle_config_panel_action = self.config_dock.toggleViewAction()
            # Customize the action's text and icon
            toggle_config_panel_action.setText("Toggle Config Panel")
            toggle_config_panel_action.setIcon(qta.icon('fa5s.cogs'))
            # Add the customized action to the menu
            vm.addAction(toggle_config_panel_action)
        else:
            logger.error("No config_dock found for View menu toggle action.")
        # *** End Fix ***

        tm = mb.addMenu('&Tools')
        tm.addAction(QAction(qta.icon('fa5s.rocket'), 'Benchmark…',
                     self, triggered=self._run_benchmark))

        hm = mb.addMenu('&Help')

    def _build_toolbar(self):
        logger.debug("Building toolbar...")
        bar = QToolBar("Appearance")
        bar.setIconSize(QSize(16, 16)); self.addToolBar(Qt.TopToolBarArea, bar); bar.addWidget(QLabel(" Theme:")); self.theme_combo = QComboBox(); self.theme_combo.addItems(["Dark", "Light"]); self.theme_combo.setCurrentText(self.settings.get("theme", "Dark")); self.theme_combo.currentTextChanged.connect(self._apply_theme); bar.addWidget(self.theme_combo); bar.addSeparator(); bar.addWidget(QLabel(" Font:")); self.font_combo = QFontComboBox(); (lambda f=self.settings.get(
            "editor_font", "Fira Code"): self.font_combo.setCurrentFont(QFont(f)) or logger.info(f"Set font {f}"))(); self.font_combo.currentFontChanged.connect(self._apply_editor_font); bar.addWidget(self.font_combo); bar.addWidget(QLabel(" Size:")); self.font_size = QSpinBox(); self.font_size.setRange(8, 32); self.font_size.setValue(int(self.settings.get("editor_font_size", 11))); self.font_size.valueChanged.connect(self._apply_editor_font); bar.addWidget(self.font_size)

    def _build_status_bar(self): logger.debug("Building status bar..."); sb = self.statusBar(); sb.setStyleSheet("QStatusBar::item{border:0px}"); self._input_token_lbl = QLabel('Input: 0 tokens'); sb.addPermanentWidget(
        self._input_token_lbl); self.context_token_label = QLabel("Context: 0/0"); self.context_token_label.setAlignment(Qt.AlignRight); sb.addPermanentWidget(self.context_token_label); sb.showMessage("Ready", 3000)

    def _build_ui(self):
        logger.debug("Building main UI...")
        sp = QSplitter(Qt.Horizontal)
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(4)
        self.main_splitter = sp  # Assign to self

        # --- Chat Panel (Left Side) ---
        chat_panel_widget = QWidget()
        cl = QVBoxLayout(chat_panel_widget)
        cl.setContentsMargins(5, 5, 5, 5)
        cl.setSpacing(5)

        self.chat_list_widget = QListWidget()
        self.chat_list_widget.setAlternatingRowColors(True)
        self.chat_list_widget.setStyleSheet("QListWidget{border:none}")
        self.chat_list_widget.setSelectionMode(QListWidget.NoSelection)
        self.chat_list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        cl.addWidget(self.chat_list_widget, 1)  # Stretch chat list

        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Enter prompt... (Ctrl+Enter)")
        self.chat_input.setAcceptRichText(False)
        self.chat_input.setFixedHeight(80)
        cl.addWidget(self.chat_input)

        # Input Controls Layout (Bottom)
        icl = QHBoxLayout()
        icl.setContentsMargins(0, 0, 0, 0)
        icl.setSpacing(5)

        # Loading Indicator Setup (Corrected Logic)
        self.loading_indicator_label = QLabel()
        self.loading_movie = None  # Initialize attribute
        loading_gif_path = Path(__file__).parent.parent / \
        'assets' / 'loading.gif'

        if loading_gif_path.exists():
            logger.debug(f"Loading animation from: {loading_gif_path}")
            # Create and assign the movie *before* configuring label
            self.loading_movie = QMovie(str(loading_gif_path))
            self.loading_indicator_label.setMovie(self.loading_movie)
            self.loading_indicator_label.setFixedSize(24, 24)
            self.loading_movie.setScaledSize(QSize(24, 24))
        else:
            logger.warning(
                f"Loading animation GIF missing: {loading_gif_path}")
            self.loading_indicator_label.setText("...")  # Placeholder text
            self.loading_indicator_label.setFixedSize(24, 24)  # Still set size

        self.loading_indicator_label.hide()  # Hide initially
        icl.addWidget(self.loading_indicator_label)

        # Status Label (for worker status)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-style:italic;color:gray")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        icl.addWidget(self.status_label, 1)  # Allow stretch

        icl.addStretch(1)  # Push buttons to the right

        # Buttons
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(qta.icon('fa5s.stop-circle'))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._handle_stop_button)
        icl.addWidget(self.stop_btn)

        self.copy_code_btn = QPushButton("Copy Code")
        self.copy_code_btn.setIcon(qta.icon('fa5s.copy'))
        self.copy_code_btn.setEnabled(False)
        self.copy_code_btn.clicked.connect(self._copy_last_code_block)
        icl.addWidget(self.copy_code_btn)

        self.send_btn = QPushButton(" Send")
        self.send_btn.setIcon(qta.icon('fa5s.paper-plane'))
        self.send_btn.clicked.connect(self._send_prompt)
        # Initial state handled by _update_active_services_and_context
        icl.addWidget(self.send_btn)

        cl.addLayout(icl)  # Add button layout to chat panel
        sp.addWidget(chat_panel_widget)  # Add chat panel to splitter

        # --- File Tree (Middle) ---
        self.file_tree=QTreeWidget()
        self.file_tree.setHeaderLabels(['Project', 'Tokens']) # Set header labels first
        self.file_tree.setAlternatingRowColors(True)

        # --- Configure Header Behavior ---
        header = self.file_tree.header()
        # Column 0 (Project): Stretch to fill available space initially. User can still resize.
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # Optional: Set a reasonable minimum size for the Project column
        # header.setMinimumSectionSize(150)
        # --- End Header Configuration ---

        sp.addWidget(self.file_tree) # Add tree to splitter
        # --- Tab Editor (Right) ---
        self.tab_editor = QTabWidget()
        self.tab_editor.setTabsClosable(True)
        self.tab_editor.setMovable(True)
        self.tab_editor.setUsesScrollButtons(True)
        sp.addWidget(self.tab_editor)

        self.setCentralWidget(sp)
        logger.info("Main UI built.")
    # --- End CORRECTED _build_ui ---

    def _initial_workspace_setup(self):
        logger.debug("Initial workspace setup...")
        if not hasattr(self,'config_dock'): logger.error("Cannot run initial setup: config_dock missing."); return

        # --- Populate Config Dock First ---
        try:
            self.settings.setdefault('prompts', []); self.settings.setdefault('selected_prompt_ids', [])
            self.config_dock.populate_controls(self.settings);
            # Handle potential missing keys during prompt population
            prompts_data = self.settings.get('prompts', [])
            selected_ids = self.settings.get('selected_prompt_ids', [])
            self.config_dock.populate_available_prompts(prompts_data)
            self.config_dock.populate_selected_prompts(selected_ids, prompts_data)
        except Exception as e:
             logger.exception("Error populating ConfigDock during initial setup.")
        # --- End Config Dock Population ---

        self._update_active_services_and_context();
        self._refresh_models_for_dock(self.settings.get('provider','Ollama'));

        # Populate the tree *synchronously*
        try:
            self.workspace_manager.populate_file_tree(self.file_tree);
        except Exception as e:
            logger.exception("Error populating file tree during initial setup.")

        # --- Use QTimer to set sizes AFTER population and initial events ---
        # A delay of 0 runs it in the next event loop cycle, 10ms gives a tiny bit more settling time.
        QTimer.singleShot(10, self._finalize_ui_layout)
        # --- End QTimer ---

        self._update_input_token_count()


    def _set_initial_splitter_sizes(self):
        """Sets reasonable initial proportions for the main horizontal splitter."""
        if hasattr(self, 'main_splitter'):
            # Get the splitter's width directly
            splitter_width = self.main_splitter.width()
            if splitter_width > 100:
                # Only resize if the splitter is reasonably wide
                # Calculate desired sizes: chat ~30%, tree ~20%, editor takes the rest
                chat_w = int(splitter_width * 0.3)
                tree_w = int(splitter_width * 0.2)
                # Calculate the remaining width for the editor explicitly
                editor_w = splitter_width - chat_w - tree_w

                # Ensure the editor width isn't negative (unlikely, but safe)
                if editor_w >= 0:
                    self.main_splitter.setSizes([chat_w, tree_w, editor_w])
                    logger.debug(
                        f"Splitter sizes set to [{chat_w}, {tree_w}, {editor_w}] based on width {splitter_width}")
                else:
                    logger.warning(
                        f"Splitter width calculation resulted in negative remainder: {editor_w}. Using default sizes.")

            else:
                # Log if splitter is too small to resize meaningfully
                logger.debug(
                    f"Splitter too small ({splitter_width}px) for initial proportional sizing.")
        else:
            logger.warning(
                "main_splitter widget not found during initial size setting.")

# ... (rest of the MainWindow class) ...

    # ----- Config Dock Signal Handlers -----
    @Slot(str)
    def _handle_provider_change_from_dock(self, provider: str):
        logger.info(f"MainWindow: Provider selection changed to: {provider}")
        if self.settings.get('provider') != provider:
            self.settings['provider'] = provider
            self.settings['model'] = ''  # Clear model when provider changes
            # Clear services in task manager
            self.task_manager.set_services(None, None)
            # *** Disable Send button until a valid model is selected ***
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip("Select a model first")
            logger.debug("Cleared services/model, disabled Send button.")
            # Model list refresh is handled separately

    @Slot(str)
    def _handle_model_change_from_dock(self, model: str):
        logger.info(f"MainWindow: Handling model change from dock: {model}")
        if self.settings.get('model') != model:
            self.settings['model'] = model
            # Update services AFTER model is set
            self._update_active_services_and_context()
        else:
            logger.debug(f"Model '{model}' already selected.")

    @Slot()
    def _handle_llm_params_change_from_dock(self): logger.info("LLM param change"); self.config_dock.update_settings_from_ui(
        self.settings); self._update_active_services_and_context()

    @Slot(str, bool)
    def _handle_rag_toggle_from_dock(self, key: str, checked: bool): logger.info(
        f"RAG toggle: {key}={checked}"); self.settings[key] = checked; self._update_statusbar_context()

    @Slot(list)
    def _handle_selected_prompts_change_from_dock(self, ids: list): logger.info(
        f"Selected prompts: {ids}"); self.settings['selected_prompt_ids'] = ids; self._update_statusbar_context()

    # ----- Actions Triggered by Config Dock -----
    @Slot(str)
    def _refresh_models_for_dock(self, provider: str): logger.info(f"Refresh models for: {provider}"); api_key = self.settings.get(
        'api_key') if provider.lower() == 'gemini' else None; QThreadPool.globalInstance().start(_ModelRefreshTask(provider, api_key, self._model_list_ready))

    @Slot(list)
    def _on_model_list_ready_for_dock(self, models: list):
        """
        Slot called when the background task finishes fetching the model list.
        Updates the model list combobox in the ConfigDock.
        """
        logger.info(
            f"Model list ready signal received ({len(models)} models).")
        # Use standard if/else for clarity and correctness
        if hasattr(self, 'config_dock'):
            current_model_selection = self.settings.get('model', '')
            logger.debug(
                f"Updating config dock model list. Current selection: '{current_model_selection}'")
            self.config_dock.update_model_list(models, current_model_selection)
        else:
            # This error should only happen if the dock wasn't created correctly
            logger.error(
                "Cannot update model list: ConfigDock ('self.config_dock') not found.")

    def _update_active_services_and_context(self):
        """Initializes services, passes them to TaskMgr, updates context display, enables/disables Send button."""
        logger.info("Updating services & context...")
        model_svc, summ_svc, limit = self._init_services()  # Returns initialized services
        self.settings['context_limit'] = limit  # Update settings
        self.task_manager.set_services(
            model_svc, summ_svc)  # Update Task Manager
        # Update UI
        hasattr(self, 'config_dock') and self.config_dock.update_context_limit_display(
            limit)
        self._update_statusbar_context()
        # *** Enable/Disable Send Button based on service availability ***
        service_ok = model_svc is not None
        self.send_btn.setEnabled(service_ok)
        self.send_btn.setToolTip(
            "Send prompt (Ctrl+Enter)" if service_ok else "LLM Service not available (check provider/model/key)")
        logger.info(
            f"Service update complete. Model Service available: {service_ok}")

    # pm/ui/main_window.py

# ... (inside the MainWindow class) ...

    def _init_services(self) -> tuple[Optional[Any], Optional[Any], int]:
        model_svc = None  # Start as None
        summ_svc = None
        limit = DEFAULT_CONFIG['context_limit']
        provider = self.settings.get('provider', 'Ollama')
        model = self.settings.get('model', '')
        api_key = self.settings.get('api_key', '')
        temp = float(self.settings.get('temperature', 0.3))
        top_k = int(self.settings.get('top_k', 40))

        logger.info(f"Initializing provider: {provider}, Model: {model}")
        try:
            # --- Validation ---
            if provider == 'Ollama' and model.startswith('models/'):
                raise ValueError(
                    f"Ollama provider specified but model name '{model}' looks like a Gemini model ID.")
            if provider == 'Gemini' and ':' in model and not model.startswith('models/'):
                raise ValueError(
                    f"Gemini provider specified but model name '{model}' looks like an Ollama model tag.")

            # --- Service Creation ---
            if provider == 'Gemini':
                if not api_key:
                    raise ValueError(
                        "Gemini provider selected, but API key is missing in settings.")
                # Assign Gemini instance
                model_svc = GeminiService(model, api_key, temp, top_k)
                logger.debug(f"GeminiService instance created: {model_svc}")
            elif provider == 'Ollama':
                if not model:
                    raise ValueError(
                        "Ollama provider selected, but no model name is specified in settings.")
                model_svc = OllamaService(model)  # Assign Ollama instance
                logger.debug(f"OllamaService instance created: {model_svc}")
            else:
                raise ValueError(f"Unsupported provider selected: {provider}")

            # --- Resolve Context Limit (after service creation) ---
            limit = resolve_context_limit(provider, model)
            logger.info(f"Resolved context limit: {limit}")

        except Exception as e:
            # Log full traceback
            logger.exception(f"Failed init provider {provider}/{model}: {e}")
            QMessageBox.warning(
                self, "Provider Error", f"Failed to initialize {provider} model '{model}':\n{e}")
            model_svc = None  # Explicitly set to None on error
            # Reset limit to default on error
            limit = DEFAULT_CONFIG['context_limit']
            self.statusBar().showMessage(
                f"Error initializing {provider}!", 5000)

        # --- Summarizer Service Initialization (Independent) ---
        # Use temporary vars to avoid confusion with main service vars
        summarizer_model = None
        # Might need a separate limit? Defaulting for now.
        summarizer_limit = 0
        if self.settings.get('rag_summarizer_enabled', False):
            summ_model_name = self.settings.get(
                'rag_summarizer_model_name', '')
            if summ_model_name:
                summ_provider = self.settings.get(
                    'rag_summarizer_provider', 'Ollama')
                logger.info(
                    f"Init Summarizer Provider: {summ_provider}, Model: {summ_model_name}")
                try:
                    if summ_provider == 'Ollama':
                        summ_svc = OllamaService(summ_model_name)
                    elif summ_provider == 'Gemini':
                        summ_api_key = self.settings.get(
                            'api_key', '')  # Use main API key for now
                        if summ_api_key:
                            # Use lower temp/topk for summarization?
                            summ_svc = GeminiService(
                                summ_model_name, summ_api_key, 0.2, 1)
                        else:
                            logger.warning(
                                "Cannot initialize Gemini summarizer: API key missing.")
                    else:
                        logger.error(
                            f"Unsupported summarizer provider: {summ_provider}")
                    # Optionally resolve summarizer limit if needed later
                    # summarizer_limit = resolve_context_limit(summ_provider, summ_model_name)
                except Exception as e:
                    logger.error(
                        f"Failed to initialize summarizer {summ_provider}/{summ_model_name}: {e}")
                    summ_svc = None  # Ensure it's None on error
            else:
                logger.debug("Summarizer enabled but no model name set.")
        else:
            logger.debug("Query summarization is disabled.")

        # *** ADDED DEBUG LOG ***
        logger.debug(
            f"RETURNING from _init_services. model_svc is None: {model_svc is None}, type: {type(model_svc)}")
        # *** END ADDED DEBUG LOG ***

        return model_svc, summ_svc, limit  # Return potentially None model_svc

    # ----- Prompt Management Actions -----
    # Phase 5 Slots remain commented out

    # ----- File Tree / Workspace Slots -----
    # (Implementations remain mostly the same)
    @Slot(Path)
    def _on_project_changed(self, new_path: Path): logger.info(f"Project changed: {new_path}"); self.project_path = new_path; self.settings = load_project_config(new_path); self.workspace_manager.settings = self.settings; self._apply_initial_theme(); self.theme_combo.setCurrentText(self.settings.get("theme", "Dark")); (lambda f=self.settings.get("editor_font", "Fira Code"): self.font_combo.setCurrentFont(QFont(f)))(); self.font_size.setValue(int(self.settings.get("editor_font_size", 11))); hasattr(self, 'config_dock') and (self.config_dock.populate_controls(self.settings), self.config_dock.populate_available_prompts(
        self.settings.get('prompts', [])), self.config_dock.populate_selected_prompts(self.settings.get('selected_prompt_ids', []), self.settings.get('prompts', [])), self._update_active_services_and_context(), self._refresh_models_for_dock(self.settings.get('provider', 'Ollama'))); self.workspace_manager.populate_file_tree(self.file_tree); self.chat_manager.clear_history(); [self.workspace_manager.close_tab(0, self.tab_editor) for _ in range(self.tab_editor.count())]; self.statusBar().showMessage(f'Opened: {new_path.name}', 5000); self._update_statusbar_context()

    @Slot(Path)
    def _on_file_saved(self, path: Path): self.statusBar(
    ).showMessage(f'Saved {path.name}', 3000)

    @Slot(str)
    def _show_file_error(self, msg: str): QMessageBox.warning(
        self, "File Error", msg); self.statusBar().showMessage("File Error", 3000)

    @Slot()
    def _update_editor_related_ui(self): self.save_file_action.setEnabled(
        self.tab_editor.count() > 0)

    def _handle_file_double_click(self, item: QTreeWidgetItem, col: int): path = self._get_path_from_item(item); (path and path.is_file(
    ) and self.workspace_manager.load_file(path, self.tab_editor)) or (path and path.is_dir() and item.setExpanded(not item.isExpanded()))

    @Slot(QTreeWidgetItem, int)  # Ensure Slot decorator is present
    def _cascade_checks(self, item: QTreeWidgetItem, col: int):
        """
        Recursively cascades check state changes down the tree for checkable items.
        Blocks signals during the cascade to prevent infinite loops/performance issues.
        """
        # 1. Only proceed if the change was in the checkbox column (0)
        #    and the item itself is checkable.
        if col == 0 and item.flags() & Qt.ItemIsUserCheckable:

            # 2. Get the new state of the item that triggered the signal
            new_state = item.checkState(0)
            logger.trace(
                f"Cascading check state '{new_state}' from item: '{item.text(0)}'")

            # 3. Block signals on the tree widget to prevent recursive triggers
            #    from the changes we are about to make.
            self.file_tree.blockSignals(True)

            try:
                # 4. Use an iterative approach (Queue/BFS) to avoid deep recursion issues
                queue = [item.child(i) for i in range(item.childCount())]
                while queue:
                    child = queue.pop(0)

                    # 5. Only modify checkable children
                    if child.flags() & Qt.ItemIsUserCheckable:
                        # Optimization: Only set state if it's actually different
                        if child.checkState(0) != new_state:
                            child.setCheckState(0, new_state)
                            # logger.trace(f"  Set '{child.text(0)}' to {new_state}") # Uncomment for detailed logs

                        # Add this child's children to the queue to process grandchildren etc.
                        queue.extend(child.child(i)
                                     for i in range(child.childCount()))

            except Exception as e:
                # Log any unexpected errors during the cascade
                logger.exception(
                    f"Error during check state cascade for item '{item.text(0)}': {e}")
            finally:
                # 6. CRITICAL: Always unblock signals, even if an error occurred.
                self.file_tree.blockSignals(False)
                logger.trace(f"Finished cascading checks for '{item.text(0)}'")

            # 7. Update the status bar context *once* after all changes are complete.
            self._update_statusbar_context()

    def _close_tab_request(self, index: int): self.workspace_manager.close_tab(
        index, self.tab_editor)

    def _save_current_tab(self): editor = self.tab_editor.currentWidget(); (isinstance(editor, QPlainTextEdit)
                          and self.workspace_manager.save_tab_content(editor)) or self.statusBar().showMessage("No active editor", 2000)

    # ----- Theme/Font Application -----
    # (Implementations remain the same)
    def _apply_theme(self, name=None, save=True): name = name or self.theme_combo.currentText(); logger.info(f"Applying theme: {name}"); app = QApplication.instance(); app and (style := qdarktheme.load_stylesheet(name.lower(
    )), app.setStyleSheet(style), (self.settings.get('theme') != name and (self.settings.__setitem__('theme', name), save and self._save_project_settings())), self._apply_editor_font(save=False)) or logger.error("No QApp")

    def _apply_editor_font(self, save=True): ff, fs = self.font_combo.currentFont().family(), self.font_size.value(); logger.info(f"Font: {ff} {fs}pt"); fc = self.settings.get('editor_font') != ff or self.settings.get('editor_font_size') != fs; self.settings['editor_font'], self.settings['editor_font_size'] = ff, fs; nf = QFont(
        ff, fs); [(e and isinstance(e, QPlainTextEdit) and (e.setFont(nf), e.style().unpolish(e), e.style().polish(e), e.update())) for p, e in self.workspace_manager.open_editors.items()]; (save and fc) and self._save_project_settings()

    # ----- Diff Dialog -----
    def _show_diff_dialog(self, content): logger.debug(
        "Show diff"); DiffDialog(content, self).show()

    # ----- Chat History Rendering -----
    # (Implementations remain the same)
    @Slot()
    def _render_chat_history(self):
        """Renders the chat history in the QListWidget."""
        history_snapshot = self.chat_manager.get_history_snapshot()
        logger.debug(
            f"Rendering chat history ({len(history_snapshot)} messages).")

        # Block signals during bulk update to avoid unnecessary processing
        self.chat_list_widget.blockSignals(True)
        self.chat_list_widget.clear()  # Clear previous items

        # Use a standard loop for clarity
        for message_data in history_snapshot:
            try:
                # Create the custom widget for the message
                widget = ChatMessageWidget(message_data)
                # Create the list item to hold the widget
                list_item = QListWidgetItem()

                # Connect signals from the widget to MainWindow slots
                widget.deleteRequested.connect(
                    self._handle_delete_request)  # Connect to the NEW method
                widget.editRequested.connect(self._handle_edit_request)
                widget.editSubmitted.connect(self._handle_edit_submit)

                # Set the size hint for the list item based on the widget's preferred size
                # This is important for proper layout and scrolling
                list_item.setSizeHint(widget.sizeHint())

                # Add the item to the list widget
                self.chat_list_widget.addItem(list_item)
                # Set the custom widget for the added list item
                self.chat_list_widget.setItemWidget(list_item, widget)

            except Exception as e:
                # Log error if creating/adding a specific widget fails
                logger.exception(
                    f"Error rendering message widget for ID {message_data.get('id', 'N/A')}: {e}")

        # Re-enable signals after update
        self.chat_list_widget.blockSignals(False)

        # Scroll to the bottom after rendering is complete (deferred slightly)
        QTimer.singleShot(0, self.chat_list_widget.scrollToBottom)

    @Slot(str, str)
    def _handle_message_content_update(self, message_id: str, full_content: str):
        """
        Slot connected to ChatManager.message_content_updated.
        Finds the specific ChatMessageWidget and updates its content dynamically.
        Adjusts the item's size hint and scrolls if necessary.
        """
        widget = self._find_widget_by_id(message_id)
        if widget:
            # logger.debug(f"Updating content display for widget ID {message_id} (len: {len(full_content)})")
            new_size_hint = widget.update_content(full_content)
            list_item_updated = False
            for i in range(self.chat_list_widget.count()):
                item = self.chat_list_widget.item(i)
                if self.chat_list_widget.itemWidget(item) == widget:
                    item.setSizeHint(new_size_hint)
                    list_item_updated = True
                    break
            if not list_item_updated:
                logger.warning(
                    f"Could not find QListWidgetItem for widget ID {message_id} to update size hint.")

            # --- Auto-Scroll Logic ---
            scrollbar = self.chat_list_widget.verticalScrollBar()
            is_near_bottom = scrollbar and (scrollbar.value() >= scrollbar.maximum(
            ) - 30 or scrollbar.value() == scrollbar.maximum())
            if is_near_bottom:  # Keep scrolling if user was already at the bottom
                QTimer.singleShot(0, self.chat_list_widget.scrollToBottom)

        else:
            logger.warning(
                f"Content update signal received for message ID {message_id}, but widget not found.")

    # ----- Chat Actions / Background Task Handling -----
# pm/ui/main_window.py

# ... (inside the MainWindow class) ...

    def _send_prompt(self):
        txt = self.chat_input.toPlainText().strip()
        if not txt:
            logger.warning("Send rejected: Input is empty.")
            # Optionally show a small notification instead of message box for empty input
            self.statusBar().showMessage("Cannot send empty prompt.", 2000)
            return
        if self.task_manager.is_busy():
            logger.warning(f"Send rejected: Task manager is busy.")
            QMessageBox.warning(
                self, "Busy", "AI is currently processing a request. Please wait.")
            return

        # 1. Add the user message to the history
        user_msg_id = self.chat_manager.add_user_message(txt)
        if not user_msg_id:
            logger.error("Failed to add user message to history.")
            return  # Should not happen if txt is not empty, but safety check

        # *** 2. Get the history snapshot *NOW*, before adding the AI placeholder ***
        history_for_worker = self.chat_manager.get_history_snapshot()
        # The last message in history_for_worker is guaranteed to be the user's message

        # 3. Add the AI placeholder to the history for UI rendering
        ai_placeholder_id = self.chat_manager.add_ai_placeholder()
        if not ai_placeholder_id:
            logger.error("Failed to add AI placeholder message.")
            # Attempt to roll back the user message? Or just proceed with error?
            # For now, log the error and potentially stop.
            return

        # --- Prepare for generation ---
        self.current_ai_message_id = ai_placeholder_id  # Store ID for streaming updates
        self.chat_input.clear()  # Clear the input field
        logger.debug("Asking Task Manager start generation...")

        # *** 4. Start generation using the snapshot taken BEFORE the placeholder ***
        self.task_manager.start_generation(
            history_for_worker,  # Pass the correct history snapshot
            self._calculate_checked_file_paths_for_worker(),
            self.workspace_manager.project_path
        )
        # UI updates for starting generation are handled by the generation_started signal
    def _finalize_ui_layout(self):
        """Sets column widths and splitter sizes after initial population."""
        logger.debug("Finalizing UI layout (column/splitter sizes)...")

        # Set Tree Column Widths
        if hasattr(self, 'file_tree') and self.file_tree.columnCount() > 1:
            header = self.file_tree.header() # Get header reference
            try:
                # 1. Set the fixed width for the Tokens column
                initial_token_column_width = 80
                self.file_tree.setColumnWidth(1, initial_token_column_width)
                logger.debug(f"Set fixed width for column 1 to {initial_token_column_width}px.")

                # 2. Tell the header *not* to automatically stretch the last section
                header.setStretchLastSection(False)
                logger.debug("Set header.stretchLastSection(False).")

                # 3. Now, set the Project column to stretch
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                logger.info(f"Set column 0 resize mode to Stretch.")

                # Log widths immediately after setting modes
                logger.debug(f"  Immediate widths - Col 0: {self.file_tree.columnWidth(0)}, Col 1: {self.file_tree.columnWidth(1)}")
                # Log again after a tiny delay to see if splitter resize changes them
                QTimer.singleShot(10, lambda: logger.debug(f"  Post-layout widths (after timer) - Col 0: {self.file_tree.columnWidth(0)}, Col 1: {self.file_tree.columnWidth(1)}"))

            except Exception as e:
                 logger.error(f"Error setting column widths: {e}")
        else:
             logger.warning("Cannot set column widths: file_tree not ready or has < 2 columns.")

        # Set Splitter Sizes (keep this logic)
        if hasattr(self,'main_splitter'):
             width = self.main_splitter.width()
             if width > 100:
                  chat_prop = 0.35
                  tree_prop = 0.20
                  edit_prop = 1.0 - chat_prop - tree_prop
                  sizes = [int(width * chat_prop), int(width * tree_prop), int(width * edit_prop)]
                  self.main_splitter.setSizes(sizes)
                  logger.info(f"Set main_splitter sizes based on width {width}: {sizes}.")
                  QTimer.singleShot(10, lambda: logger.debug(f"  Post-layout splitter sizes (after timer): {self.main_splitter.sizes()}"))
             else:
                  logger.warning(f"Splitter too small ({width}) to resize confidently.")
        else:
             logger.warning("main_splitter not found for resizing.")

    def _calculate_checked_file_paths_for_worker(self) -> List[Path]:
        """
        Traverses the file tree and collects the Paths of all items
        that are checked and represent actual files.
        Uses a breadth-first search approach.
        """
        paths: List[Path] = []
        try:
            # Start traversal from the invisible root item's children (top-level items)
            # Initialize a queue (list used as a queue) with top-level items
            queue = [
                self.file_tree.invisibleRootItem().child(i)
                for i in range(self.file_tree.invisibleRootItem().childCount())
            ]

            # Process items until the queue is empty
            while queue:
                # Get the next item from the front of the queue
                item = queue.pop(0)

                # Check if the item is checked
                if item.checkState(0) == Qt.Checked:
                    # Get the path associated with the item
                    p = self._get_path_from_item(item)
                    # If it's a file path and not already added, add it
                    if p and p.is_file() and p not in paths:
                        paths.append(p)

                # Add all children of the current item to the end of the queue
                # This ensures breadth-first processing
                queue.extend(item.child(i) for i in range(item.childCount()))

        except Exception as e:
            # Log the error and show a warning to the user
            logger.exception(
                "Error collecting checked file paths for context:")
            QMessageBox.warning(
                self,
                "Context Error",
                f"Failed to gather context from checked files:\n{e}"
            )

        logger.debug(
            f"Calculated checked file paths for worker: {len(paths)} files.")
        return paths

    @Slot()
    def _handle_stop_button(self): logger.debug(
        "Stop button."); self.task_manager.stop_generation()  # Delegate

    # ----- Slots for Handling Task Manager Signals -----
    @Slot()
    def _on_generation_started(self):
        logger.info("UI: Gen started.")
        # *** Set flag ***
        self._generation_complete = False
        # --- Reset UI Elements for generation start ---
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")
        self.chat_input.setReadOnly(True)
        self.chat_input.setStyleSheet("background-color:#333;")
        if self.loading_movie:
            self.loading_indicator_label.show()
            self.loading_movie.start()
        self.copy_code_btn.setEnabled(False)
        self.last_code_block_content = ""  # Clear previous code
        self.context_token_label.setText("Context: ... / ...")

    @Slot(bool)
    def _on_generation_finished(self, stopped: bool):
        logger.info(
            f"UI: Generation finished signal received. Stopped: {stopped}")

        # --- Set completion flag and store the ID locally ---
        self._generation_complete = True
        finished_message_id = self.current_ai_message_id  # Store before clearing
        logger.debug(
            f"Generation finished for message ID: {finished_message_id}")

        # Retrieve the final AI response content
        final_content = ""
        if finished_message_id:
            message_data = self.chat_manager._find_message_by_id(
                finished_message_id)
            final_content = message_data.get(
                'content', '') if message_data else ""
        else:
            logger.warning(
                "_on_generation_finished called but finished_message_id was already None (or current_ai_message_id was None).")

        self.last_ai_response_raw_text = final_content
        code_found = False

        if not stopped:
            self.statusBar().showMessage("Generation Complete.", 3000)
            # ... (Check for diff) ...
            if "```diff" in final_content or re.match(r"--- a/.*\n\+\+\+ b/.*", final_content, re.DOTALL):
                logger.info(
                    "Detected diff format in response, showing DiffDialog.")
                self._show_diff_dialog(final_content)
            # ... (Extract code block) ...
            code_blocks = re.findall(
                r"```(?:[a-zA-Z]+\n)?(.*?)```", final_content, re.DOTALL)
            if code_blocks:
                self.last_code_block_content = code_blocks[-1].strip()
                code_found = True
                logger.info(
                    f"Found {len(code_blocks)} code blocks. Last one stored.")
            else:
                self.last_code_block_content = ""
                logger.info("No code blocks found in the final response.")
        else:
            self.statusBar().showMessage("Generation Stopped.", 3000)
            self.last_code_block_content = ""

        # --- Reset UI Elements ---
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stop")
        self.chat_input.setReadOnly(False)
        self.chat_input.setStyleSheet("")

        if self.loading_movie:
            self.loading_movie.stop()
        self.loading_indicator_label.hide()
        self.status_label.hide()

        # Enable copy code button ONLY if generation finished normally AND code was found
        self.copy_code_btn.setEnabled(code_found and not stopped)

        # Update the context token count in the status bar based on the final history
        self._update_statusbar_context()  # Update status bar immediately

        # --- Reset the ID *immediately* and store last ID ---
        logger.debug(
            f"Resetting current_ai_message_id (was {finished_message_id}).")
        self.current_ai_message_id = None
        self._last_finished_message_id = finished_message_id  # Store for late chunks

    @Slot(str)
    def _update_status_label(self, msg: str):
        (msg and (self.status_label.setText(msg),
         self.status_label.show())) or self.status_label.hide()
        logger.debug(f"Status Label: {msg}")

    @Slot(int, int)
    def _handle_worker_context_info(self, used: int, max_t: int):
        logger.debug(f"Worker ctx: {used}/{max_t}")
        max_t = max(max_t, 1)
        self.context_token_label.setText(f"Context: {used:,}/{max_t:,}")
        r = used/max_t
        c = "color:red;" if r > 0.9 else ("color:orange;" if r > 0.75 else "")
        self.context_token_label.setStyleSheet(c)

    @Slot(str)
    def _handle_stream_chunk(self, chunk: str):
        """
        Slot connected to TaskManager.stream_chunk.
        Determines the target message ID and tells ChatManager to update.
        Handles late chunks arriving after completion signal gracefully.
        """
        target_message_id = self.current_ai_message_id

        # Check if generation finished *just* before this chunk arrived
        # Use getattr for safety during initialization checks
        generation_complete_flag = getattr(
            self, '_generation_complete', True)  # Default true

        if not target_message_id:
            if generation_complete_flag:
                # Generation is marked complete, try using the ID of the message that *just* finished
                last_id = getattr(self, '_last_finished_message_id', None)
                if last_id:
                    logger.debug(
                        f"Late chunk received for recently finished message ID {last_id}. Applying.")
                    target_message_id = last_id
                else:
                    # This should be rare - finished but no record of which message finished
                    logger.warning(
                        "Late chunk received but no record of last finished message ID.")
                    return  # Cannot process this chunk
            else:
                # Generation not marked complete, but ID is None - genuinely unexpected
                logger.warning(
                    "Chunk received but no current msg ID and generation not marked complete.")
                return  # Cannot process this chunk

        # If we have a target_message_id (either current or last finished)
        if target_message_id:
            # Tell ChatManager to append the chunk.
            # ChatManager is responsible for accumulating content and emitting
            # the 'message_content_updated' signal.
            self.chat_manager.stream_ai_content_update(
                target_message_id, chunk)

    @Slot(str)
    def _handle_stream_error(self, err: str):
        logger.error(f"Task Mgr Error: {err}")
        QMessageBox.warning(self, "Gen Error", f"Error:\n{err}")
        self.statusBar().showMessage(f"Error: {err[:50]}...", 5000)

    # ----- Status Bar Update Methods -----
    @Slot()
    def _update_input_token_count(self):
        try:
            txt = self.chat_input.toPlainText()
            tok = count_tokens(txt)
            self._input_token_lbl.setText(f'Input: {tok} tokens')
        except Exception as e:
            logger.error(f"Input tk fail:{e}")
            self._input_token_lbl.setText('Input: Error')

    @Slot()
    def _update_statusbar_context(self):
        # Prevent infinite loops during auto-unchecking
        if self._is_adjusting_checks:
            # logger.debug("Skipping statusbar update due to _is_adjusting_checks flag.")
            return

        if not hasattr(self, 'context_token_label'):
            logger.warning(
                "Cannot update statusbar context: context_token_label not found.")
            return

        # logger.debug("Running _update_statusbar_context...")
        base_tokens = 0
        max_tokens = self.settings.get(
            'context_limit', DEFAULT_CONFIG['context_limit'])
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            logger.warning(
                f"Invalid context_limit '{max_tokens}' in settings, using default.")
            max_tokens = DEFAULT_CONFIG['context_limit']
        # For display and ratio calculation
        max_tokens_display = max(max_tokens, 1)

        try:
            # --- Calculate Base Tokens ---
            system_prompt = self.settings.get('system_prompt', '')
            base_tokens += count_tokens(system_prompt)
            history_snapshot = self.chat_manager.get_history_snapshot()
            limit_index = len(history_snapshot)
            if history_snapshot and history_snapshot[-1].get('role') == 'user':
                limit_index -= 1
            for msg in history_snapshot[:limit_index]:
                base_tokens += count_tokens(msg.get('role', '')) + \
                    count_tokens(msg.get('content', '')) + 4

            # --- Get Checked Files Info ---
            checked_files_info = []
            current_checked_file_tokens = 0
            if hasattr(self, 'file_tree'):
                queue = [self.file_tree.invisibleRootItem().child(i) for i in range(
                    self.file_tree.invisibleRootItem().childCount())]
                while queue:
                    item = queue.pop(0)
                    if item.checkState(0) == Qt.Checked and (item.flags() & Qt.ItemIsUserCheckable):
                        path = self._get_path_from_item(item)
                        if path and path.is_file():
                            token_count = item.data(0, TOKEN_COUNT_ROLE)
                            if isinstance(token_count, int):
                                checked_files_info.append(
                                    (item, token_count))
                                current_checked_file_tokens += token_count
                            else:
                                logger.warning(f"Missing token count data for checked file: {path.name}")
                    queue.extend(item.child(i) for i in range(item.childCount()))
            else:
                logger.warning("Cannot get checked files info: file_tree missing.")

            # --- Calculate Total and Update Label (Preliminary) ---
            # This update shows the state *before* potential auto-unchecking
            current_total_context = base_tokens + current_checked_file_tokens
            display_text = f"Context: {current_total_context:,}/{max_tokens_display:,}"
            self.context_token_label.setText(display_text)
            ratio = current_total_context / max_tokens_display if max_tokens_display > 0 else 1.0
            style_sheet = "color: red;" if ratio > 0.9 else (
                "color: orange;" if ratio > 0.75 else "")
            self.context_token_label.setStyleSheet(style_sheet)

            # --- Auto-Uncheck Logic ---
            if current_total_context > max_tokens:
                logger.info(
                    f"Context ({current_total_context}) exceeds limit ({max_tokens}). Initiating auto-uncheck...")
                notification_shown_this_time = False
                adjustment_made = False  # Track if any item was actually unchecked

                self._is_adjusting_checks = True  # Set re-entrancy flag
                try:
                    tokens_to_remove = current_total_context - max_tokens
                    items_to_uncheck = sorted(
                        checked_files_info, key=lambda x: x[1], reverse=True)

                    for item, token_count in items_to_uncheck:
                        if tokens_to_remove <= 0:
                            break

                        if token_count > 0:
                            if not notification_shown_this_time:
                                first_uncheck_name = item.text(0)
                                QMessageBox.information(
                                    self, "Context Limit Exceeded",
                                    f"Estimated context ({current_total_context:,}) exceeds limit ({max_tokens:,}).\n\n"
                                    f"Automatically unchecking files starting with '{first_uncheck_name}'..."
                                )
                                notification_shown_this_time = True

                            logger.debug(
                                f"Auto-unchecking '{item.text(0)}' ({token_count} tokens).")
                            item.setCheckState(0, Qt.Unchecked)
                            tokens_to_remove -= token_count
                            adjustment_made = True  # Mark that a change happened

                finally:
                    self._is_adjusting_checks = False  # Clear re-entrancy flag
                    # *** If adjustments were made, schedule a final update call ***
                    if adjustment_made:
                        logger.debug(
                            "Scheduling final status bar update after auto-uncheck.")
                        # This ensures the UI reflects the state *after* all unchecks are processed
                        QTimer.singleShot(0, self._update_statusbar_context)

        except Exception as e:
            logger.exception(f"Failed during status bar context update: {e}")
            self.context_token_label.setText("Context: Error")
            self.context_token_label.setStyleSheet("")
            self._is_adjusting_checks = False  # Ensure flag is cleared on error

    def _calculate_checked_files_tokens(self) -> int:
        """
        Calculates the approximate token count for all checked files in the
        file tree, ignoring files over SIZE_LIMIT. Includes approximate
        overhead for file markers used in the context.
        Uses a breadth-first traversal.
        """
        if not hasattr(self, 'file_tree'):
            logger.warning(
                "Cannot calculate checked file tokens: file_tree not found.")
            return 0

        total_tokens = 0
        # Use a set to keep track of processed file paths to avoid double counting
        # if the same file somehow appears multiple times (e.g., symlinks - though not handled explicitly)
        processed_paths = set()

        # Start traversal from the invisible root item's children
        queue = [
            self.file_tree.invisibleRootItem().child(i)
            for i in range(self.file_tree.invisibleRootItem().childCount())
        ]

        while queue:
            item = queue.pop(0)  # Get item from front (BFS)
            is_checked = item.checkState(0) == Qt.Checked
            path = self._get_path_from_item(item)

            if not path:
                continue  # Skip items without a valid path

            # If it's a directory, add its children to the queue for processing
            if path.is_dir():
                queue.extend(item.child(i) for i in range(item.childCount()))
                continue  # Move to the next item in the queue

            # If it's a file, is checked, and hasn't been processed yet:
            if is_checked and path.is_file() and path not in processed_paths:
                processed_paths.add(path)  # Mark as processed
                try:
                    # Check file size before reading
                    file_size = path.stat().st_size
                    if file_size <= TREE_TOKEN_SIZE_LIMIT:
                        # Read content and count tokens
                        content = path.read_text(
                            encoding='utf-8', errors='ignore')
                        file_tokens = count_tokens(content)
                        # Add approximate overhead for context markers
                        # These markers help the LLM identify file boundaries
                        marker_overhead = count_tokens(
                            f"### File: {path.name} ###") + count_tokens("### End File ###")
                        total_tokens += file_tokens + marker_overhead
                        # logger.debug(f"Counted {file_tokens + marker_overhead} tokens for checked file: {path.name}")
                    else:
                        logger.debug(
                            f"Skipping checked file (too large: {file_size} > {TREE_TOKEN_SIZE_LIMIT}): {path.name}")
                except OSError as e:
                    logger.warning(
                        f"OS Error checking/reading checked file {path}: {e}")
                except Exception as e:
                    logger.warning(
                        f"Error processing checked file {path} for token count: {e}")

        # logger.debug(f"Total tokens from checked files: {total_tokens}")
        return total_tokens

    def _copy_last_code_block(self):
        """Copies the content of the last detected code block to the clipboard."""
        # Get the stored code block content
        code_content = self.last_code_block_content

        # Check conditions: not busy, content is a string, and content is not empty
        if not self.task_manager.is_busy() and isinstance(code_content, str) and code_content:
            # Get the system clipboard
            clipboard = QApplication.clipboard()
            # Set the clipboard text
            clipboard.setText(code_content)
            # Show confirmation message in the status bar
            self.statusBar().showMessage("Code copied!", 2000)  # 2000ms duration
        elif self.task_manager.is_busy():
            # Log if tried to copy while AI is busy
            logger.warning("Copy code rejected: Task manager is busy.")
            # Optionally show a message, but status bar might be sufficient
            self.statusBar().showMessage("Cannot copy code while AI is running.", 2000)
        else:
            # Handle cases where there's no code to copy
            logger.debug("Copy code rejected: No code content available.")
            self.statusBar().showMessage("No code block found in the last response.", 2000)

    @Slot(QTreeWidgetItem, int)
    def _handle_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        """
        Handles itemChanged signal from the tree. Initiates recursive cascade
        for directories and updates the status bar context.
        Uses a flag to prevent infinite loops. NO explicit signal blocking.
        """
        # --- Prevent loops from programmatic changes ---
        if self._is_adjusting_checks or self._is_cascading_checks:
            # logger.debug("Ignoring itemChanged due to flag.")
            return

        # --- Process only changes in the checkbox column (0) ---
        if column == 0:
            logger.debug(
                f"User interaction detected: '{item.text(0)}', State: {item.checkState(0)}")
            path = self._get_path_from_item(item)

            # --- Cascade Check State for Directories ---
            # Check if it's a directory that the user interacted with
            if path and path.is_dir() and (item.flags() & Qt.ItemIsUserCheckable):
                logger.debug(
                    f"Directory '{item.text(0)}' check state changed by user, starting cascade...")
                self._is_cascading_checks = True  # Set flag
                try:
                    new_state = item.checkState(0)
                    # Call recursive function - setCheckState inside will emit itemChanged,
                    # but those calls will be blocked by the _is_cascading_checks flag above.
                    self._set_check_state_recursive(item, new_state)
                finally:
                    self._is_cascading_checks = False  # Clear flag AFTER recursion
                    logger.debug(
                        f"Finished cascading for '{item.text(0)}'. Scheduling status update.")
                    # *** ADD EXPLICIT UPDATE ***
                    if hasattr(self, 'file_tree'):
                        logger.debug("Forcing tree widget update.")
                        self.file_tree.update()  # Force repaint of the widget area
                    # *** END ADDITION ***
                    QTimer.singleShot(0, self._update_statusbar_context)
                    return

            # --- Update Status Bar (for single item change or scheduled update) ---
            # This runs if it wasn't a directory cascade OR if called by the QTimer
            logger.debug("Running status bar update.")
            self._update_statusbar_context()

    @Slot(QPoint)
    def _show_file_tree_context_menu(self, pos: QPoint):
        """
        Creates and shows the context menu for the file tree widget.
        Actions like New File/Folder, Rename, Delete, Refresh are included.
        Actions are enabled/disabled based on the selected item.
        """
        # Get the item at the position where the right-click occurred
        item = self.file_tree.itemAt(pos)
        # Map the local widget position to global screen position for the menu
        global_pos = self.file_tree.mapToGlobal(pos)
        # Get the Path object associated with the clicked item (if any)
        path = self._get_path_from_item(item)

        # Determine if the clicked item is the project root itself
        is_root = (path is not None and path ==
                   self.workspace_manager.project_path)

        # Create the context menu
        menu = QMenu()

        # Create actions
        new_file_action = QAction("New File...", self)
        new_folder_action = QAction("New Folder...", self)
        refresh_action = QAction("Refresh", self)
        rename_action = QAction("Rename...", self)
        delete_action = QAction("Delete...", self)

        # --- Enable/Disable Actions based on context ---
        # Can create if a path exists (file or folder) or if the project root itself is valid
        can_create = (path is not None) or (
            self.workspace_manager.project_path is not None)
        # Can modify (rename/delete) only if a path exists AND it's not the project root
        can_modify = (path is not None and not is_root)

        new_file_action.setEnabled(can_create)
        new_folder_action.setEnabled(can_create)
        rename_action.setEnabled(can_modify)
        delete_action.setEnabled(can_modify)
        # Refresh is always enabled

        # --- Connect Actions to Handlers ---
        # Use lambdas to pass necessary arguments (like the selected item or type)
        new_file_action.triggered.connect(lambda: self._tree_new_file_or_folder(item, True))  # True for is_file
        new_folder_action.triggered.connect(lambda: self._tree_new_file_or_folder(item, False))  # False for is_file
        refresh_action.triggered.connect(
            lambda: self.workspace_manager.populate_file_tree(self.file_tree))
        rename_action.triggered.connect(lambda: self._tree_rename_item(item))
        delete_action.triggered.connect(lambda: self._tree_delete_item(item))

        # --- Add Actions to Menu ---
        menu.addActions([new_file_action, new_folder_action])
        menu.addSeparator()
        menu.addActions([rename_action, delete_action])
        menu.addSeparator()
        menu.addAction(refresh_action)

        # --- Execute Menu ---
        # Show the menu at the global position where the click happened
        menu.exec(global_pos)

    def _get_path_from_item(self, item: Optional[QTreeWidgetItem]) -> Optional[Path]:
        """
        Safely retrieves the Path object stored in a QTreeWidgetItem's data.

        Args:
            item: The QTreeWidgetItem to get the path from, or None.

        Returns:
            A Path object if the item is valid and has path data stored,
            otherwise None.
        """
        # Check if the item exists and if it has data stored in the UserRole
        if item and item.data(0, Qt.UserRole):
            # Retrieve the data (which should be a string representation of the path)
            path_str = item.data(0, Qt.UserRole)
            try:
                # Convert the string back to a Path object
                return Path(path_str)
            except Exception as e:
                # Log error if conversion fails (e.g., invalid path string stored)
                logger.error(
                    f"Failed to convert item data '{path_str}' to Path: {e}")
                return None
        else:
            # Return None if the item is None or has no data in UserRole
            return None

    def _tree_new_file_or_folder(self, sel_item: Optional[QTreeWidgetItem], is_file: bool):
        """
        Handles creating a new file or folder based on the context menu action.
        Determines the parent directory, prompts for a name, checks existence,
        and performs the creation.
        """
        # --- Determine Parent Directory ---
        parent_path = self.workspace_manager.project_path  # Default to project root
        target_path = self._get_path_from_item(sel_item)
        if target_path:
            # If selected item is a directory, use it as parent
            # If selected item is a file, use its parent directory
            parent_path = target_path if target_path.is_dir() else target_path.parent
        logger.debug(f"Determined parent path for new item: {parent_path}")

        # --- Get Name from User ---
        item_type = "File" if is_file else "Folder"
        new_name, ok = QInputDialog.getText(
            self, f"New {item_type}", f"Enter name for new {item_type}:")

        if not ok or not new_name:
            logger.debug(
                f"New {item_type} cancelled by user or empty name provided.")
            return  # User cancelled or entered empty name

        new_name = new_name.strip()
        if not new_name:
            logger.warning(
                f"New {item_type} name cannot be empty after stripping whitespace.")
            QMessageBox.warning(self, "Invalid Name", "Name cannot be empty.")
            return

        # --- Check Existence and Create ---
        new_path = parent_path / new_name
        logger.info(f"Attempting to create {item_type}: {new_path}")

        if new_path.exists():
            error_msg = f"'{new_path.name}' already exists in this location."
            logger.warning(error_msg)
            QMessageBox.warning(self, "Creation Failed", error_msg)
            return

        # --- Perform Creation ---
        try:
            if is_file:
                # Use WorkspaceManager to create the file
                created_path = self.workspace_manager.create_new_file(new_path)  # Pass full path
                if created_path:
                    logger.info(f"Successfully created file: {created_path}")
                    # Refresh tree and open the new file in the editor
                    self.workspace_manager.populate_file_tree(self.file_tree)
                    self.workspace_manager.load_file(
                        created_path, self.tab_editor)
                    self.statusBar().showMessage(
                        f"Created file '{new_name}'", 3000)
                else:
                    # create_new_file already logs errors, but we can add a fallback
                    logger.error(
                        f"WorkspaceManager failed to create file {new_path}, check previous logs.")
                    # QMessageBox might be redundant if create_new_file shows one
            else:  # Create a folder
                new_path.mkdir()
                logger.info(f"Successfully created directory: {new_path}")
                # Refresh tree
                self.workspace_manager.populate_file_tree(self.file_tree)
                self.statusBar().showMessage(
                    f"Created folder '{new_name}'", 3000)

        except OSError as e:
            error_msg = f"Failed to create {item_type} '{new_name}':\n{e}"
            logger.error(error_msg)
            QMessageBox.critical(
                self, f"{item_type} Creation Error", error_msg)
        except Exception as e:
            # Catch any other unexpected errors
            error_msg = f"An unexpected error occurred creating {item_type} '{new_name}':\n{e}"
            logger.exception(error_msg)  # Log full traceback
            QMessageBox.critical(
                self, f"{item_type} Creation Error", error_msg)

    def _tree_rename_item(self, sel_item: Optional[QTreeWidgetItem]):
        """
        Handles renaming a file or folder selected in the file tree.
        Prompts the user for a new name and performs the rename operation
        on the filesystem and updates the tree widget. Also handles updating
        references in open editor tabs if the renamed item was open.
        """
        # Get the current path from the selected tree item
        current_path = self._get_path_from_item(sel_item)

        # --- Validation ---
        # Ensure an item is selected, has a valid path, and is not the project root itself
        if not sel_item or not current_path or current_path == self.workspace_manager.project_path:
            logger.warning(
                "Rename request invalid: No item selected, path missing, or trying to rename project root.")
            # Optionally show a message box, but usually context menu disables rename for root
            return

        current_name = current_path.name

        # --- Get New Name from User ---
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Item",
            f"Enter new name for '{current_name}':",
            text=current_name  # Pre-fill with current name
        )

        # --- Process Rename ---
        if ok and new_name:
            new_name = new_name.strip()  # Remove leading/trailing whitespace
            if new_name != current_name:
                new_path = current_path.parent / new_name
                logger.info(
                    f"Attempting rename: '{current_path}' -> '{new_path}'")

                # Check if the new name already exists
                if new_path.exists():
                    error_msg = f"Cannot rename: '{new_path.name}' already exists in this folder."
                    logger.warning(error_msg)
                    QMessageBox.warning(self, "Rename Failed", error_msg)
                    return

                # --- Perform Rename Operation ---
                try:
                    # Filesystem rename
                    current_path.rename(new_path)
                    logger.info(f"Filesystem rename successful.")

                    # Update Tree Widget Item
                    sel_item.setText(0, new_name)  # Update displayed name
                    sel_item.setData(0, Qt.UserRole, str(new_path))  # Update stored path

                    # --- Update Open Editor Tab (if applicable) ---
                    if current_path in self.workspace_manager.open_editors:
                        logger.debug(
                            f"Updating open editor tab for renamed item: {current_name} -> {new_name}")
                        # Get the editor widget associated with the OLD path
                        editor = self.workspace_manager.open_editors.pop(
                            current_path)
                        # Update the editor's objectName (which stores the path)
                        editor.setObjectName(str(new_path))
                        # Re-insert the editor into the dictionary with the NEW path
                        self.workspace_manager.open_editors[new_path] = editor

                        # Find the corresponding tab and update its text and tooltip
                        for i in range(self.tab_editor.count()):
                            if self.tab_editor.widget(i) == editor:
                                self.tab_editor.setTabText(i, new_name)
                                self.tab_editor.setTabToolTip(i, str(new_path))
                                break  # Found the tab, no need to continue loop
                        self.editors_changed.emit()  # Signal change if needed

                    self.statusBar().showMessage(
                        f"Renamed '{current_name}' to '{new_name}'", 3000)
                    # Optionally, refresh parent node in tree if needed, though setText/setData often suffices
                    # self.workspace_manager.populate_file_tree(self.file_tree) # Could refresh whole tree if easier

                except OSError as e:
                    error_msg = f"Failed to rename '{current_name}':\n{e}"
                    logger.error(error_msg)
                    QMessageBox.critical(self, "Rename Error", error_msg)
                    # Attempt to revert tree item text if FS rename failed? Or just leave as is?
                    # sel_item.setText(0, current_name)
                    # sel_item.setData(0, Qt.UserRole, str(current_path))
                except Exception as e:
                    # Catch any other unexpected errors
                    error_msg = f"An unexpected error occurred during rename:\n{e}"
                    logger.exception(error_msg)  # Log full traceback
                    QMessageBox.critical(self, "Rename Error", error_msg)

            else:
                logger.debug("Rename cancelled: New name is the same as the old name.")
        else:
            logger.debug("Rename cancelled by user or empty name provided.")

    def _tree_delete_item(self, sel_item: Optional[QTreeWidgetItem]):
        """
        Handles deleting a file or folder selected in the file tree.
        Confirms with the user, performs the deletion on the filesystem,
        closes any open editor tabs for the deleted file, and removes the
        item from the tree widget.
        """
        # Get the Path object for the selected item
        current_path = self._get_path_from_item(sel_item)

        # --- Validation ---
        # Ensure an item is selected, has a path, and is not the project root
        if not sel_item or not current_path or current_path == self.workspace_manager.project_path:
            logger.warning(
                "Delete request invalid: No item selected, path missing, or trying to delete project root.")
            return

        # Determine if it's a file or folder for the confirmation message
        item_type = "folder" if current_path.is_dir() else "file"

        # --- Confirmation Dialog ---
        reply = QMessageBox.warning(
            self,
            f"Confirm Delete {item_type.capitalize()}",
            f"Are you sure you want to permanently delete the {item_type}:\n'{current_path.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,  # Buttons
            QMessageBox.StandardButton.Cancel  # Default button
        )

        # --- Process Deletion ---
        if reply == QMessageBox.StandardButton.Yes:
            logger.info(
                f"User confirmed deletion for {item_type}: {current_path}")
            try:
                delete_successful = False
                if current_path.is_file():
                    # --- Delete File ---
                    # Check if the file is open in an editor tab
                    if current_path in self.workspace_manager.open_editors:
                        logger.debug(
                            f"Closing open editor tab for deleting file: {current_path.name}")
                        # Find and close the specific tab *before* deleting the file
                        editor_to_close = self.workspace_manager.open_editors[current_path]
                        tab_index_to_close = -1
                        for i in range(self.tab_editor.count()):
                            if self.tab_editor.widget(i) == editor_to_close:
                                tab_index_to_close = i
                                break
                        if tab_index_to_close != -1:
                            # Use the manager's close_tab method which handles cleanup
                            self.workspace_manager.close_tab(tab_index_to_close, self.tab_editor)
                        else:
                            # Should not happen if dict is consistent, but log warning
                            logger.warning(f"Editor for {current_path} in dict but not found in tabs during delete.")
                            # Still attempt to remove from dict just in case
                            del self.workspace_manager.open_editors[current_path]

                    # Delete the file from the filesystem
                    os.remove(current_path)
                    delete_successful = True

                elif current_path.is_dir():
                    # --- Delete Directory ---
                    # Recursively delete the directory and its contents
                    shutil.rmtree(current_path)
                    delete_successful = True
                else:
                    # Should not happen if validation is correct, but handle defensively
                    logger.warning(
                        f"Cannot delete: '{current_path.name}' is neither a file nor a directory.")

                # --- Update UI if deletion was successful ---
                if delete_successful:
                    logger.info(
                        f"Successfully deleted {item_type}: {current_path}")
                    # Remove the item from the tree widget
                    parent_item = sel_item.parent()
                    if parent_item:
                        parent_item.removeChild(sel_item)
                    else:
                        # If it's a top-level item, remove it directly from the tree
                        index = self.file_tree.indexOfTopLevelItem(sel_item)
                        if index != -1:
                            self.file_tree.takeTopLevelItem(index)
                    # Update status bar context (token count will decrease)
                    self._update_statusbar_context()
                    self.statusBar().showMessage(
                        f"Deleted '{current_path.name}'", 3000)

            except OSError as e:
                error_msg = f"Failed to delete {item_type} '{current_path.name}':\n{e}"
                logger.error(error_msg)
                QMessageBox.critical(
                    self, f"{item_type.capitalize()} Deletion Error", error_msg)
            except Exception as e:
                # Catch any other unexpected errors
                error_msg = f"An unexpected error occurred deleting {item_type} '{current_path.name}':\n{e}"
                logger.exception(error_msg)  # Log full traceback
                QMessageBox.critical(
                    self, f"{item_type.capitalize()} Deletion Error", error_msg)
        else:
            logger.debug("User cancelled deletion.")

    # ----- Chat Edit/Delete Handling Slots -----
    @Slot(str, str)
    def _handle_edit_submit(self, message_id: str, new_content: str):
        """
        Slot connected to ChatMessageWidget.editSubmitted signal.
        Updates the message content in ChatManager, truncates history after
        the edited message, adds an AI placeholder, and starts a new generation.
        """
        # Prevent submission if AI is busy
        if self.task_manager.is_busy():
            logger.warning("Edit submit ignored: Task manager is busy.")
            # Find the widget and force it out of edit mode if submission failed
            widget = self._find_widget_by_id(message_id)
            if widget:
                widget.exit_edit_mode()
            QMessageBox.warning(
                self, "Busy", "Cannot submit edit while AI is generating.")
            return

        # 1. Update the message content in the data model (ChatManager)
        update_success = self.chat_manager.update_message_content(
            message_id, new_content)

        if update_success:
            logger.info(
                f"Content updated for message {message_id}. Truncating and resubmitting...")

            # 2. Truncate the history *after* the edited message
            # This removes all subsequent user/AI messages
            self.chat_manager.truncate_history_after(message_id)

            # 3. Add a new AI placeholder for the response to the edited message
            # History should now end with the updated user message
            ai_placeholder_id = self.chat_manager.add_ai_placeholder()

            if ai_placeholder_id:
                # Store the new placeholder ID for streaming
                self.current_ai_message_id = ai_placeholder_id
                logger.debug(
                    f"New AI placeholder {ai_placeholder_id} added. Starting generation...")

                # 4. Start a new generation using the truncated history
                # The history passed will end with the *updated* user message
                self.task_manager.start_generation(
                    self.chat_manager.get_history_snapshot(),  # Get snapshot *before* placeholder added again!
                    self._calculate_checked_file_paths_for_worker(),
                    self.workspace_manager.project_path
                )
                # Note: The ChatMessageWidget automatically exits edit mode upon emitting editSubmitted
            else:
                logger.error(
                    f"Failed to add AI placeholder after edit submit for {message_id}.")
                # Exit edit mode on the widget even if placeholder failed
                widget = self._find_widget_by_id(message_id)
                if widget:
                    widget.exit_edit_mode()
        else:
            # This case means ChatManager couldn't find the message to update
            logger.warning(
                f"Edit submit failed: Could not update content for message {message_id}.")
            # Ensure widget exits edit mode if update failed
            widget = self._find_widget_by_id(message_id)
            if widget:
                widget.exit_edit_mode()

    @Slot(str)
    def _handle_edit_request(self, message_id: str):
        """
        Slot connected to ChatMessageWidget.editRequested signal.
        Finds the corresponding widget and puts it into edit mode.
        Scrolls the list view to ensure the editing widget is visible.
        """
        # Check if AI is busy, prevent editing during generation
        if self.task_manager.is_busy():
            logger.warning("Edit request ignored: Task manager is busy.")
            QMessageBox.warning(
                self, "Busy", "Cannot edit messages while AI is generating.")
            return

        # Find the specific ChatMessageWidget instance using its ID
        widget = self._find_widget_by_id(message_id)
        if widget:
            logger.debug(
                f"Entering edit mode for widget with message ID: {message_id}")
            # Tell the widget to switch to its editing UI
            widget.enter_edit_mode()

            # --- Scroll to the item ---
            # Find the QListWidgetItem associated with the widget
            list_item = None
            for i in range(self.chat_list_widget.count()):
                current_item = self.chat_list_widget.item(i)
                if self.chat_list_widget.itemWidget(current_item) == widget:
                    list_item = current_item
                    break

            # If the list item was found, scroll the list view to make it visible
            if list_item:
                self.chat_list_widget.scrollToItem(
                    list_item, QListWidget.ScrollHint.EnsureVisible)
            else:
                logger.warning(
                    f"Could not find QListWidgetItem for widget ID {message_id} to scroll to.")
        else:
            logger.warning(
                f"Edit requested for message ID {message_id}, but widget not found.")

    @Slot(str, str)
    def _handle_edit_submit(self, m_id:str, ncont:str): (not self.task_manager.is_busy() and self.chat_manager.update_message_content(m_id,ncont) and (self.chat_manager.truncate_history_after(m_id), (aid := self.chat_manager.add_ai_placeholder()) and (setattr(self,'current_ai_message_id',aid), logger.info("Resubmitting..."), self.task_manager.start_generation(self.chat_manager.get_history_snapshot(), self._calculate_checked_file_paths_for_worker(), self.workspace_manager.project_path)) or logger.error("Placeholder fail")) or (logger.warning(f"Edit fail {m_id}"), (w := self._find_widget_by_id(m_id)) and w.exit_edit_mode())) or QMessageBox.warning(self,"Busy","Busy")

    @Slot(str)
    def _handle_delete_request(self, message_id: str):
        """
        Slot connected to ChatMessageWidget.deleteRequested signal.
        Deletes the specified message and truncates the history after it.
        """
        # Prevent deletion if AI is busy
        if self.task_manager.is_busy():
            logger.warning("Delete request ignored: Task manager is busy.")
            QMessageBox.warning(
                self, "Busy", "Cannot delete messages while AI is generating.")
            return

        logger.info(f"Handling delete request for message ID: {message_id}")
        # Delegate deletion and truncation logic to the ChatManager
        delete_success = self.chat_manager.delete_message_and_truncate(
            message_id)
        if not delete_success:
            # This case usually means the message ID wasn't found in ChatManager
            logger.warning(
                f"Failed to delete message {message_id} (likely not found).")
    # ----- Project/Settings Actions -----

    def _open_project(self):
        """
        Opens a directory selection dialog to allow the user to choose a
        new project folder. Delegates the actual project loading and UI
        update to the WorkspaceManager.
        """
        # Suggest starting the dialog in the parent directory of the current project
        start_dir = str(
            self.project_path.parent) if self.project_path else str(Path.cwd())

        # Open the native directory selection dialog
        selected_directory = QFileDialog.getExistingDirectory(
            self,
            "Open Project Folder",  # Dialog title
            start_dir             # Initial directory
            # Options can be added here if needed, e.g., QFileDialog.Option.ShowDirsOnly
        )

        # If the user selected a directory (didn't cancel)
        if selected_directory:
            logger.info(
                f"User selected new project directory: {selected_directory}")
            # Convert the selected path string to a Path object
            new_project_path = Path(selected_directory)
            # Tell the WorkspaceManager to handle the project change.
            # The WorkspaceManager will emit signals that this MainWindow
            # listens to in order to update the UI (tree, tabs, settings, etc.).
            self.workspace_manager.set_project_path(new_project_path)
        else:
            logger.debug("Open project dialog cancelled by user.")

    def _new_file(self):
        """
        Prompts the user for a filename and creates a new, empty file
        in the root of the current project directory. Opens the file
        in a new editor tab.
        """
        # Prompt user for the new filename
        new_name, ok = QInputDialog.getText(
            self, 'New File', 'Enter filename:')

        if ok and new_name:
            new_name = new_name.strip()
            if not new_name:
                QMessageBox.warning(self, "Invalid Name", "Filename cannot be empty.")
                return

            logger.info(
                f"Attempting to create new file in project root: {new_name}")
            # Delegate creation to WorkspaceManager (pass only the filename)
            # Assuming create_new_file handles joining with project_path
            # and checks for existence.
            created_path = self.workspace_manager.create_new_file(new_name)

            if created_path:
                logger.info(f"Successfully created file: {created_path}")
                # Refresh the file tree to show the new file
                self.workspace_manager.populate_file_tree(self.file_tree)
                # Load the new empty file into an editor tab
                self.workspace_manager.load_file(created_path, self.tab_editor)
                self.statusBar().showMessage(
                    f"Created file '{new_name}'", 3000)
            else:
                # Error message likely shown by create_new_file/WorkspaceManager signal
                logger.warning(f"Failed to create file '{new_name}' via WorkspaceManager.")
                # Optionally show another message box here if create_new_file doesn't guarantee one
                # QMessageBox.warning(self, "Creation Failed", f"Could not create file '{new_name}'. See logs.")

        else:
            logger.debug(
                "New file action cancelled by user or empty name provided.")

    def _save_project_settings(self):
        """
        Saves the current application settings (self.settings) to the
        .patchmind.json file within the current project directory.
        Crucially, it first updates self.settings from the ConfigDock UI
        if the dock exists.
        """
        # --- Check if ConfigDock exists ---
        # Saving settings should reflect the current UI state if possible
        if hasattr(self, 'config_dock') and self.config_dock is not None:
            logger.debug(
                "Updating self.settings from ConfigDock UI before saving...")
            # Ask the dock to update the self.settings dictionary based on its widgets
            self.config_dock.update_settings_from_ui(self.settings)
        else:
            # Log a warning if the dock isn't available, as saved settings
            # might not match the user's latest choices in the UI.
            logger.warning(
                "Cannot update settings from ConfigDock before saving (dock not found). Saving current self.settings state.")

        # --- Check if project path is valid ---
        if hasattr(self, 'workspace_manager') and self.workspace_manager.project_path.is_dir():
            project_dir = self.workspace_manager.project_path
            logger.info(
                f"Saving project settings to: {project_dir / '.patchmind.json'}")
            try:
                # Call the function that handles writing the JSON file
                save_project_config(project_dir, self.settings)
                self.statusBar().showMessage('Project settings saved.', 3000)  # Confirmation
            except Exception as e:
                # Catch errors during file writing
                logger.exception(
                    f"Failed to save project config to {project_dir}: {e}")
                QMessageBox.critical(self, "Save Error",
                                     f"Could not save project settings:\n{e}")
        else:
            # Log an error if we can't determine where to save the file
            logger.error(
                "Cannot save settings: Project path is invalid or WorkspaceManager not found.")
            QMessageBox.warning(
                self, "Save Error", "Cannot save settings: No valid project directory specified.")

    def _open_settings(self):
        """Opens the Settings dialog and applies changes if accepted."""
        if not hasattr(self, 'config_dock'):
            logger.error(
                "Settings action failed: ConfigDock ('self.config_dock') not found.")
            QMessageBox.critical(
                self, "Error", "Configuration panel is missing or failed to load.")
            return

        # Create the dialog with a copy of the current settings
        # Pass 'self' as the parent
        dialog = SettingsDialog(self.settings.copy(), self)
        original_settings = self.settings.copy()
        # Execute the dialog modally. Check if the user clicked "OK".
        if dialog.exec() == QDialog.Accepted:
            logger.info("Settings dialog accepted by user.")
            try:
                # --- Apply Accepted Settings ---
                # Update the main settings dictionary with changes from the dialog
                self.settings.update(dialog.settings)
                new_settings = dialog.settings
                changed_keys = {k for k in DEFAULT_CONFIG if original_settings.get(k) != new_settings.get(k)}
                logger.debug(f"Changed settings keys: {changed_keys}")
                # Apply changes that affect the UI or core components
                if 'theme' in changed_keys:
                    self._apply_theme(save=False) # Apply theme first (might affect highlighter)
                if 'editor_font' in changed_keys or 'editor_font_size' in changed_keys:
                    self._apply_editor_font(save=False) # Apply font

                # *** APPLY SYNTAX STYLE IF CHANGED ***
                if 'syntax_highlighting_style' in changed_keys:
                    if hasattr(self, 'workspace_manager'):
                        self.workspace_manager.apply_syntax_style(self.settings['syntax_highlighting_style'])
                    else:
                        logger.error("Cannot apply syntax style: WorkspaceManager not found.")


                # Update services based on potentially changed LLM/API settings
                self._update_active_services_and_context()

                # Refresh model list if provider might have changed
                self._refresh_models_for_dock(
                    self.settings.get('provider', 'Ollama'))

                # Update the config dock UI to reflect the new settings
                self.config_dock.populate_controls(self.settings)
                # Also update prompt lists in the dock if they are managed via settings
                self.config_dock.populate_available_prompts(
                    self.settings.get('prompts', []))
                self.config_dock.populate_selected_prompts(self.settings.get(
                    'selected_prompt_ids', []), self.settings.get('prompts', []))

                # Save the updated settings persistently
                self._save_project_settings()
                logger.info("Settings applied and saved.")

            except Exception as e:
                # Catch potential errors during settings application
                logger.exception("Error applying settings after dialog acceptance:")
                QMessageBox.critical(
                     self, "Apply Settings Error", f"Failed to apply settings:\n{e}")
        else:
            # User clicked Cancel or closed the dialog
            logger.info("Settings dialog cancelled by user.")

    def _run_benchmark(self): QMessageBox.information(self, "Bench", "NI")

    # ----- Misc Helpers -----
    def _find_widget_by_id(self, message_id: str) -> Optional[ChatMessageWidget]:
        """
        Iterates through the items in the chat list widget to find the
        ChatMessageWidget associated with the given message ID.

        Args:
            message_id: The unique ID of the message to find.

        Returns:
            The ChatMessageWidget instance if found, otherwise None.
        """
        if not hasattr(self, 'chat_list_widget'):
            logger.error("Cannot find widget by ID: chat_list_widget does not exist.")
            return None

        # Iterate through all items in the QListWidget
        for i in range(self.chat_list_widget.count()):
            item = self.chat_list_widget.item(i)
            # Get the custom widget associated with this list item
            widget = self.chat_list_widget.itemWidget(item)

            # Check if the widget is a ChatMessageWidget and has the matching message_id attribute
            if (widget and
                    isinstance(widget, ChatMessageWidget) and
                    getattr(widget, 'message_id', None) == message_id):
                return widget  # Return the found widget

        # If the loop completes without finding the widget
        logger.debug(
            f"Widget with message ID '{message_id}' not found in chat list.")
        return None

    # ----- Shortcuts -----
    def _init_shortcuts(self):
        """Initializes global keyboard shortcuts for the main window."""
        logger.debug("Initializing keyboard shortcuts.")

        # Define shortcuts and their corresponding slots/lambdas
        shortcuts = {
            'Ctrl+Return': self._send_prompt,
            'Ctrl+Enter': self._send_prompt,  # Common alternative for sending
            'Ctrl+S': self._save_current_tab,
            'Ctrl+O': self._open_project,
            'Ctrl+N': self._new_file,
            'Ctrl+,': self._open_settings,  # Often used for settings/preferences
            # Ctrl+W for closing tabs needs a lambda to check if tabs exist first
            'Ctrl+W': lambda: self.tab_editor.count() > 0 and self._close_tab_request(self.tab_editor.currentIndex()),
            # Add other shortcuts as needed
            # 'F5': self._some_refresh_action,
        }

        # Create QShortcut objects and connect them
        for key_sequence, target_slot in shortcuts.items():
            try:
                shortcut = QShortcut(QKeySequence(key_sequence), self)
                # Connect the shortcut's 'activated' signal to the target slot/lambda
                shortcut.activated.connect(target_slot)
                # logger.debug(f"  Shortcut '{key_sequence}' connected.") # Optional: Verbose logging
            except Exception as e:
                # Log if creating/connecting a shortcut fails
                logger.error(
                    f"Failed to create or connect shortcut for '{key_sequence}': {e}")

    # ----- Window Close Event -----
    def closeEvent(self, event):
        """Handles window close events, saving settings."""
        logger.info("Close event triggered. Saving state...")

        # --- Update last project path in settings ---
        # Check if workspace manager and project path exist before accessing
        if hasattr(self, 'workspace_manager') and self.workspace_manager.project_path:
            # Use dictionary assignment, not setattr
            self.settings['last_project_path'] = str(
                self.workspace_manager.project_path)
            logger.debug(
                f"Updated last_project_path in settings to: {self.settings['last_project_path']}")
        else:
            logger.warning(
                "Could not update last_project_path: WorkspaceManager or project_path missing.")

        # --- Save settings ---
        # Check if config dock exists, as saving might depend on UI state via update_settings_from_ui
        if hasattr(self, 'config_dock'):
            # This call updates self.settings from the dock's UI elements before saving
            logger.debug(
                "Saving project settings via ConfigDock before closing.")
            self._save_project_settings()  # This internally calls update_settings_from_ui and save_project_config
        else:
            # Fallback: Save settings directly if dock doesn't exist, but UI state won't be captured
            logger.warning(
                "ConfigDock not found. Saving settings directly without capturing dock UI state.")
            # Ensure project_path exists before saving directly
            if hasattr(self, 'workspace_manager') and self.workspace_manager.project_path:
                save_project_config(
                    self.workspace_manager.project_path, self.settings)
            else:
                logger.error(
                    "Cannot save settings directly: WorkspaceManager or project_path missing.")

        # Accept the close event to allow the window to close
        event.accept()
        logger.info("Application closing.")
# ───────────────────────── Launcher ─────────────────────────


def launch_app():
    QApplication.setApplicationName("PatchMind IDE")
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        win=MainWindow()
        win.show()
    except Exception as e:
        logger.exception("FATAL Init!"); QMessageBox.critical(None,"Fatal",f"Init fail:\n{e}\n\nLogs?"); sys.exit(1)
    sys.exit(app.exec())

if __name__ == '__main__':
    launch_app()
