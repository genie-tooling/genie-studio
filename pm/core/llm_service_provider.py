# pm/core/llm_service_provider.py
from PySide6.QtCore import QObject, Signal, Slot
from loguru import logger
from typing import Optional, Any

from .settings_service import SettingsService
from .ollama_service import OllamaService
from .gemini_service import GeminiService
from .model_registry import resolve_context_limit, list_ollama_models, list_gemini_models

class LLMServiceProvider(QObject):
    """
    Manages the instantiation and switching of LLM service clients (Ollama, Gemini)
    based on settings provided by SettingsService.
    """
    services_updated = Signal() # Emitted when model or summarizer service instances change
    context_limit_changed = Signal(int) # Emitted when the main model's context limit changes

    def __init__(self, settings_service: SettingsService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._settings_service = settings_service
        self._model_service: Optional[OllamaService | GeminiService] = None
        self._summarizer_service: Optional[OllamaService | GeminiService] = None

        # Connect to relevant settings changes
        self._settings_service.llm_config_changed.connect(self._update_services)
        self._settings_service.rag_config_changed.connect(self._update_services) # RAG config might change summarizer

        # Initial service creation
        self._update_services()
        logger.info("LLMServiceProvider initialized.")

    @Slot()
    def _update_services(self):
        """
        Reads current settings and creates/updates the appropriate service instances.
        """
        logger.info("LLMServiceProvider: Updating services based on settings...")
        services_changed = False
        old_model_ctx = self.get_context_limit()

        # --- Update Main Model Service ---
        provider = self._settings_service.get_setting('provider', 'Ollama').lower()
        model_name = self._settings_service.get_setting('model', '')
        api_key = self._settings_service.get_setting('api_key', '')
        temp = self._settings_service.get_setting('temperature', 0.3)
        top_k = self._settings_service.get_setting('top_k', 40)

        new_model_service = None
        if provider == 'ollama' and model_name:
            try:
                # Check if Ollama model exists before creating service
                # This prevents errors if the user configures a non-existent model
                available_ollama = list_ollama_models() # Uses cached list
                if model_name in available_ollama:
                    new_model_service = OllamaService(model=model_name)
                else:
                    logger.error(f"Configured Ollama model '{model_name}' not found. Cannot create service.")
                    # Optionally: Try to select the first available Ollama model?
                    # if available_ollama:
                    #     logger.warning(f"Falling back to first available Ollama model: {available_ollama[0]}")
                    #     self._settings_service.set_setting('model', available_ollama[0]) # This triggers another update cycle
                    #     return # Exit early, let the next update handle it

            except Exception as e:
                logger.exception(f"Failed to initialize OllamaService for model '{model_name}': {e}")
        elif provider == 'gemini' and model_name and api_key:
            try:
                # Potentially check Gemini model availability here too if needed
                new_model_service = GeminiService(model=model_name, api_key=api_key, temp=temp, top_k=top_k)
            except Exception as e:
                logger.exception(f"Failed to initialize GeminiService for model '{model_name}': {e}")
        elif provider == 'gemini' and not api_key:
             logger.warning("Gemini provider selected but API key is missing.")
        elif not model_name:
            logger.warning(f"{provider.capitalize()} provider selected but model name is empty.")

        # Update only if the type or key parameters changed significantly
        # Note: Simple comparison `!=` might not work well if objects don't implement `__eq__` meaningfully
        # For now, we replace if a new service could be created
        if new_model_service is not None or self._model_service is not None: # Check if there was or is a service
             # Rough check: Replace if provider/model changed or if one exists and the other doesn't
             current_type = type(self._model_service).__name__ if self._model_service else None
             new_type = type(new_model_service).__name__ if new_model_service else None
             current_model = getattr(self._model_service, 'model', None) if self._model_service else None

             if new_type != current_type or getattr(new_model_service, 'model', None) != current_model:
                 logger.info(f"Switching main model service from {current_type}({current_model}) to {new_type}({getattr(new_model_service, 'model', None)})")
                 self._model_service = new_model_service
                 services_changed = True
             # Maybe update params like temp/topk if service type is the same?

        # --- Update Summarizer Service ---
        summ_enabled = self._settings_service.get_setting('rag_summarizer_enabled', True)
        summ_provider = self._settings_service.get_setting('rag_summarizer_provider', 'Ollama').lower()
        summ_model = self._settings_service.get_setting('rag_summarizer_model_name', '')
        # Summarizer typically doesn't need API key separate from main (Gemini uses same config, Ollama needs none)

        new_summarizer_service = None
        if summ_enabled:
            if summ_provider == 'ollama' and summ_model:
                try:
                    available_ollama = list_ollama_models() # Cached
                    if summ_model in available_ollama:
                         new_summarizer_service = OllamaService(model=summ_model)
                    else:
                         logger.error(f"Configured Summarizer Ollama model '{summ_model}' not found.")
                except Exception as e:
                    logger.exception(f"Failed to initialize Summarizer OllamaService for model '{summ_model}': {e}")
            elif summ_provider == 'gemini' and summ_model and api_key: # Check main API key for Gemini
                 try:
                      # Assume temp/topk don't apply or use defaults for summarizer
                      new_summarizer_service = GeminiService(model=summ_model, api_key=api_key)
                 except Exception as e:
                      logger.exception(f"Failed to initialize Summarizer GeminiService for model '{summ_model}': {e}")
            elif summ_provider == 'gemini' and not api_key:
                 logger.warning("Summarizer uses Gemini provider but main API key is missing.")
            elif not summ_model:
                 logger.warning(f"Summarizer provider {summ_provider.capitalize()} selected but model name is empty.")

        # Update Summarizer Service
        # Similar check as above
        current_summ_type = type(self._summarizer_service).__name__ if self._summarizer_service else None
        new_summ_type = type(new_summarizer_service).__name__ if new_summarizer_service else None
        current_summ_model = getattr(self._summarizer_service, 'model', None) if self._summarizer_service else None

        if new_summ_type != current_summ_type or getattr(new_summarizer_service, 'model', None) != current_summ_model:
             logger.info(f"Switching summarizer service from {current_summ_type}({current_summ_model}) to {new_summ_type}({getattr(new_summarizer_service, 'model', None)})")
             self._summarizer_service = new_summarizer_service
             services_changed = True
        elif not summ_enabled and self._summarizer_service is not None:
             logger.info("Disabling summarizer service.")
             self._summarizer_service = None # Explicitly disable
             services_changed = True


        if services_changed:
            self.services_updated.emit()

        # Check and emit context limit change for the main model
        new_model_ctx = self.get_context_limit()
        if new_model_ctx != old_model_ctx:
             self.context_limit_changed.emit(new_model_ctx)


    def get_model_service(self) -> Optional[OllamaService | GeminiService]:
        """Returns the current main LLM service instance."""
        return self._model_service

    def get_summarizer_service(self) -> Optional[OllamaService | GeminiService]:
        """Returns the current summarizer LLM service instance (if enabled)."""
        return self._summarizer_service

    def get_context_limit(self) -> int:
        """Resolves and returns the context limit for the *current main model*."""
        provider = self._settings_service.get_setting('provider', 'Ollama').lower()
        model_name = self._settings_service.get_setting('model', '')
        if not model_name: return self._settings_service.get_setting('context_limit', 4096) # Fallback if no model

        try:
             # Use the dynamic resolution function
             limit = resolve_context_limit(provider, model_name)
             # Store it back into settings maybe? Or just return resolved value?
             # self._settings_service.set_setting('context_limit', limit) # careful with signaling loops
             return limit
        except Exception as e:
             logger.error(f"Failed to resolve context limit for {provider}/{model_name}: {e}")
             return self._settings_service.get_setting('context_limit', 4096) # Fallback to stored/default

