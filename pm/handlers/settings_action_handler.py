# pm/handlers/settings_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QAction, QFont
from loguru import logger
from typing import Optional
import qdarktheme # For applying theme

from ..core.settings_service import SettingsService
from ..core.model_list_service import ModelListService
from ..core.workspace_manager import WorkspaceManager
from ..ui.settings_dialog import SettingsDialog

class SettingsActionHandler(QObject):
    """Handles opening the settings dialog and applying settings changes."""

    def __init__(self,
                 main_window: QMainWindow,
                 settings_service: SettingsService,
                 model_list_service: ModelListService,
                 workspace_manager: WorkspaceManager, # To apply style/font changes
                 open_settings_action: QAction,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._settings_service = settings_service
        self._model_list_service = model_list_service
        self._workspace_manager = workspace_manager

        # Connect the menu action trigger
        open_settings_action.triggered.connect(self.handle_open_settings)

        # Connect signals from SettingsService to apply changes immediately (optional)
        # Or apply changes only after dialog is accepted (_handle_settings_accepted)
        self._settings_service.theme_changed.connect(self._apply_theme)
        self._settings_service.font_changed.connect(self._apply_font)
        self._settings_service.syntax_style_changed.connect(self._apply_syntax_style)

        logger.info("SettingsActionHandler initialized.")
        # Apply initial theme/font settings
        self._apply_initial_settings()


    @Slot()
    def handle_open_settings(self):
        """Opens the SettingsDialog."""
        logger.debug("SettingsActionHandler: Opening settings dialog...")
        # Pass the required services to the dialog
        dialog = SettingsDialog(
            settings_service=self._settings_service,
            model_list_service=self._model_list_service,
            parent=self._main_window
        )
        # No need to pass settings dict copy anymore

        if dialog.exec(): # QDialog::Accepted is returned if Ok clicked and dialog.accept() called
            logger.info("SettingsDialog accepted. Settings were saved by the dialog via SettingsService.")
            # Settings are saved *within* the dialog's accept() method via SettingsService.
            # The service emits signals for changes, which relevant components should listen to.
            # We might manually trigger some updates here if needed, but signal/slot is preferred.
            # Example: Force workspace style update if syntax style might have changed.
            # self._apply_syntax_style(self._settings_service.get_setting('syntax_highlighting_style'))
        else:
            logger.info("SettingsDialog cancelled. No settings were saved.")
            # No action needed, SettingsService state remains unchanged.

    def _apply_initial_settings(self):
        """Applies theme and font settings when the application starts."""
        logger.debug("Applying initial theme and font settings...")
        self._apply_theme(self._settings_service.get_setting('theme', 'Dark'))
        self._apply_font(
            self._settings_service.get_setting('editor_font', 'Fira Code'),
            self._settings_service.get_setting('editor_font_size', 11)
        )
        self._apply_syntax_style(self._settings_service.get_setting('syntax_highlighting_style'))


    @Slot(str)
    def _apply_theme(self, theme_name: str):
        """Applies the selected UI theme (Dark/Light)."""
        logger.info(f"Applying theme: {theme_name}")
        try:
            stylesheet = qdarktheme.load_stylesheet(theme_name.lower())
            self._main_window.setStyleSheet(stylesheet)
            # You might need to force style updates on some widgets if they don't inherit automatically
            # e.g., self._main_window.update() or QApplication.processEvents()
        except Exception as e:
            logger.error(f"Failed to apply theme '{theme_name}': {e}")

    @Slot(str, int)
    def _apply_font(self, font_family: str, font_size: int):
        """Applies font changes to relevant widgets (e.g., open editors)."""
        logger.info(f"Applying font: {font_family}, Size: {font_size}")
        # WorkspaceManager should handle applying font to its editors
        # We might need to pass the font info to it or have it listen to settings changes.
        # For now, assume WorkspaceManager handles this internally based on settings changes.
        # Example direct call (if WorkspaceManager needs it):
        # self._workspace_manager.apply_font_to_editors(font_family, font_size)
        pass # TODO: Ensure WorkspaceManager updates open editor fonts

    @Slot(str)
    def _apply_syntax_style(self, style_name: str):
        """Applies the selected syntax highlighting style to open editors."""
        logger.info(f"Applying syntax style: {style_name}")
        self._workspace_manager.apply_syntax_style(style_name)

