# pm/core/llm_service_provider.py
from PySide6.QtCore import QObject, Signal, Slot
from loguru import logger
from typing import Optional, Any

from .settings_service import SettingsService
from .ollama_service import OllamaService
from .gemini_service import GeminiService
from .model_registry import resolve_context_limit, list_ollama_models, list_gemini_models
from .project_config import DEFAULT_CONFIG # For fallback limit

class LLMServiceProvider(QObject):
    """
    Manages the instantiation and switching of LLM service clients (Ollama, Gemini)
    based on settings provided by SettingsService. Resolves and emits the correct
    context limit early during initialization and after project settings load.
    """
    services_updated = Signal() # Emitted when model or summarizer service instances change
    context_limit_changed = Signal(int) # Emitted when the main model's context limit changes

    def __init__(self, settings_service: SettingsService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._settings_service = settings_service
        self._model_service: Optional[OllamaService | GeminiService] = None
        self._summarizer_service: Optional[OllamaService | GeminiService] = None

        # Connect to relevant settings changes *before* initial update
        self._settings_service.llm_config_changed.connect(self._update_services)
        self._settings_service.rag_config_changed.connect(self._update_services) # RAG config might change summarizer
        # *** Connect settings_loaded to trigger service update ***
        self._settings_service.settings_loaded.connect(self._update_services)
        # **********************************************************

        # Initial service creation AND context limit resolution happens here
        # because __init__ calls _update_services implicitly via the settings_loaded connection
        # or directly if no settings file existed initially. Let's call it explicitly
        # just in case settings_loaded doesn't fire on first ever run?
        # No, settings_loaded *should* fire even if loading defaults.
        # self._update_services() # Explicit call removed, rely on signal connection

        logger.info("LLMServiceProvider initialized and connected to settings signals.")

    @Slot()
    def _update_services(self):
        """
        Reads current settings, creates/updates service instances, and immediately
        resolves and emits the context limit for the main model.
        This is triggered by llm_config_changed, rag_config_changed, OR settings_loaded.
        """
        logger.info("LLMServiceProvider: _update_services triggered. Updating services and resolving context limit...")
        services_changed = False

        # --- Update Main Model Service ---
        provider = self._settings_service.get_setting('provider', 'Ollama').lower()
        model_name = self._settings_service.get_setting('model', '')
        api_key = self._settings_service.get_setting('api_key', '')
        temp = self._settings_service.get_setting('temperature', 0.3)
        top_k = self._settings_service.get_setting('top_k', 40)

        # Store previous service details for comparison
        old_model_service = self._model_service
        old_model_type = type(old_model_service).__name__ if old_model_service else None
        old_model_name = getattr(old_model_service, 'model', None) if old_model_service else None

        new_model_service = None
        try:
            if provider == 'ollama' and model_name:
                logger.debug(f"LLMServiceProvider: Attempting Ollama setup for model '{model_name}'")
                try:
                    resolve_context_limit(provider, model_name) # Check existence via ollama.show
                    new_model_service = OllamaService(model=model_name)
                    logger.debug(f"LLMServiceProvider: Successfully created OllamaService for '{model_name}'.")
                except Exception as resolve_err:
                     logger.error(f"LLMServiceProvider: Failed context check/creation for Ollama model '{model_name}': {resolve_err}.")

            elif provider == 'gemini' and model_name and api_key:
                logger.debug(f"LLMServiceProvider: Attempting Gemini setup for model '{model_name}'")
                new_model_service = GeminiService(model=model_name, api_key=api_key, temp=temp, top_k=top_k)
                logger.debug(f"LLMServiceProvider: Successfully created GeminiService for '{model_name}'.")

            elif provider == 'gemini' and not api_key:
                 logger.warning("LLMServiceProvider: Gemini provider selected but API key is missing.")
            elif not model_name:
                logger.warning(f"LLMServiceProvider: {provider.capitalize()} provider selected but model name is empty.")

        except Exception as e:
            logger.exception(f"LLMServiceProvider: Failed during service instantiation for {provider}/{model_name}: {e}")
            new_model_service = None

        # Update internal service reference if changed
        new_type = type(new_model_service).__name__ if new_model_service else None
        new_model = getattr(new_model_service, 'model', None) if new_model_service else None

        if new_type != old_model_type or new_model != old_model_name:
            logger.info(f"LLMServiceProvider: Switching main model service from {old_model_type}({old_model_name}) to {new_type}({new_model})")
            self._model_service = new_model_service
            services_changed = True
        else:
             logger.debug(f"LLMServiceProvider: Main model service unchanged ({new_type}({new_model})).")


        # --- Update Summarizer Service (logic remains similar) ---
        # (Keep existing summarizer update logic here...)
        summ_enabled = self._settings_service.get_setting('rag_summarizer_enabled', True)
        summ_provider = self._settings_service.get_setting('rag_summarizer_provider', 'Ollama').lower()
        summ_model = self._settings_service.get_setting('rag_summarizer_model_name', '')
        summ_api_key = api_key # Use main API key for Gemini

        old_summ_service = self._summarizer_service
        old_summ_type = type(old_summ_service).__name__ if old_summ_service else None
        old_summ_model = getattr(old_summ_service, 'model', None) if old_summ_service else None

        new_summarizer_service = None
        if summ_enabled:
            try:
                if summ_provider == 'ollama' and summ_model:
                    try:
                        resolve_context_limit(summ_provider, summ_model)
                        logger.debug(f"LLMServiceProvider: Attempting Summarizer OllamaService for model '{summ_model}'")
                        new_summarizer_service = OllamaService(model=summ_model)
                    except Exception as resolve_err:
                         logger.error(f"LLMServiceProvider: Failed context check/creation for Summarizer Ollama model '{summ_model}': {resolve_err}.")

                elif summ_provider == 'gemini' and summ_model and summ_api_key:
                     logger.debug(f"LLMServiceProvider: Attempting Summarizer GeminiService for model '{summ_model}'")
                     new_summarizer_service = GeminiService(model=summ_model, api_key=summ_api_key)

                elif summ_provider == 'gemini' and not summ_api_key:
                     logger.warning("LLMServiceProvider: Summarizer uses Gemini provider but main API key is missing.")
                elif not summ_model:
                     logger.warning(f"LLMServiceProvider: Summarizer provider {summ_provider.capitalize()} selected but model name is empty.")
            except Exception as e:
                logger.exception(f"LLMServiceProvider: Failed during summarizer instantiation for {summ_provider}/{summ_model}: {e}")
                new_summarizer_service = None

        # Update Summarizer Service reference if changed
        new_summ_type = type(new_summarizer_service).__name__ if new_summarizer_service else None
        new_summ_model = getattr(new_summarizer_service, 'model', None) if new_summarizer_service else None

        if new_summ_type != old_summ_type or new_summ_model != old_summ_model:
             logger.info(f"LLMServiceProvider: Switching summarizer service from {old_summ_type}({old_summ_model}) to {new_summ_type}({new_summ_model})")
             self._summarizer_service = new_summarizer_service
             services_changed = True
        elif not summ_enabled and self._summarizer_service is not None:
             logger.info("LLMServiceProvider: Disabling summarizer service.")
             self._summarizer_service = None # Explicitly disable
             services_changed = True
        else:
             logger.debug("LLMServiceProvider: Summarizer service unchanged.")


        # --- Emit signals AFTER potential changes ---
        if services_changed:
            logger.debug("LLMServiceProvider: Emitting services_updated signal.")
            self.services_updated.emit()

        # *** Always resolve and emit the context limit for the *current* main model ***
        # This ensures the correct limit is known immediately after any update.
        resolved_limit = 0
        try:
            resolved_limit = self.get_context_limit() # Use the getter which handles resolution
            logger.info(f"LLMServiceProvider: Resolved context limit post-update: {resolved_limit}. Emitting signal.")
            self.context_limit_changed.emit(resolved_limit)
        except Exception as e:
            logger.error(f"LLMServiceProvider: Error resolving context limit after update: {e}. Emitting fallback.")
            fallback_limit = DEFAULT_CONFIG.get('context_limit', 4096)
            self.context_limit_changed.emit(fallback_limit)


    def get_model_service(self) -> Optional[OllamaService | GeminiService]:
        """Returns the current main LLM service instance."""
        return self._model_service

    def get_summarizer_service(self) -> Optional[OllamaService | GeminiService]:
        """Returns the current summarizer LLM service instance (if enabled)."""
        return self._summarizer_service

    def get_context_limit(self) -> int:
        """Resolves and returns the context limit for the *currently active main model*."""
        logger.trace("LLMServiceProvider: get_context_limit() called.")
        # Use the currently active service if it exists
        active_service = self._model_service
        if active_service:
             provider = 'gemini' if isinstance(active_service, GeminiService) else 'ollama'
             model_name = getattr(active_service, 'model', '')
             if model_name:
                  try:
                      limit = resolve_context_limit(provider, model_name)
                      logger.trace(f"LLMServiceProvider: Resolved context limit from active service ({provider}/{model_name}): {limit}")
                      return limit
                  except Exception as e:
                       logger.error(f"LLMServiceProvider: Failed to resolve context limit for active service {provider}/{model_name}: {e}. Falling back.")
                       # Fall through to using settings if active service resolution fails
             else:
                  logger.warning("LLMServiceProvider: Active service exists but has no model name? Falling back to settings.")
                  # Fall through

        # Fallback: If no active service OR active service failed, resolve based on *settings*
        logger.debug("LLMServiceProvider: Falling back to resolving context limit from settings.")
        provider_from_settings = self._settings_service.get_setting('provider', 'Ollama').lower()
        model_from_settings = self._settings_service.get_setting('model', '')
        if model_from_settings:
            try:
                 limit = resolve_context_limit(provider_from_settings, model_from_settings)
                 logger.debug(f"LLMServiceProvider: Resolved limit from settings ({provider_from_settings}/{model_from_settings}): {limit}")
                 return limit
            except Exception as e:
                 logger.warning(f"LLMServiceProvider: Failed to resolve limit from settings ({provider_from_settings}/{model_from_settings}): {e}. Using default.")
                 return DEFAULT_CONFIG.get('context_limit', 4096)
        else:
             logger.debug(f"LLMServiceProvider: No model in settings. Using default context limit.")
             return DEFAULT_CONFIG.get('context_limit', 4096)
