# pm/ui/main_window.py
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, # Changed import
                             QApplication, QStatusBar, QSplitter, QPlainTextEdit,
                             QMessageBox, QFileDialog, QTreeWidget, QDockWidget,
                             QListWidget, QPushButton, QTabWidget, QLabel,
                             QHeaderView, QSizePolicy, QTreeWidgetItemIterator, QTreeWidgetItem,
                             QMenu)
from PyQt6.QtGui import (QAction, QKeySequence, QFont, QIcon, QDesktopServices, # Changed import
                         QCursor, QShowEvent)
from PyQt6.QtCore import Qt, pyqtSlot, QSize, QTimer, QPoint, QUrl, QByteArray, QSettings # Changed imports
from loguru import logger
import qtawesome as qta
from functools import partial
import traceback # Ensure traceback is imported

# --- Core Components ---
from ..core.app_core import AppCore
from ..core.logging_setup import LOG_PATH
from ..core.constants import TOKEN_COUNT_ROLE

# --- UI Components ---
from .main_window_ui import MainWindowUI
from .config_dock import ConfigDock
from .controllers.status_bar_controller import StatusBarController

# --- Action Manager ---
from ..core.action_manager import ActionManager

# --- Handlers ---
from ..handlers.chat_action_handler import ChatActionHandler
from ..handlers.workspace_action_handler import WorkspaceActionHandler
from ..handlers.prompt_action_handler import PromptActionHandler
from ..handlers.settings_action_handler import SettingsActionHandler
from ..handlers.change_queue_handler import ChangeQueueHandler

class MainWindow(QMainWindow):
    """
    Main application window. Owns core components, UI structure,
    and orchestrates connections between them.
    """
    def __init__(self):
        super().__init__()

        logger.info("Initializing MainWindow...")

        self._enforce_limit_timer = QTimer(self)
        self._enforce_limit_timer.setSingleShot(True)
        self._enforce_limit_timer.setInterval(150)
        self._enforce_limit_timer.timeout.connect(self._check_and_enforce_token_limit)
        self._initial_refresh_done = False

        # --- Initialize Core ---
        # --- FIX: Do NOT pass 'self' (MainWindow instance) as parent to AppCore ---
        # This works around a TypeError when QObject constructor receives a MainWindow instance.
        # Ideally, this parenting should work, but this resolves the immediate error.
        self.core = AppCore(parent=None)
        # ------------------------------------------------------------------------

        # --- Early Connections ---
        self.core.models.llm_models_updated.connect(self._update_config_dock_model_list)
        self.core.models.model_refresh_error.connect(self._handle_config_dock_model_error)

        self.core.settings.settings_loaded.connect(self._populate_config_dock_from_settings)
        self.core.settings.settings_loaded.connect(self._apply_initial_settings)
        logger.debug("MainWindow: Early pyqtSignal connections established.")

        # --- Initialize UI and Actions ---
        self.ui = MainWindowUI()
        self.action_manager = ActionManager(self)

        # --- Setup Main Window Shell ---
        self.setWindowTitle(f"PatchMind IDE")
        self.setMinimumSize(1200, 700)

        self.ui.setup_ui(self, self.core.settings.get_all_settings())

        self.action_manager.create_menus(self.menuBar())
        self.action_manager.create_toolbars(self)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_controller = StatusBarController(self.status_bar, self)

        self._init_handlers()
        self._connect_pyqtSignals()
        self._load_window_state()
        self._populate_initial_state() # Populates tree etc.

        logger.info("MainWindow initialization complete (initial refresh deferred to showEvent).")
        # show() called externally by launch_app

    def showEvent(self, event: QShowEvent):
        """Override showEvent to trigger initial actions and set splitter sizes."""
        # --- IMPORTANT: Call base class implementation FIRST ---
        super().showEvent(event)

        # --- Set Splitter Sizes using a Timer ---
        # Check if splitter exists and it's the first time the window is shown non-spontaneously
        if self.ui.main_splitter and not event.spontaneous() and not hasattr(self, '_splitter_sizes_set'):
             logger.debug("showEvent: Scheduling initial splitter size application.")
             # Use a QTimer to ensure this runs after the event loop processes the show event
             QTimer.singleShot(0, self._apply_initial_splitter_sizes)

             self._splitter_sizes_set = True # Flag to prevent re-applying on subsequent shows

        # --- Existing initial refresh logic ---
        if not self._initial_refresh_done and not event.spontaneous():
            logger.info("MainWindow: First showEvent detected, triggering initial model refresh.")
            QTimer.singleShot(10, self._refresh_config_dock_models) # Keep this separate timer
            self._initial_refresh_done = True

    # --- NEW METHOD to apply sizes ---
    @pyqtSlot() # Changed decorator
    def _apply_initial_splitter_sizes(self):
        """Applies the calculated initial sizes and then adjusts the splitter."""
        if self.ui.main_splitter:
            tree_width = 250
            editor_width = 500
            chat_width = 500
            config_width = 300
            sizes = [tree_width, editor_width, chat_width, config_width]

            # --- Debugging: Inspect Minimum Widths (Keep this) ---
            try:
                tree_container = self.ui.main_splitter.widget(0)
                editor_tabs = self.ui.main_splitter.widget(1)
                chat_area = self.ui.main_splitter.widget(2)
                config_dock_widget = self.ui.main_splitter.widget(3)

                logger.debug(f"Minimum Widths Before Set (in _apply_initial_splitter_sizes):")
                logger.debug(f"  Tree Container: Hint={tree_container.minimumSizeHint().width()}, Actual={tree_container.minimumWidth()}")
                logger.debug(f"  Editor Tabs:    Hint={editor_tabs.minimumSizeHint().width()}, Actual={editor_tabs.minimumWidth()}")
                logger.debug(f"  Chat Area:      Hint={chat_area.minimumSizeHint().width()}, Actual={chat_area.minimumWidth()}")
                logger.debug(f"  Config Dock:    Hint={config_dock_widget.minimumSizeHint().width()}, Actual={config_dock_widget.minimumWidth()}")

            except Exception as e:
                logger.error(f"Error inspecting minimum widths: {e}")

            logger.info(f"Forcing initial splitter sizes via QTimer: {sizes}") # Changed log level to INFO
            self.ui.main_splitter.setSizes(sizes)

            logger.debug("Calling main_splitter.adjustSize() after setSizes.")
            self.ui.main_splitter.adjustSize()

        else:
            logger.error("Cannot apply initial splitter sizes: main_splitter not found.")

    def _init_handlers(self):
        logger.debug("Initializing handlers...")

        self.chat_handler = ChatActionHandler(core=self.core, chat_input=self.ui.chat_input, send_button=self.ui.send_btn, chat_list_widget=self.ui.chat_list, get_checked_files_callback=self._get_checked_file_paths, parent=self )

        self.workspace_handler = WorkspaceActionHandler(main_window=self, core=self.core, ui=self.ui, actions=self.action_manager, status_bar=self.status_bar_controller, parent=self )

        self.prompt_handler = PromptActionHandler(main_window=self, core=self.core, config_dock=self.ui.config_dock_widget, parent=self )

        self.settings_handler = SettingsActionHandler(main_window=self, core=self.core, open_settings_action=self.action_manager.settings, parent=self )

        # CHANGE THIS: Pass arguments positionally
        self.change_queue_handler = ChangeQueueHandler(
            self.ui.change_queue_widget,      # 1st: widget
            self.core.workspace,              # 2nd: workspace
            self.status_bar_controller,       # 3rd: status_bar
            self                               # 4th: parent
        )

    def _connect_pyqtSignals(self):
        logger.debug("Connecting MainWindow pyqtSignals...")

        self.core.tasks.status_update.connect(self.status_bar_controller.update_status, Qt.ConnectionType.QueuedConnection)
        self.core.tasks.context_info.connect(self.status_bar_controller.update_token_count, Qt.ConnectionType.QueuedConnection)
        self.core.tasks.generation_started.connect(self._disable_ui_for_generation)
        self.core.tasks.generation_finished.connect(self._enable_ui_after_generation)

        self.core.settings.project_path_changed.connect(self._handle_project_path_change)
        self.core.settings.settings_changed.connect(self._handle_setting_change_for_dock)

        self.core.llm.context_limit_changed.connect(self.status_bar_controller.update_token_limit)
        self.core.llm.context_limit_changed.connect(self.ui.config_dock_widget.update_context_limit_display)
        self.core.llm.context_limit_changed.connect(self._check_and_enforce_token_limit)

        self.core.workspace.project_changed.connect(self.core.settings.load_project)

        # Lambdas for simple setting updates are acceptable per the rules
        self.ui.config_dock_widget.provider_changed.connect(lambda p: self.core.settings.set_setting('provider', p))
        self.ui.config_dock_widget.model_changed.connect(lambda m: self.core.settings.set_setting('model', m))
        self.ui.config_dock_widget.llm_params_changed.connect(self._update_llm_params_from_dock)
        self.ui.config_dock_widget.rag_toggle_changed.connect(lambda key, state: self.core.settings.set_setting(key, state))
        self.ui.config_dock_widget.request_model_list_refresh.connect(self._refresh_config_dock_models)

        self.ui.file_tree.itemChanged.connect(self._handle_tree_item_changed_for_status)
        self.ui.file_tree.itemChanged.connect(self.workspace_handler.handle_tree_item_changed)
        self.ui.file_tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        self.ui.tree_select_all_btn.clicked.connect(self._select_all_tree_items)
        self.ui.tree_deselect_all_btn.clicked.connect(self._deselect_all_tree_items)

        self.chat_handler.potential_change_detected.connect(self.change_queue_handler.handle_potential_change)

        logger.debug("MainWindow pyqtSignals connected.")

    def _load_window_state(self):
        logger.debug("Loading window state using QSettings...")

        # Use QSettings - uses OrganizationName and ApplicationName set in launch_app
        qsettings = QSettings()

        geometry_data = qsettings.value("mainWindow/geometry")
        window_state_data = qsettings.value("mainWindow/state")
        splitter_state_data = qsettings.value("mainWindow/mainSplitterState") # Load directly

        if isinstance(geometry_data, QByteArray):
            try:
                if not self.restoreGeometry(geometry_data):
                    logger.warning("Failed to restore window geometry.")

            except Exception as e:
                logger.error(f"Error restoring geometry from QSettings: {e}")

        else:
            logger.debug("No valid window geometry found in QSettings.")

        if isinstance(window_state_data, QByteArray):
            try:
                if not self.restoreState(window_state_data):
                    logger.warning("Failed to restore window state.")

            except Exception as e:
                logger.error(f"Error restoring window state from QSettings: {e}")

        else:
            logger.debug("No valid window state found in QSettings.")

        if self.ui.main_splitter and isinstance(splitter_state_data, QByteArray):
            try:
                if not self.ui.main_splitter.restoreState(splitter_state_data):
                    logger.warning("Failed to restore main splitter state from QSettings.")

                else:
                    logger.debug("Restored main splitter state from QSettings.")

            except Exception as e:
                logger.error(f"Error restoring splitter state from QSettings: {e}")

        elif self.ui.main_splitter:
            logger.debug("No valid splitter state found in QSettings.")

    def _save_window_state(self):
        logger.debug("Saving window state using QSettings...")

        qsettings = QSettings()

        geometry_data = self.saveGeometry()
        window_state_data = self.saveState()

        qsettings.setValue("mainWindow/geometry", geometry_data)
        qsettings.setValue("mainWindow/state", window_state_data)

        if self.ui.main_splitter:
            splitter_state_data = self.ui.main_splitter.saveState()
            qsettings.setValue("mainWindow/mainSplitterState", splitter_state_data)

            logger.debug("Saved main splitter state to QSettings.")

        else:
            logger.debug("Main splitter not found, skipping save state.")

        # Remove the attempts to save to SettingsService
        # self.core.settings.set_setting("main_window_geometry", ...) # REMOVE
        # self.core.settings.set_setting("main_window_state", ...)    # REMOVE
        # self.core.settings.set_setting("main_splitter_state", ...) # REMOVE

        # Optional: Force sync to disk immediately (usually not needed)
        # qsettings.sync()
        logger.debug("Window/Splitter state saved to QSettings.")

    def _apply_initial_settings(self):
        logger.debug("MainWindow: Applying initial theme/font/style via handler...")
        self.settings_handler.apply_initial_settings()

    def _populate_initial_state(self):
        logger.debug("Populating initial state...")

        self.core.workspace.populate_file_tree(self.ui.file_tree)
        self._handle_project_path_change(self.core.workspace.project_path)

        self._update_status_token_display()
        self.chat_handler._update_send_button_state()

        logger.debug("Initial state populated.")

    @pyqtSlot(Path) # Changed decorator
    def _handle_project_path_change(self, path: Path):
        self.setWindowTitle(f"PatchMind IDE - {path.name}")

    @pyqtSlot() # Changed decorator
    def _populate_config_dock_from_settings(self):
        logger.debug("MainWindow: Populating ConfigDock from SettingsService (no refresh)...")
        settings_dict = self.core.settings.get_all_settings()

        self.ui.config_dock_widget.populate_controls(settings_dict)

        self.prompt_handler.update_config_dock_prompts()

        try:
            current_limit = self.core.llm.get_context_limit()
            self.status_bar_controller.update_token_limit(current_limit)

            logger.debug(f"MainWindow: Updated status bar limit post-load: {current_limit}")

            self._update_status_token_display()
            self._check_and_enforce_token_limit()

        except Exception as e:
            logger.error(f"MainWindow: Error updating status bar limit post-load: {e}")

    @pyqtSlot(str, object) # Changed decorator
    def _handle_setting_change_for_dock(self, key: str, value: object):
        relevant_keys = ['provider', 'model', 'temperature', 'top_k', 'prompts', 'selected_prompt_ids']

        is_relevant = key in relevant_keys or key.startswith('rag_')

        if is_relevant:
            logger.info(f"Setting '{key}' changed, repopulating ConfigDock and triggering refresh.")

            self._populate_config_dock_from_settings()
            self._refresh_config_dock_models()

    @pyqtSlot() # Changed decorator
    def _update_llm_params_from_dock(self):
        temp = self.ui.config_dock_widget.temp_spin.value()
        topk = self.ui.config_dock_widget.topk_spin.value()

        self.core.settings.set_setting('temperature', temp)
        self.core.settings.set_setting('top_k', topk)

        logger.debug(f"Updated LLM params: Temp={temp}, TopK={topk}")

    @pyqtSlot() # Changed decorator
    def _refresh_config_dock_models(self):
        logger.debug("MainWindow: Refreshing ConfigDock model list triggered...")

        provider = self.core.settings.get_setting('provider', 'Ollama')
        api_key = None

        if provider.lower() == 'gemini':
            api_key = self.core.settings.get_setting('api_key')

        self.ui.config_dock_widget.update_model_list(["⏳ loading..."], "")

        self.ui.config_dock_widget.model_combo.setEnabled(False)

        self.core.models.refresh_models('llm', provider, api_key)

    @pyqtSlot(list) # Changed decorator
    def _update_config_dock_model_list(self, models: list):
        logger.debug(f"MainWindow: Received model list pyqtSignal with {len(models)} models.")

        current_model_from_settings = self.core.settings.get_setting('model', '')
        final_model_to_select = current_model_from_settings

        if not final_model_to_select and models:
            final_model_to_select = models[0]
            logger.warning(f"No model set, defaulting to first: {final_model_to_select}")

        elif final_model_to_select and models and final_model_to_select not in models:
            logger.warning(f"Current model '{final_model_to_select}' not in list, defaulting to first: {models[0]}")
            final_model_to_select = models[0]

        if self.ui and self.ui.config_dock_widget:
            logger.debug(f"Scheduling ConfigDock model list update via QTimer.")

            # Use lambda to pass arguments to the delayed pyqtSlot
            QTimer.singleShot(0, lambda m=models, s=final_model_to_select: self._perform_dock_model_update(m, s))

        else:
            logger.warning("Attempted model list update, but ConfigDock UI unavailable.")

    @pyqtSlot(list, str) # Changed decorator
    def _perform_dock_model_update(self, models: list, model_to_select: str):
        logger.debug(f"Executing scheduled ConfigDock update. Models: {len(models)}, Select: '{model_to_select}'")

        if self.ui and self.ui.config_dock_widget:
            self.ui.config_dock_widget.update_model_list(models, model_to_select)
            self.ui.config_dock_widget.model_combo.setEnabled(True)

            idx = self.ui.config_dock_widget.model_combo.findText(model_to_select)

            if idx >= 0:
                self.ui.config_dock_widget.model_combo.setCurrentIndex(idx)
                logger.debug(f"Ensured '{model_to_select}' is selected.")

            else:
                logger.warning(f"Could not find '{model_to_select}' in combobox after update.")

        else:
            logger.error("_perform_dock_model_error_update called, but ConfigDock UI missing!")

    @pyqtSlot(str, str) # Changed decorator
    def _handle_config_dock_model_error(self, provider_type: str, error_message: str):
         if provider_type == 'llm':
             logger.error(f"Error loading models for ConfigDock: {error_message}")

         if self.ui and self.ui.config_dock_widget:
             # Use lambda to pass argument to the delayed pyqtSlot
             QTimer.singleShot(0, lambda err=error_message: self._perform_dock_model_error_update(err))

         else:
             logger.warning("Error loading models, but ConfigDock UI unavailable.")

    @pyqtSlot(str) # Changed decorator
    def _perform_dock_model_error_update(self, error_message: str):
        logger.debug("Executing scheduled ConfigDock error update.")

        if self.ui and self.ui.config_dock_widget:
            self.ui.config_dock_widget.update_model_list([], "Error loading")
            self.ui.config_dock_widget.model_combo.setEnabled(False)

        else:
            logger.error("_perform_dock_model_error_update called, but ConfigDock UI missing!")

    @pyqtSlot() # Changed decorator
    def _disable_ui_for_generation(self):
        logger.debug("Disabling UI")

        self.action_manager.settings.setEnabled(False)
        self.ui.config_dock_widget.setEnabled(False)

        self.chat_handler._update_send_button_state()

        # Attempt to disconnect the send button's normal click handler
        try:
            self.ui.send_btn.clicked.disconnect(self.chat_handler.handle_send_button_click)
        except RuntimeError:
            # If disconnect fails, it was likely not connected. Safe to ignore.
            logger.trace("Disconnect failed for send_btn->handle_send_button_click (likely okay).")
            pass

        # Update send button appearance and enable it for stopping
        self.ui.send_btn.setText("Stop")
        self.ui.send_btn.setIcon(qta.icon('fa5s.stop-circle', color='red'))
        self.ui.send_btn.setEnabled(True)

        # Attempt to connect the send button to the stop_generation action
        try:
            self.ui.send_btn.clicked.connect(self.core.tasks.stop_generation)
        except Exception as e:
            # If connecting the stop action fails, log error and disable button
            logger.error(f"Error connecting send_btn to stop_generation: {e}")

            self.ui.send_btn.setEnabled(False)
            self.ui.send_btn.setText("Error")

    @pyqtSlot(bool) # Changed decorator
    def _enable_ui_after_generation(self, stopped_by_user: bool):
        logger.debug(f"Re-enabling UI (Stopped: {stopped_by_user})")

        self.action_manager.settings.setEnabled(True)
        self.ui.config_dock_widget.setEnabled(True)

        # Attempt to disconnect the stop handler
        try:
            self.ui.send_btn.clicked.disconnect(self.core.tasks.stop_generation)
        except RuntimeError:
            logger.trace("Disconnect failed for send_btn->stop_generation (likely okay).")
            pass

        # Restore normal send button appearance
        self.ui.send_btn.setText("Send")
        self.ui.send_btn.setIcon(qta.icon('fa5s.paper-plane', color='white'))

        # Attempt to reconnect the normal send handler
        try:
            self.ui.send_btn.clicked.connect(self.chat_handler.handle_send_button_click)
        except Exception as e:
            # If reconnecting send fails, log error and disable button
            logger.error(f"Error reconnecting send_btn to handle_send_button_click: {e}")

            self.ui.send_btn.setEnabled(False)
            self.ui.send_btn.setText("Error")

        # Update button/input state via handler and set focus
        if self.chat_handler:
            self.chat_handler._update_send_button_state()
            self.ui.chat_input.setFocus()

    @pyqtSlot(QTreeWidgetItem, int) # Changed decorator
    def _handle_tree_item_changed_for_status(self, item: QTreeWidgetItem, column: int):
        if column == 0:
            logger.trace(f"Item changed: {item.text(0)}, state: {item.checkState(0)}")

            self._update_status_token_display()
            self._enforce_limit_timer.start()

    def _get_checked_tokens(self) -> int:
        """Calculates total tokens for all CHECKED FILE items in the tree."""
        total_tokens = 0

        iterator = QTreeWidgetItemIterator(self.ui.file_tree, QTreeWidgetItemIterator.IteratorFlag.All)

        while iterator.value():
            item = iterator.value()

            # Initialize token_count for this item at the start of the loop
            token_count = 0
            item_processed_for_tokens = False # Flag if we got a token count for this item

            is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            is_checked = item.checkState(0) == Qt.CheckState.Checked

            if is_checkable and is_checked:
                path_str = item.data(0, Qt.ItemDataRole.UserRole)

                if path_str:
                    try:
                        # Only process files for token count
                        path = Path(path_str)

                        if path.is_file():
                            token_count_data = item.data(0, TOKEN_COUNT_ROLE)

                            if isinstance(token_count_data, int) and token_count_data >= 0:
                                token_count = token_count_data # Assign valid token count
                                item_processed_for_tokens = True # Mark as processed

                            else:
                                # File item, but invalid token data - log and treat as 0 tokens
                                logger.trace(f"File item {path_str} has invalid token data: {token_count_data}")
                                token_count = 0 # Ensure it's 0
                                item_processed_for_tokens = True # Still counts as processed (as a file)

                        # Add the determined token_count *only if* it was processed (i.e., it was a file)
                        # This implicitly handles directories (token_count remains 0, flag is False)
                        if item_processed_for_tokens:
                            total_tokens += token_count

                    except Exception as e:
                        # Log error but continue iterating other items
                        logger.warning(f"Error checking path/token data for '{path_str}': {e}")
                        # Do not add potentially incorrect token_count from previous iteration

            iterator += 1

        return total_tokens

    def _update_status_token_display(self):
        selected_tokens = self._get_checked_tokens()
        max_tokens = self.core.llm.get_context_limit()

        self.status_bar_controller.update_token_count(selected_tokens, max_tokens)

    @pyqtSlot() # Changed decorator
    def _check_and_enforce_token_limit(self):
        logger.debug("Checking token limit...")

        max_tokens = self.core.llm.get_context_limit()

        if max_tokens <= 0:
            logger.debug("Skipping token enforcement (limit <= 0).")
            self._update_status_token_display()
            return

        cumulative_tokens = 0
        items_deselected = []
        deselection_needed = False

        self.ui.file_tree.blockSignals(True)

        try:
            iterator = QTreeWidgetItemIterator(self.ui.file_tree, QTreeWidgetItemIterator.IteratorFlag.All)

            while iterator.value():
                item = iterator.value()

                is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                is_checked = item.checkState(0) == Qt.CheckState.Checked

                if not is_checkable or not is_checked:
                    iterator += 1
                    continue

                item_tokens = 0
                path_str = item.data(0, Qt.ItemDataRole.UserRole)

                if path_str:
                     try:
                         if Path(path_str).is_file():
                             token_data = item.data(0, TOKEN_COUNT_ROLE)

                             if isinstance(token_data, int) and token_data >= 0:
                                 item_tokens = token_data

                     except Exception as e:
                         logger.warning(f"Error checking path for token limit '{path_str}': {e}")

                if cumulative_tokens + item_tokens > max_tokens:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    items_deselected.append(item.text(0))
                    deselection_needed = True

                    logger.trace(f"Deselected '{item.text(0)}' due to token limit.")

                else:
                    cumulative_tokens += item_tokens

                iterator += 1

        finally:
            self.ui.file_tree.blockSignals(False)

        self._update_status_token_display()

        if deselection_needed:
            warning_msg = (f"Token limit ({max_tokens:,}) exceeded. Auto-deselected {len(items_deselected)} item(s).")

            logger.warning(warning_msg)

            self.status_bar_controller.update_status(warning_msg, 5000)

        logger.debug(f"Token limit check finished. Total after check: {cumulative_tokens}")

    @pyqtSlot() # Changed decorator
    def _select_all_tree_items(self):
        logger.debug("Selecting all checkable tree items.")

        self.ui.file_tree.blockSignals(True)

        try:
            iterator = QTreeWidgetItemIterator(self.ui.file_tree, QTreeWidgetItemIterator.IteratorFlag.All)

            while iterator.value():
                item = iterator.value()

                if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    item.setCheckState(0, Qt.CheckState.Checked)

                iterator += 1

        finally:
            self.ui.file_tree.blockSignals(False)

            self._update_status_token_display()
            self._check_and_enforce_token_limit()

    @pyqtSlot() # Changed decorator
    def _deselect_all_tree_items(self):
        logger.debug("Deselecting all checkable tree items.")

        self.ui.file_tree.blockSignals(True)

        try:
            iterator = QTreeWidgetItemIterator(self.ui.file_tree, QTreeWidgetItemIterator.IteratorFlag.All)

            while iterator.value():
                item = iterator.value()

                if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    item.setCheckState(0, Qt.CheckState.Unchecked)

                iterator += 1

        finally:
            self.ui.file_tree.blockSignals(False)

            self._update_status_token_display()
            # No need to enforce limit after deselecting all

    @pyqtSlot(QPoint) # Changed decorator
    def _show_tree_context_menu(self, pos: QPoint):
        item = self.ui.file_tree.itemAt(pos)

        if not item:
            return

        path_str = item.data(0, Qt.ItemDataRole.UserRole)

        if not path_str:
            return

        path = Path(path_str)
        menu = QMenu(self)

        if path.is_file():
            open_action = menu.addAction(qta.icon('fa5s.folder-open'), "Open")
            # Lambda connection is okay here
            open_action.triggered.connect(lambda: self.workspace_handler.handle_tree_item_activated(item, 0))

        elif path.is_dir():
            expand_action = menu.addAction("Expand/Collapse")
            expand_action.triggered.connect(lambda: item.setExpanded(not item.isExpanded()))

        is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)

        if is_checkable:
            menu.addSeparator()

            check_state = item.checkState(0)

            if check_state == Qt.CheckState.Checked:
                uncheck_action = menu.addAction(qta.icon('fa5s.minus-square'), "Uncheck")
                uncheck_action.triggered.connect(lambda: item.setCheckState(0, Qt.CheckState.Unchecked))

            else:
                check_action = menu.addAction(qta.icon('fa5s.check-square'), "Check")
                check_action.triggered.connect(lambda: item.setCheckState(0, Qt.CheckState.Checked))

            if path.is_dir(): # Actions specific to checkable directories
                menu.addSeparator()

                check_children_action = menu.addAction("Check All Children")
                uncheck_children_action = menu.addAction("Uncheck All Children")

                check_children_action.triggered.connect(lambda: self.workspace_handler._set_child_check_state(item, Qt.CheckState.Checked))
                uncheck_children_action.triggered.connect(lambda: self.workspace_handler._set_child_check_state(item, Qt.CheckState.Unchecked))

        menu.exec(self.ui.file_tree.mapToGlobal(pos))

    def _get_checked_file_paths(self) -> List[Path]:
        checked_paths = []
        iterator = QTreeWidgetItemIterator(self.ui.file_tree)

        while iterator.value():
            item = iterator.value()

            path_str = item.data(0, Qt.ItemDataRole.UserRole)

            if path_str:
                try:
                    path = Path(path_str)

                    is_checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                    is_checked = item.checkState(0) == Qt.CheckState.Checked

                    # Include checked directories as well as files if needed for context
                    if is_checkable and is_checked and (path.is_file() or path.is_dir()):
                         checked_paths.append(path)

                except Exception as e:
                     logger.warning(f"Error processing tree item path '{path_str}': {e}")

            iterator += 1

        return checked_paths

    @pyqtSlot() # Changed decorator
    def show_about_dialog(self):
        # Simplified about text
        about_text = """<h2>PatchMind IDE</h2>
                      <p>AI-enhanced code editor.</p>
                      <p>Version: 0.2.1 (Placeholder)</p>"""

        QMessageBox.about(self, "About PatchMind IDE", about_text)

    @pyqtSlot() # Changed decorator
    def show_log_directory(self):
        try:
            log_url = QUrl.fromLocalFile(str(LOG_PATH.resolve()))

            if not QDesktopServices.openUrl(log_url):
                # Raise error if service fails
                raise RuntimeError("QDesktopServices failed to open URL")

            self.status_bar_controller.update_status(f"Opened log directory: {LOG_PATH}", 3000)

        except Exception as e:
            logger.error(f"Failed open log dir '{LOG_PATH}': {e}")
            QMessageBox.critical(self, "Error", f"Could not open log directory:\n{LOG_PATH}\n\nError: {e}")

    def closeEvent(self, event):
        logger.info("Close triggered.")

        if not self.workspace_handler.close_all_tabs(confirm=True):
            logger.debug("Close ignored by user (cancelled tab closing).")
            event.ignore()
            return

        logger.debug("Requesting Task Manager stop if busy...")

        if self.core.tasks.is_busy():
            self.core.tasks.stop_generation()

            # Use timer to allow stop request to process before continuing close
            QTimer.singleShot(100, lambda ev=event: self._continue_close(ev))

            event.ignore() # Ignore initial close, wait for timer

        else:
             self._continue_close(event) # No tasks running, continue close immediately

    def _continue_close(self, event):
        logger.debug("Saving window state & settings before closing...")

        self._save_window_state()

        if not self.core.settings.save_settings():
            logger.error("Failed to save project settings during close.")
            # Optionally ask user if they want to close anyway?
            # For now, just log the error and proceed.

        logger.info("Accepting close event.")
        event.accept()

# --- End of MainWindow Class ---

def launch_app():
    QApplication.setApplicationName("PatchMind IDE")
    QApplication.setOrganizationName("PatchMind")
    # REMOVED High DPI scaling attributes - Qt6 handles this automatically
    # QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    # QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.exception("Unhandled exception caught by excepthook:")

        try:
            tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
            tb_string = "".join(tb_list)
            logger.error(f"Traceback:\n{tb_string}")

            QMessageBox.critical(None, "Critical Error",
                                 f"An unhandled exception occurred:\n"
                                 f"{exc_type.__name__}: {exc_value}\n\n"
                                 f"Please check the logs for details.\nThe application may need to close.")

        except Exception as mb_error:
            # Failsafe if even the message box errors
            logger.error(f"Failed to display the critical error message box: {mb_error}")

        # Exit might be too abrupt, consider allowing user interaction if possible
        # sys.exit(1)

    sys.excepthook = handle_exception

    # Apply initial theme
    try:
        # Use a temporary AppCore just to read the initial theme setting
        # --- Use parent=None to avoid the parenting TypeError ---
        temp_core = AppCore(parent=None)
        # -------------------------------------------------------

        initial_theme = temp_core.settings.get_setting('theme', 'Dark').lower()

        import qdarktheme

        app.setStyleSheet(qdarktheme.load_stylesheet(initial_theme))

        logger.info(f"Applied initial theme: {initial_theme}")

        del temp_core # Clean up temporary instance

    except Exception as e:
        # Log the specific error applying theme, but don't crash the app launch
        logger.error(f"Failed to apply initial theme: {e}.")

    # Create and show main window
    main_window = MainWindow()
    main_window.show() # <<< Ensure show() is called here >>>

    logger.info("Starting application event loop...")
    sys.exit(app.exec())

# Ensure the script can be run directly if needed (for testing)
# if __name__ == "__main__":
#     launch_app()
