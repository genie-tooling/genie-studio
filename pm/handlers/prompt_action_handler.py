# pm/handlers/prompt_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMainWindow, QMessageBox # For dialogs
from loguru import logger
from typing import Optional, List

from ..core.settings_service import SettingsService
from ..ui.config_dock import ConfigDock
# from ..ui.prompt_editor_dialog import PromptEditorDialog # Import when created

class PromptActionHandler(QObject):
    """Handles interactions related to prompt management in the ConfigDock."""

    def __init__(self,
                 main_window: QMainWindow, # For showing dialogs
                 settings_service: SettingsService,
                 config_dock: ConfigDock, # To connect signals from
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._settings_service = settings_service
        self._config_dock = config_dock

        # --- Connect Signals from ConfigDock ---
        self._config_dock.request_prompt_new.connect(self.handle_new_prompt)
        self._config_dock.request_prompt_edit.connect(self.handle_edit_prompt)
        self._config_dock.request_prompt_delete.connect(self.handle_delete_prompt)
        self._config_dock.selected_prompts_changed.connect(self.handle_selected_prompts_changed)

        # Connect to SettingsService to update dock when prompts change externally
        # self._settings_service.prompts_changed.connect(self._update_config_dock_prompts) # Add this signal later

        logger.info("PromptActionHandler initialized.")
        # Initial population (should be handled by MainWindow logic that loads settings)
        # self._update_config_dock_prompts()

    @Slot()
    def handle_new_prompt(self):
        """Handles the request to create a new prompt."""
        logger.debug("New prompt requested.")
        # TODO: Implement PromptEditorDialog
        # dialog = PromptEditorDialog(parent=self._main_window)
        # if dialog.exec():
        #     prompt_data = dialog.get_prompt_data()
        #     if prompt_data:
        #         # Add prompt via SettingsService
        #         # self._settings_service.add_prompt(prompt_data)
        #         logger.info(f"TODO: Add new prompt: {prompt_data['name']}")
        #         QMessageBox.information(self._main_window, "Not Implemented", "Adding new prompts is not fully implemented yet.")
        QMessageBox.information(self._main_window, "Not Implemented", "Creating new prompts requires PromptEditorDialog.")


    @Slot(str)
    def handle_edit_prompt(self, prompt_id: str):
        """Handles the request to edit an existing prompt."""
        logger.debug(f"Edit prompt requested for ID: {prompt_id}")
        # TODO: Implement PromptEditorDialog
        # prompt_data = self._settings_service.get_prompt_by_id(prompt_id)
        # if not prompt_data:
        #     QMessageBox.warning(self._main_window, "Error", f"Prompt with ID {prompt_id} not found.")
        #     return
        # dialog = PromptEditorDialog(prompt_data=prompt_data, parent=self._main_window)
        # if dialog.exec():
        #     updated_data = dialog.get_prompt_data()
        #     if updated_data:
        #         # Update prompt via SettingsService
        #         # self._settings_service.update_prompt(prompt_id, updated_data)
        #         logger.info(f"TODO: Update prompt {prompt_id}: {updated_data['name']}")
        #         QMessageBox.information(self._main_window, "Not Implemented", "Editing prompts is not fully implemented yet.")
        QMessageBox.information(self._main_window, "Not Implemented", "Editing prompts requires PromptEditorDialog.")

    @Slot(list)
    def handle_delete_prompt(self, prompt_ids: List[str]):
        """Handles the request to delete prompts."""
        if not prompt_ids: return
        logger.debug(f"Delete prompts requested for IDs: {prompt_ids}")
        # Confirmation should happen in ConfigDock before emitting signal

        # TODO: Implement prompt deletion in SettingsService
        # deleted_count = 0
        # for prompt_id in prompt_ids:
        #     if self._settings_service.delete_prompt(prompt_id):
        #         deleted_count += 1
        # logger.info(f"TODO: Deleted {deleted_count} of {len(prompt_ids)} requested prompts.")
        # if deleted_count < len(prompt_ids):
        #      QMessageBox.warning(self._main_window, "Deletion Issue", f"Could not delete {len(prompt_ids) - deleted_count} prompts.")
        QMessageBox.information(self._main_window, "Not Implemented", f"Deleting {len(prompt_ids)} prompts is not fully implemented yet.")


    @Slot(list)
    def handle_selected_prompts_changed(self, selected_ids: List[str]):
        """Handles changes in the active/selected prompt list from ConfigDock."""
        logger.debug(f"Selected prompt IDs updated by ConfigDock: {selected_ids}")
        # Update the setting via SettingsService
        # Use a specific key for the ordered list of active prompt IDs
        self._settings_service.set_setting('selected_prompt_ids', selected_ids)
        logger.info(f"Set selected_prompt_ids in settings: {selected_ids}")


    # TODO: Slot connected to SettingsService signal when prompts definition changes
    # @Slot()
    # def _update_config_dock_prompts(self):
    #     """Refreshes the prompt lists in ConfigDock based on SettingsService."""
    #     logger.debug("Updating ConfigDock prompt lists from SettingsService...")
    #     all_prompts = self._settings_service.get_all_prompts() # Need method in SettingsService
    #     selected_ids = self._settings_service.get_setting('selected_prompt_ids', [])
    #     self._config_dock.populate_available_prompts(all_prompts)
    #     self._config_dock.populate_selected_prompts(selected_ids, all_prompts)

