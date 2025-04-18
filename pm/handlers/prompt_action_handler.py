# pm/handlers/prompt_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMainWindow, QMessageBox # For dialog parent
from loguru import logger
from typing import Optional, List

# --- Updated Imports ---
from ..core.app_core import AppCore
from ..core.settings_service import SettingsService
from ..ui.config_dock import ConfigDock
# from ..ui.prompt_editor_dialog import PromptEditorDialog # Import when created

class PromptActionHandler(QObject):
    """Handles interactions related to prompt management in the ConfigDock."""

    def __init__(self,
                 # --- Dependencies ---
                 main_window: QMainWindow, # Dialog parent
                 core: AppCore,
                 config_dock: ConfigDock, # Direct dependency
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._core = core
        self._settings_service: SettingsService = core.settings
        self._config_dock = config_dock

        # --- Connect Signals from ConfigDock ---
        self._config_dock.request_prompt_new.connect(self.handle_new_prompt)
        self._config_dock.request_prompt_edit.connect(self.handle_edit_prompt)
        self._config_dock.request_prompt_delete.connect(self.handle_delete_prompt)
        self._config_dock.selected_prompts_changed.connect(self.handle_selected_prompts_changed)

        # Connect to SettingsService to update dock when prompts change externally
        # TODO: Add prompts_changed signal to SettingsService if needed
        # self._settings_service.settings_changed.connect(self._handle_settings_change)

        logger.info("PromptActionHandler initialized.")
        # Initial population handled by MainWindow via settings_loaded -> _populate_config_dock

    # TODO: Add slot for settings_changed if dynamic updates are needed
    # @Slot(str, object)
    # def _handle_settings_change(self, key: str, value: object):
    #     if key == 'prompts' or key == 'selected_prompt_ids':
    #          self._update_config_dock_prompts()

    @Slot()
    def handle_new_prompt(self):
        """Handles the request to create a new prompt."""
        logger.debug("New prompt requested.")
        # TODO: Implement PromptEditorDialog
        # dialog = PromptEditorDialog(parent=self._main_window)
        # if dialog.exec():
        #     prompt_data = dialog.get_prompt_data()
        #     if prompt_data:
        #         if self._settings_service.add_prompt(prompt_data): # Assuming add_prompt method exists
        #             logger.info(f"Added new prompt: {prompt_data['name']}")
        #             # SettingsService should emit signal to update dock
        #         else:
        #             QMessageBox.warning(self._main_window, "Error", "Failed to add new prompt.")
        QMessageBox.information(self._main_window, "Not Implemented", "Creating new prompts requires PromptEditorDialog and SettingsService integration.")


    @Slot(str)
    def handle_edit_prompt(self, prompt_id: str):
        """Handles the request to edit an existing prompt."""
        logger.debug(f"Edit prompt requested for ID: {prompt_id}")
        # TODO: Implement PromptEditorDialog & SettingsService methods
        # prompt_data = self._settings_service.get_prompt_by_id(prompt_id) # Assuming method exists
        # if not prompt_data:
        #     QMessageBox.warning(self._main_window, "Error", f"Prompt with ID {prompt_id} not found.")
        #     return
        # dialog = PromptEditorDialog(prompt_data=prompt_data, parent=self._main_window)
        # if dialog.exec():
        #     updated_data = dialog.get_prompt_data()
        #     if updated_data:
        #         if self._settings_service.update_prompt(prompt_id, updated_data): # Assuming method exists
        #             logger.info(f"Updated prompt {prompt_id}: {updated_data['name']}")
        #             # SettingsService should emit signal to update dock
        #         else:
        #             QMessageBox.warning(self._main_window, "Error", "Failed to update prompt.")
        QMessageBox.information(self._main_window, "Not Implemented", "Editing prompts requires PromptEditorDialog and SettingsService integration.")

    @Slot(list)
    def handle_delete_prompt(self, prompt_ids: List[str]):
        """Handles the request to delete prompts."""
        if not prompt_ids: return
        logger.debug(f"Delete prompts requested for IDs: {prompt_ids}")
        # Confirmation should happen in ConfigDock before emitting signal

        # TODO: Implement prompt deletion in SettingsService
        # deleted_count = 0
        # errors = []
        # for prompt_id in prompt_ids:
        #     if self._settings_service.delete_prompt(prompt_id): # Assuming method exists
        #         deleted_count += 1
        #     else:
        #         errors.append(prompt_id)
        # logger.info(f"Deleted {deleted_count} of {len(prompt_ids)} prompts.")
        # if errors:
        #      QMessageBox.warning(self._main_window, "Deletion Issue", f"Could not delete prompts: {', '.join(errors)}")
        # # SettingsService should emit signal to update dock
        QMessageBox.information(self._main_window, "Not Implemented", f"Deleting {len(prompt_ids)} prompts requires SettingsService integration.")


    @Slot(list)
    def handle_selected_prompts_changed(self, selected_ids: List[str]):
        """Handles changes in the active/selected prompt list from ConfigDock."""
        logger.debug(f"Selected prompt IDs updated by ConfigDock: {selected_ids}")
        # Update the setting via SettingsService
        # Use a specific key for the ordered list of active prompt IDs
        self._settings_service.set_setting('selected_prompt_ids', selected_ids)
        # SettingsService emits settings_changed signal automatically


    # This method is called by MainWindow when settings are reloaded
    @Slot()
    def update_config_dock_prompts(self):
        """Refreshes the prompt lists in ConfigDock based on SettingsService."""
        logger.debug("PromptActionHandler: Updating ConfigDock prompt lists...")
        all_prompts = self._settings_service.get_setting('prompts', []) # Get from settings
        selected_ids = self._settings_service.get_setting('selected_prompt_ids', [])
        self._config_dock.populate_available_prompts(all_prompts)
        self._config_dock.populate_selected_prompts(selected_ids, all_prompts)

