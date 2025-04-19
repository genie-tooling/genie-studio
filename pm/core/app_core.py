# pm/core/app_core.py
from PyQt6.QtCore import QObject # Changed import
from pathlib import Path
from loguru import logger
from typing import Optional

from .settings_service import SettingsService
from .llm_service_provider import LLMServiceProvider
from .model_list_service import ModelListService
from .workspace_manager import WorkspaceManager
from .chat_manager import ChatManager
from .task_manager import BackgroundTaskManager
from .model_registry import clear_model_list_cache

class AppCore(QObject):
    """
    Initializes and holds instances of core, non-UI services.
    Acts as a central access point for application logic and state managers.
    """
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        logger.info("Initializing AppCore...")

        clear_model_list_cache()

        # Instantiate core services with parent=None to avoid TypeError during __init__
        self.settings_service = SettingsService(None)

        # Pass settings_service instance, instantiate with parent=None
        self.llm_provider = LLMServiceProvider(self.settings_service, None)

        # Instantiate with parent=None
        self.model_list_service = ModelListService(None)

        initial_path_str = self.settings_service.get_setting('last_project_path', str(Path.cwd()))
        initial_path = Path(initial_path_str)

        if not initial_path.is_dir():
             logger.warning(f"Last project path '{initial_path}' invalid, using CWD.")
             initial_path = Path.cwd()
             self.settings_service.set_setting('last_project_path', str(initial_path))

        # This was already parent=None - KEEP
        self.workspace_manager = WorkspaceManager(initial_path, self.settings_service, parent=None)

        # Instantiate with parent=None
        self.chat_manager = ChatManager(None)

        # Pass settings_service and llm_provider instances, instantiate with parent=None
        self.task_manager = BackgroundTaskManager(self.settings_service, self.llm_provider, None)

        # Load initial project settings (which populates settings_service)
        if not self.settings_service.load_project(initial_path):
             logger.error(f"AppCore: Initial project load failed for {initial_path}.")

        # TaskManager needs references to services after they are created and potentially configured
        # Calling set_services here ensures it gets the instances, regardless of parenting
        self.task_manager.set_services(
            self.llm_provider.get_model_service(),
            self.llm_provider.get_summarizer_service()
        )

        # Connect pyqtSignal to keep TaskManager updated if services change later
        self.llm_provider.services_updated.connect(
            lambda: self.task_manager.set_services(
                self.llm_provider.get_model_service(),
                self.llm_provider.get_summarizer_service()
            )
        )

        logger.info("AppCore initialization complete.")

    # --- Getters remain the same ---
    @property
    def settings(self) -> SettingsService:
        return self.settings_service

    @property
    def llm(self) -> LLMServiceProvider:
        return self.llm_provider

    @property
    def models(self) -> ModelListService:
        return self.model_list_service

    @property
    def workspace(self) -> WorkspaceManager:
        return self.workspace_manager

    @property
    def chat(self) -> ChatManager:
        return self.chat_manager

    @property
    def tasks(self) -> BackgroundTaskManager:
        return self.task_manager
