# pm/handlers/settings_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QAction, QFont
from loguru import logger
from typing import Optional
import qdarktheme # For applying theme

# --- Updated Imports ---
from ..core.app_core import AppCore
from ..core.settings_service import SettingsService
from ..core.model_list_service import ModelListService
from ..core.workspace_manager import WorkspaceManager
from ..ui.settings_dialog import SettingsDialog

class SettingsActionHandler(QObject):
    """Handles opening the settings dialog and applying global settings changes."""

    def __init__(self,
                 # --- Dependencies ---
                 main_window: QMainWindow, # Dialog parent
                 core: AppCore,
                 open_settings_action: QAction, # Passed from ActionManager
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._main_window = main_window
        self._core = core

        # --- Get managers/services ---
        self._settings_service: SettingsService = core.settings
        self._model_list_service: ModelListService = core.models
        self._workspace_manager: WorkspaceManager = core.workspace

        # --- Connect the menu action trigger ---
        open_settings_action.triggered.connect(self.handle_open_settings)

        # --- Connect signals from SettingsService to apply changes immediately ---
        # These apply *global* settings (theme, font, syntax style)
        self._settings_service.theme_changed.connect(self._apply_theme)
        self._settings_service.font_changed.connect(self._apply_font)
        self._settings_service.syntax_style_changed.connect(self._apply_syntax_style)

        logger.info("SettingsActionHandler initialized.")
        # Apply initial theme/font settings (could be moved to MainWindow post-init)
        # self._apply_initial_settings() # Moved to MainWindow._apply_initial_settings

    @Slot()
    def handle_open_settings(self):
        """Opens the SettingsDialog and connects necessary signals for its duration."""
        logger.debug("SettingsActionHandler: Opening settings dialog...")
        # --- Pass only SettingsService ---
        dialog = SettingsDialog(
            settings_service=self._settings_service,
            parent=self._main_window
        )

        # --- Connect signals between Dialog and ModelListService ---
        # *** Use lambdas to insert the correct provider_type ***
        dialog.request_llm_refresh.connect(
            lambda provider, api_key: self._model_list_service.refresh_models('llm', provider, api_key)
        )
        dialog.request_summarizer_refresh.connect(
            lambda provider, api_key: self._model_list_service.refresh_models('summarizer', provider, api_key)
        )
        # **********************************************************

        # Connect ModelListService signals back to *temporary* dialog slots if dialog needs updates
        # NOTE: SettingsDialog _populate_* slots are currently empty. Connections are harmless but redundant.
        self._model_list_service.llm_models_updated.connect(dialog._populate_llm_model_select)
        self._model_list_service.summarizer_models_updated.connect(dialog._populate_summarizer_model_select)
        self._model_list_service.model_refresh_error.connect(dialog._handle_refresh_error)
        # --- End Dialog/Service Connections ---

        if dialog.exec():
            logger.info("SettingsDialog accepted. Settings were saved by the dialog via SettingsService.")
            # SettingsService will emit signals for changed settings, triggering updates
        else:
            logger.info("SettingsDialog cancelled. No settings were saved.")

        # --- Disconnect signals after dialog closes ---
        try:
            # Disconnect using the same lambda pattern or by reference if possible (less reliable with lambdas)
            # Trying disconnection by reference first, might fail silently for lambdas.
            # A more robust way involves storing the lambda connection results, but let's try this first.
            dialog.request_llm_refresh.disconnect()
            dialog.request_summarizer_refresh.disconnect()
            self._model_list_service.llm_models_updated.disconnect(dialog._populate_llm_model_select)
            self._model_list_service.summarizer_models_updated.disconnect(dialog._populate_summarizer_model_select)
            self._model_list_service.model_refresh_error.disconnect(dialog._handle_refresh_error)
            logger.debug("SettingsActionHandler: Disconnected dialog signals (attempted).")
        except RuntimeError as e:
            # This might catch errors if the connection (e.g., lambda) doesn't exist or was already gone.
            logger.warning(f"SettingsActionHandler: Error disconnecting dialog signals: {e}")
        except Exception as e:
             logger.exception(f"SettingsActionHandler: Unexpected error disconnecting signals: {e}")
        # --- End Disconnect ---

    # This method can be called by MainWindow after initialization
    def apply_initial_settings(self):
        """Applies theme and font settings when the application starts."""
        logger.debug("SettingsActionHandler: Applying initial theme, font, style...")
        self._apply_theme(self._settings_service.get_setting('theme', 'Dark'))
        self._apply_font(
            self._settings_service.get_setting('editor_font', 'Fira Code'),
            self._settings_service.get_setting('editor_font_size', 11)
        )
        self._apply_syntax_style(self._settings_service.get_setting('syntax_highlighting_style'))

    # Slots to apply settings remain largely the same
    @Slot(str)
    def _apply_theme(self, theme_name: str):
        """Applies the selected UI theme (Dark/Light)."""
        logger.info(f"Applying theme: {theme_name}")
        try:
            stylesheet = qdarktheme.load_stylesheet(theme_name.lower())
            self._main_window.setStyleSheet(stylesheet) # Apply to main window
            # Potentially re-apply to dialogs if they don't inherit? Usually they do.
        except Exception as e:
            logger.error(f"Failed to apply theme '{theme_name}': {e}")

    @Slot(str, int)
    def _apply_font(self, font_family: str, font_size: int):
        """Applies font changes to relevant widgets via WorkspaceManager."""
        logger.info(f"Applying font: {font_family}, Size: {font_size}")
        self._workspace_manager.apply_font_to_editors(font_family, font_size)

    @Slot(str)
    def _apply_syntax_style(self, style_name: str):
        """Applies the selected syntax highlighting style via WorkspaceManager."""
        logger.info(f"Applying syntax style: {style_name}")
        self._workspace_manager.apply_syntax_style(style_name)

