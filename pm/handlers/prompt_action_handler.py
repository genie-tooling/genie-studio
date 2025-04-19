# pm/handlers/prompt_action_handler.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer # Added QTimer
from PyQt6.QtWidgets import QMainWindow, QMessageBox # For dialog parent
from loguru import logger
from typing import Optional, List, Dict # Added Dict

# --- Updated Imports ---
from ..core.app_core import AppCore
from ..core.settings_service import SettingsService
from ..ui.config_dock import ConfigDock
from ..ui.prompt_editor_dialog import PromptEditorDialog # Import the new dialog

class PromptActionHandler(QObject):
    """Handles interactions related to prompt management in the ConfigDock."""

    def __init__(self,
                 main_window: QMainWindow,
                 core: AppCore,
                 config_dock: ConfigDock,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._core = core
        self._settings_service: SettingsService = core.settings
        self._config_dock = config_dock

        # Connect pyqtSignals from ConfigDock
        self._config_dock.request_prompt_new.connect(self.handle_new_prompt)
        self._config_dock.request_prompt_edit.connect(self.handle_edit_prompt)
        self._config_dock.request_prompt_delete.connect(self.handle_delete_prompt)
        self._config_dock.selected_prompts_changed.connect(self.handle_selected_prompts_changed)

        # Connect to SettingsService to update dock when prompts change
        # This connection is crucial for the UI to update after changes
        self._settings_service.prompts_changed.connect(self.update_config_dock_prompts)

        logger.info("PromptActionHandler initialized.")
        # --- ADDED: Deferred initial population ---
        # MainWindow._populate_config_dock_from_settings *should* call this,
        # but adding a deferred call here provides robustness against timing issues.
        # Use a zero timer to run it after the current event processing finishes.
        QTimer.singleShot(0, self.update_config_dock_prompts)
        logger.debug("Scheduled initial prompt list population.")
        # -----------------------------------------

    @pyqtSlot()
    def handle_new_prompt(self):
        """Handles the request to create a new prompt."""
        logger.debug("New prompt requested.")
        dialog = PromptEditorDialog(parent=self._main_window)
        if dialog.exec():
            prompt_data = dialog.get_prompt_data()
            if prompt_data:
                # SettingsService.add_prompt now handles validation and pyqtSignal emission
                if self._settings_service.add_prompt(prompt_data):
                    logger.info(f"Added new prompt: {prompt_data['name']}")
                    # prompts_changed pyqtSignal handled by update_config_dock_prompts
                else:
                    QMessageBox.warning(self._main_window, "Error", "Failed to add new prompt (check logs).")

    @pyqtSlot(str)
    def handle_edit_prompt(self, prompt_id: str):
        """Handles the request to edit an existing prompt."""
        logger.debug(f"Edit prompt requested for ID: {prompt_id}")
        prompt_data = self._settings_service.get_prompt_by_id(prompt_id) # Use service method
        if not prompt_data:
            QMessageBox.warning(self._main_window, "Error", f"Prompt with ID {prompt_id} not found.")
            return

        dialog = PromptEditorDialog(prompt_data=prompt_data, parent=self._main_window)
        if dialog.exec():
            updated_data = dialog.get_prompt_data()
            if updated_data:
                # SettingsService.update_prompt now handles validation and pyqtSignal emission
                if self._settings_service.update_prompt(prompt_id, updated_data):
                    logger.info(f"Updated prompt {prompt_id}: {updated_data['name']}")
                    # prompts_changed pyqtSignal handled by update_config_dock_prompts
                else:
                    QMessageBox.warning(self._main_window, "Error", "Failed to update prompt (check logs).")

    @pyqtSlot(list)
    def handle_delete_prompt(self, prompt_ids: List[str]):
        """Handles the request to delete prompts."""
        if not prompt_ids:
            return
        logger.debug(f"Delete prompts requested for IDs: {prompt_ids}")
        # Confirmation should happen in ConfigDock before emitting pyqtSignal

        deleted_count = 0; errors = []
        # --- Ensure prompt names are fetched BEFORE potential deletion ---
        error_names_map = {}
        for prompt_id in prompt_ids:
             prompt = self._settings_service.get_prompt_by_id(prompt_id)
             error_names_map[prompt_id] = prompt.get('name', prompt_id) if prompt else prompt_id
        # --- End pre-fetch ---

        for prompt_id in prompt_ids:
            # SettingsService.delete_prompt now handles validation and pyqtSignal emission
            if self._settings_service.delete_prompt(prompt_id):
                deleted_count += 1
            else:
                errors.append(prompt_id) # Should ideally get name here

        logger.info(f"Deleted {deleted_count} of {len(prompt_ids)} prompts.")
        if errors:
             # Use the pre-fetched names for error reporting
             error_display_names = [error_names_map.get(pid, pid) for pid in errors]
             QMessageBox.warning(self._main_window, "Deletion Issue", f"Could not delete prompts: {', '.join(error_display_names)}")
        # prompts_changed pyqtSignal handled by update_config_dock_prompts

    @pyqtSlot(list)
    def handle_selected_prompts_changed(self, selected_ids: List[str]):
        """Handles changes in the active/selected prompt list from ConfigDock."""
        logger.debug(f"Selected prompt IDs updated by ConfigDock: {selected_ids}")
        # Update the setting via SettingsService
        # This will trigger settings_changed -> llm_config_changed automatically if needed
        self._settings_service.set_setting('selected_prompt_ids', selected_ids)

    @pyqtSlot() # Connects to SettingsService.prompts_changed
    @pyqtSlot(list) # Also allow direct call with list
    def update_config_dock_prompts(self, updated_prompts_list: Optional[List[Dict]] = None):
        """Refreshes the prompt lists in ConfigDock based on SettingsService."""
        # --- ADDED Safeguard ---
        if not self._config_dock or not self._settings_service:
            logger.warning("PromptActionHandler: Attempted to update ConfigDock prompts, but dock or service is missing.")
            return
        # -----------------------

        logger.debug("PromptActionHandler: Updating ConfigDock prompt lists...")
        # Use the provided list if given, otherwise fetch from service
        all_prompts = updated_prompts_list if updated_prompts_list is not None else self._settings_service.get_user_prompts()
        selected_ids = self._settings_service.get_setting('selected_prompt_ids', [])

        # Ensure ConfigDock methods are called to update both lists
        # Check if the methods exist before calling, just in case
        if hasattr(self._config_dock, 'populate_available_prompts'):
             self._config_dock.populate_available_prompts(all_prompts)
        else:
             logger.error("ConfigDock missing populate_available_prompts method!")

        if hasattr(self._config_dock, 'populate_selected_prompts'):
             self._config_dock.populate_selected_prompts(selected_ids, all_prompts)
        else:
             logger.error("ConfigDock missing populate_selected_prompts method!")

        logger.debug("PromptActionHandler: ConfigDock prompt lists update complete.")
