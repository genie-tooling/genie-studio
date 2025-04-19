# pm/core/llm_service_provider.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from loguru import logger
from typing import Optional, Any

import ollama

from .settings_service import SettingsService
from .ollama_service import OllamaService
from .gemini_service import GeminiService
from .model_registry import resolve_context_limit
from .project_config import DEFAULT_CONFIG

class LLMServiceProvider(QObject):
    """
    Manages LLM service clients, switching, context limit resolution,
    and explicitly unloading previous Ollama models.
    """
    services_updated = pyqtSignal()
    context_limit_changed = pyqtSignal(int)

    def __init__(self, settings_service: SettingsService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._settings_service = settings_service
        self._model_service: Optional[OllamaService | GeminiService] = None
        self._summarizer_service: Optional[OllamaService | GeminiService] = None
        self._current_context_limit: int = 0 # Store current limit
        # --- Delay connections ---
        logger.info("LLMServiceProvider initialized. Delaying pyqtSignal connections.")
        # Trigger initial update and connection setup after event loop starts
        QTimer.singleShot(10, self._connect_and_update) # Increased delay slightly

    # --- NEW pyqtSlot to connect pyqtSignals and perform initial update ---
    @pyqtSlot()
    def _connect_and_update(self):
        logger.info("LLMServiceProvider: Connecting pyqtSignals and performing initial update.")
        # Connect pyqtSignals AFTER attributes are initialized and initial events processed
        try:
            self._settings_service.llm_config_changed.connect(self._update_services)
            self._settings_service.rag_config_changed.connect(self._update_services)
        except Exception as e:
             logger.error(f"LLMServiceProvider: Failed to connect pyqtSignals: {e}")
             # Handle error? Maybe try again later? For now, log it.

        # Now perform the initial update
        self._update_services()

    @pyqtSlot()
    def _update_services(self):
        # --- Check removed from here, now only called when config *actually* changes ---
        # logger.info("LLMServiceProvider: Checking if service update needed...")
        logger.info("LLMServiceProvider: _update_services triggered.") # Log when it runs

        # --- Get current settings relevant to service identity ---
        provider = self._settings_service.get_setting('provider', 'Ollama').lower()
        model_name = self._settings_service.get_setting('model', '')
        api_key = self._settings_service.get_setting('api_key', '') # Needed for Gemini identity
        summ_provider = self._settings_service.get_setting('rag_summarizer_provider', 'Ollama').lower()
        summ_model = self._settings_service.get_setting('rag_summarizer_model_name', '')
        summ_enabled = self._settings_service.get_setting('rag_summarizer_enabled', True)

        # --- Get current service state ---
        current_provider_type = 'gemini' if isinstance(self._model_service, GeminiService) else ('ollama' if isinstance(self._model_service, OllamaService) else None)
        current_model_name = getattr(self._model_service, 'model', None)

        current_summ_provider_type = 'gemini' if isinstance(self._summarizer_service, GeminiService) else ('ollama' if isinstance(self._summarizer_service, OllamaService) else None)
        current_summ_model_name = getattr(self._summarizer_service, 'model', None)
        current_summ_enabled = self._summarizer_service is not None

        # --- Check if core settings defining the services have changed ---
        main_service_needs_update = (
            (provider != current_provider_type) or
            (model_name != current_model_name) or
            (provider == 'gemini' and not isinstance(self._model_service, GeminiService)) # Need Gemini
        )
        summ_service_needs_update = (
            (summ_enabled != current_summ_enabled) or
            (summ_enabled and summ_provider != current_summ_provider_type) or
            (summ_enabled and summ_model != current_summ_model_name) or
            (summ_enabled and summ_provider == 'gemini' and not isinstance(self._summarizer_service, GeminiService)) # Need Gemini Summ
        )

        # --- Bail out early if nothing significant changed ---
        # Keep this check, as pyqtSignals might still fire even if value is technically same
        if not main_service_needs_update and not summ_service_needs_update:
             logger.debug("LLMServiceProvider: No significant config change detected within _update_services. Skipping service update.")
             self._check_and_emit_context_limit()
             return

        logger.info("LLMServiceProvider: Configuration change detected within _update_services. Updating services...")
        services_changed_flag = False # Track if any service instance actually changed

        # --- Store old main service BEFORE creating new one ---
        old_model_service = self._model_service
        old_model_name = current_model_name # Use already fetched value

        # --- Update Main Model Service ---
        if main_service_needs_update:
            temp = self._settings_service.get_setting('temperature', 0.3); top_k = self._settings_service.get_setting('top_k', 40)
            new_model_service = None
            try:
                if provider == 'ollama' and model_name:
                    logger.debug(f"Attempting Ollama setup for model '{model_name}'")
                    resolve_context_limit(provider, model_name) # Pre-check context
                    new_model_service = OllamaService(model=model_name)
                elif provider == 'gemini' and model_name and api_key:
                    logger.debug(f"Attempting Gemini setup for model '{model_name}'")
                    new_model_service = GeminiService(model=model_name, api_key=api_key, temp=temp, top_k=top_k);
            except Exception as e: logger.exception(f"Failed service instantiation for {provider}/{model_name}: {e}")

            new_type = type(new_model_service).__name__ if new_model_service else None
            new_model = getattr(new_model_service, 'model', None) if new_model_service else None
            logger.info(f"Switching main model service from {current_provider_type}({old_model_name}) to {new_type}({new_model})")

            self._model_service = new_model_service # Update internal reference
            services_changed_flag = True # Service instance changed

            if isinstance(old_model_service, OllamaService) and old_model_name:
                 logger.info(f"Scheduling unload for previous Ollama model: {old_model_name}")
                 QTimer.singleShot(100, lambda model=old_model_name: self._request_ollama_unload(model))
        else:
            logger.debug("Main model service configuration unchanged.")

        # --- Update Summarizer Service ---
        if summ_service_needs_update:
            old_summ_service = self._summarizer_service
            old_summ_type = current_summ_provider_type
            old_summ_model = current_summ_model_name

            new_summarizer_service = None
            if summ_enabled:
                summ_api_key = api_key
                try:
                    if summ_provider == 'ollama' and summ_model:
                        logger.debug(f"Attempting Summarizer OllamaService for '{summ_model}'");
                        resolve_context_limit(summ_provider, summ_model);
                        new_summarizer_service = OllamaService(model=summ_model)
                    elif summ_provider == 'gemini' and summ_model and summ_api_key:
                        logger.debug(f"Attempting Summarizer GeminiService for '{summ_model}'");
                        new_summarizer_service = GeminiService(model=summ_model, api_key=summ_api_key)
                except Exception as e: logger.exception(f"Failed summarizer instantiation for {summ_provider}/{summ_model}: {e}")

            new_summ_type = type(new_summarizer_service).__name__ if new_summarizer_service else None;
            new_summ_model = getattr(new_summarizer_service, 'model', None) if new_summarizer_service else None

            logger.info(f"Switching summarizer from {old_summ_type}({old_summ_model}) to {new_summ_type}({new_summ_model})")
            self._summarizer_service = new_summarizer_service;
            services_changed_flag = True
        else:
             logger.debug("Summarizer configuration unchanged.")

        if services_changed_flag:
            logger.debug("Emitting services_updated pyqtSignal.");
            self.services_updated.emit()

        self._check_and_emit_context_limit()

    @pyqtSlot(str)
    def _request_ollama_unload(self, model_name_to_unload: str):
        if not model_name_to_unload: logger.warning("Ollama unload request skipped: No model name provided."); return
        logger.info(f"Sending unload request for Ollama model: {model_name_to_unload}")
        try:
            temp_client = ollama.Client()
            response = temp_client.generate( model=model_name_to_unload, prompt="", stream=False, keep_alive=0 )
            logger.debug(f"Ollama unload response for '{model_name_to_unload}': {response}")
            logger.info(f"Unload request successfully sent for {model_name_to_unload}.")
        except ollama.ResponseError as e:
             if e.status_code == 404: logger.debug(f"Ollama unload request for '{model_name_to_unload}' returned 404 (Model likely not loaded or found).")
             else: logger.error(f"Ollama API error during unload request for '{model_name_to_unload}': {e.status_code} - {e.error}")
        except Exception as e: logger.exception(f"Unexpected error sending Ollama unload request for '{model_name_to_unload}': {e}")

    def _check_and_emit_context_limit(self):
        new_limit = 0
        try:
            new_limit = self.get_context_limit()
            if new_limit != self._current_context_limit:
                 logger.info(f"Context limit changed from {self._current_context_limit} to {new_limit}. Emitting pyqtSignal.");
                 self._current_context_limit = new_limit
                 self.context_limit_changed.emit(new_limit)
            else:
                 logger.trace(f"Context limit unchanged ({new_limit}). Skipping pyqtSignal emission.")
        except Exception as e:
            logger.error(f"Error resolving context limit during check: {e}. Emitting fallback.");
            fallback_limit = DEFAULT_CONFIG.get('context_limit', 4096);
            if fallback_limit != self._current_context_limit:
                 self._current_context_limit = fallback_limit
                 self.context_limit_changed.emit(fallback_limit)

    # --- Getters ---
    def get_model_service(self) -> Optional[OllamaService | GeminiService]: return self._model_service
    def get_summarizer_service(self) -> Optional[OllamaService | GeminiService]: return self._summarizer_service
    def get_context_limit(self) -> int:
        logger.trace("get_context_limit() called.")
        active_service = self._model_service
        if active_service:
             provider = 'gemini' if isinstance(active_service, GeminiService) else 'ollama'
             model_name = getattr(active_service, 'model', '')
             if model_name:
                  try: limit = resolve_context_limit(provider, model_name); logger.trace(f"Resolved ctx from active service ({provider}/{model_name}): {limit}"); return limit
                  except Exception as e: logger.error(f"Failed resolve ctx for active service {provider}/{model_name}: {e}. Falling back.")
             else: logger.warning("Active service exists but has no model name? Falling back.")
        logger.debug("Falling back to resolving context limit from settings.")
        provider_from_settings = self._settings_service.get_setting('provider', 'Ollama').lower();
        model_from_settings = self._settings_service.get_setting('model', '')
        if model_from_settings:
            try: limit = resolve_context_limit(provider_from_settings, model_from_settings); logger.debug(f"Resolved limit from settings ({provider_from_settings}/{model_from_settings}): {limit}"); return limit
            except Exception as e: logger.warning(f"Failed resolve limit from settings ({provider_from_settings}/{model_from_settings}): {e}. Using default."); return DEFAULT_CONFIG.get('context_limit', 4096)
        else: logger.debug(f"No model in settings. Using default context limit."); return DEFAULT_CONFIG.get('context_limit', 4096)
