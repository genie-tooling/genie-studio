# pm/handlers/settings_action_handler.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QAction, QFont
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

        # --- Connect pyqtSignals from SettingsService to apply changes immediately ---
        # These apply *global* settings (theme, font, syntax style)
        self._settings_service.theme_changed.connect(self._apply_theme)
        self._settings_service.font_changed.connect(self._apply_font)
        self._settings_service.editor_theme_changed.connect(self._apply_syntax_style)

        logger.info("SettingsActionHandler initialized.")
        # Apply initial theme/font settings (called by MainWindow post-init)

    @pyqtSlot()
    def handle_open_settings(self):
        """Opens the SettingsDialog."""
        logger.debug("SettingsActionHandler: Opening settings dialog...")
        # --- Pass only SettingsService ---
        dialog = SettingsDialog(
            settings_service=self._settings_service,
            parent=self._main_window
        )

        # --- REMOVED Connections to non-existent Dialog pyqtSlots ---
        # The SettingsDialog no longer needs to be updated by the ModelListService
        # dialog.request_llm_refresh.connect(...) # Connection is internal to dialog if needed
        # dialog.request_summarizer_refresh.connect(...) # Connection is internal to dialog if needed
        # self._model_list_service.llm_models_updated.connect(dialog._populate_llm_model_select) # REMOVED
        # self._model_list_service.summarizer_models_updated.connect(dialog._populate_summarizer_model_select) # REMOVED
        # self._model_list_service.model_refresh_error.connect(dialog._handle_refresh_error) # REMOVED
        # --- End REMOVED Connections ---

        if dialog.exec():
            logger.info("SettingsDialog accepted. Settings were saved by the dialog via SettingsService.")
            # SettingsService will emit pyqtSignals for changed settings, triggering updates
        else:
            logger.info("SettingsDialog cancelled. No settings were saved.")

        # --- REMOVED Disconnect calls for non-existent connections ---
        # No need to disconnect pyqtSignals that were never connected to the dialog.
        logger.debug("SettingsActionHandler: Dialog closed.")
        # --- End REMOVED Disconnect ---

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

    # pyqtSlots to apply settings remain largely the same
    @pyqtSlot(str)
    def _apply_theme(self, theme_name: str):
        """Applies the selected UI theme (Dark/Light)."""
        logger.info(f"Applying theme: {theme_name}")
        try:
            stylesheet = qdarktheme.load_stylesheet(theme_name.lower())
            self._main_window.setStyleSheet(stylesheet) # Apply to main window
        except Exception as e:
            logger.error(f"Failed to apply theme '{theme_name}': {e}")

    @pyqtSlot(str, int)
    def _apply_font(self, font_family: str, font_size: int):
        """Applies font changes to relevant widgets via WorkspaceManager."""
        logger.info(f"Applying font: {font_family}, Size: {font_size}")
        self._workspace_manager.apply_font_to_editors(font_family, font_size)

    @pyqtSlot(str)
    def _apply_syntax_style(self, style_name: str):
        """Applies the selected syntax highlighting style via WorkspaceManager."""
        logger.info(f"Applying syntax style: {style_name}")
        self._workspace_manager.apply_syntax_style(style_name)

