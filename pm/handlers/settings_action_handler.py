# pm/handlers/settings_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QAction, QFont
from loguru import logger
from typing import Optional
import qdarktheme # For applying theme

from ..core.settings_service import SettingsService
# --- Import ModelListService HERE ---
from ..core.model_list_service import ModelListService
# --- End ---
from ..core.workspace_manager import WorkspaceManager
from ..ui.settings_dialog import SettingsDialog

class SettingsActionHandler(QObject):
    """Handles opening the settings dialog and applying settings changes."""

    def __init__(self,
                 main_window: QMainWindow,
                 settings_service: SettingsService,
                 model_list_service: ModelListService, # Keep service instance
                 workspace_manager: WorkspaceManager,
                 open_settings_action: QAction,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._settings_service = settings_service
        self._model_list_service = model_list_service # Store service instance
        self._workspace_manager = workspace_manager

        # Connect the menu action trigger
        open_settings_action.triggered.connect(self.handle_open_settings)

        # Connect signals from SettingsService to apply changes immediately
        self._settings_service.theme_changed.connect(self._apply_theme)
        self._settings_service.font_changed.connect(self._apply_font)
        self._settings_service.syntax_style_changed.connect(self._apply_syntax_style)

        logger.info("SettingsActionHandler initialized.")
        # Apply initial theme/font settings
        self._apply_initial_settings()


    @Slot()
    def handle_open_settings(self):
        """Opens the SettingsDialog and connects refresh signals."""
        logger.debug("SettingsActionHandler: Opening settings dialog...")
        # --- Pass only SettingsService ---
        dialog = SettingsDialog(
            settings_service=self._settings_service,
            # model_list_service=self._model_list_service, # REMOVED
            parent=self._main_window
        )
        # --- END ---

        # --- Connect signals FROM dialog TO ModelListService ---
        # Use lambda to adapt dialog signal args to service slot args
        dialog.request_llm_refresh.connect(
            lambda provider, api_key: self._model_list_service.refresh_models('llm', provider, api_key)
        )
        dialog.request_summarizer_refresh.connect(
            lambda provider, api_key: self._model_list_service.refresh_models('summarizer', provider, api_key)
        )
        # --- Connect signals FROM ModelListService TO dialog slots ---
        self._model_list_service.llm_models_updated.connect(dialog._populate_llm_model_select)
        self._model_list_service.summarizer_models_updated.connect(dialog._populate_summarizer_model_select)
        self._model_list_service.model_refresh_error.connect(dialog._handle_refresh_error)
        # --- End ---

        if dialog.exec():
            logger.info("SettingsDialog accepted. Settings were saved by the dialog via SettingsService.")
        else:
            logger.info("SettingsDialog cancelled. No settings were saved.")

        # --- Disconnect signals after dialog closes to prevent leaks ---
        try:
            dialog.request_llm_refresh.disconnect()
            dialog.request_summarizer_refresh.disconnect()
            self._model_list_service.llm_models_updated.disconnect(dialog._populate_llm_model_select)
            self._model_list_service.summarizer_models_updated.disconnect(dialog._populate_summarizer_model_select)
            self._model_list_service.model_refresh_error.disconnect(dialog._handle_refresh_error)
            logger.debug("SettingsActionHandler: Disconnected dialog signals.")
        except RuntimeError as e:
             logger.warning(f"SettingsActionHandler: Error disconnecting dialog signals: {e}")
        except Exception as e:
             logger.exception(f"SettingsActionHandler: Unexpected error disconnecting signals: {e}")
        # --- End Disconnect ---


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
        except Exception as e:
            logger.error(f"Failed to apply theme '{theme_name}': {e}")

    @Slot(str, int)
    def _apply_font(self, font_family: str, font_size: int):
        """Applies font changes to relevant widgets (e.g., open editors)."""
        logger.info(f"Applying font: {font_family}, Size: {font_size}")
        # Delegate to workspace manager
        self._workspace_manager.apply_font_to_editors(font_family, font_size)

    @Slot(str)
    def _apply_syntax_style(self, style_name: str):
        """Applies the selected syntax highlighting style to open editors."""
        logger.info(f"Applying syntax style: {style_name}")
        self._workspace_manager.apply_syntax_style(style_name)