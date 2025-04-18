# pm/core/model_list_service.py
from PySide6.QtCore import QObject, Signal, Slot, QThread
from loguru import logger
from typing import List, Optional, Any, Dict # Added Dict

from .model_registry import list_models

# --- Worker Class (remains the same) ---
class ModelRefreshWorker(QObject):
    """Worker object to fetch models in a background thread."""
    models_ready = Signal(str, list) # provider_type ('llm'/'summarizer'), models_list
    error_occurred = Signal(str, str) # provider_type, error_message
    finished = Signal(str) # provider_type

    def __init__(self, provider_type: str, provider_name: str, api_key: Optional[str]):
        super().__init__()
        self.provider_type = provider_type
        self.provider_name = provider_name
        self.api_key = api_key
        self._is_interrupted = False
        self._thread_ref = None # Store owning thread ref for logging

    def assign_thread(self, thread: QThread):
        self._thread_ref = thread

    @Slot()
    def run(self):
        """Fetch the models."""
        thread_id = self._thread_ref.objectName() if self._thread_ref else 'UnknownThread'
        logger.debug(f"ModelRefreshWorker ({self.provider_type} on {thread_id}): Starting run for provider '{self.provider_name}'.")
        models = []
        try:
            models = list_models(
                provider=self.provider_name,
                api_key=self.api_key,
                force_no_cache=True
            )

            if self._is_interrupted:
                logger.info(f"ModelRefreshWorker ({self.provider_type} on {thread_id}): Interrupted during fetch.")
            else:
                self.models_ready.emit(self.provider_type, models)
                logger.debug(f"ModelRefreshWorker ({self.provider_type} on {thread_id}): Emitted models_ready ({len(models)}).")

        except Exception as e:
            error_msg = f"Error fetching models for {self.provider_name} ({self.provider_type}): {e}"
            logger.error(error_msg)
            if not self._is_interrupted:
                self.error_occurred.emit(self.provider_type, error_msg)
        finally:
            logger.debug(f"ModelRefreshWorker ({self.provider_type} on {thread_id}): Emitting finished signal.")
            self.finished.emit(self.provider_type)

    def request_interruption(self):
        self._is_interrupted = True


# --- Service Class (Modified) ---
class ModelListService(QObject):
    """
    Manages background fetching of model lists for different providers.
    Encapsulates QThread/Worker logic.
    """
    llm_models_updated = Signal(list)
    summarizer_models_updated = Signal(list)
    model_refresh_error = Signal(str, str) # provider_type, error_message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._active_threads: Dict[str, QThread] = {}
        self._active_workers: Dict[str, ModelRefreshWorker] = {}
        logger.info("ModelListService initialized.")

    def _cleanup_thread(self, provider_type: str):
        """Safely requests stop and cleans up a worker/thread pair for a specific type."""
        thread = self._active_threads.get(provider_type) # Use .get() to avoid KeyError if already removed
        worker = self._active_workers.get(provider_type)

        # --- Disconnect signals FIRST to prevent dangling connections ---
        if worker:
            try: worker.models_ready.disconnect(self._handle_worker_models_ready)
            except RuntimeError: pass
            try: worker.error_occurred.disconnect(self._handle_worker_error)
            except RuntimeError: pass
            try: worker.finished.disconnect(self._handle_worker_finished)
            except RuntimeError: pass
            # Also disconnect the connection to thread.quit if it exists
            try: worker.finished.disconnect(thread.quit)
            except (RuntimeError, TypeError): pass # TypeError if thread is None

        if thread:
             # Disconnect thread signals
            try: thread.finished.disconnect(self._cleanup_references)
            except RuntimeError: pass
            try: thread.finished.disconnect(thread.deleteLater)
            except RuntimeError: pass
            try: thread.started.disconnect(worker.run) # worker might be None here
            except (RuntimeError, TypeError): pass

        # --- Now handle thread shutdown ---
        if thread and thread.isRunning():
            logger.debug(f"ModelListService: Cleaning up previous thread for '{provider_type}'...")
            if worker:
                worker.request_interruption()

            thread.quit()
            if not thread.wait(1000):
                logger.warning(f"ModelListService: Thread for '{provider_type}' did not finish quitting gracefully. Terminating.")
                thread.terminate()
                thread.wait(500)
            else:
                logger.debug(f"ModelListService: Thread for '{provider_type}' finished.")
        elif thread:
             logger.debug(f"ModelListService: Thread for '{provider_type}' already finished or not started.")

        # --- Remove references AFTER potential cleanup ---
        self._active_threads.pop(provider_type, None)
        self._active_workers.pop(provider_type, None)
        logger.debug(f"ModelListService: References for '{provider_type}' removed.")


    @Slot(str, str, str)
    def refresh_models(self, provider_type: str, provider_name: str, api_key: Optional[str] = None):
        if provider_type not in ['llm', 'summarizer']:
            logger.error(f"ModelListService: Invalid provider_type '{provider_type}' for refresh.")
            return

        self._cleanup_thread(provider_type) # Cleanup previous first
        logger.info(f"ModelListService: Starting {provider_type} model refresh for provider '{provider_name}'...")

        thread = QThread()
        thread.setObjectName(f"ModelRefreshThread_{provider_type.upper()}")
        worker = ModelRefreshWorker(provider_type, provider_name, api_key)
        worker.assign_thread(thread)

        self._active_threads[provider_type] = thread
        self._active_workers[provider_type] = worker
        worker.moveToThread(thread)

        # --- Connect Worker Signals ---
        worker.models_ready.connect(self._handle_worker_models_ready)
        worker.error_occurred.connect(self._handle_worker_error)
        worker.finished.connect(self._handle_worker_finished) # Still useful for logging perhaps

        # --- Connect Thread Lifecycle Signals ---
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit) # Worker finishing tells thread to stop its loop
        worker.finished.connect(worker.deleteLater) # Worker cleans itself up
        thread.finished.connect(thread.deleteLater) # Thread cleans itself up *after* finishing

        # --- *** Connect thread.finished to the NEW cleanup slot *** ---
        thread.finished.connect(lambda pt=provider_type: self._cleanup_references(pt))

        thread.start()
        logger.debug(f"ModelListService: Started background thread for {provider_type} refresh ({thread.objectName()}).")


    @Slot(str, list)
    def _handle_worker_models_ready(self, provider_type: str, models: list):
        """Internal slot to handle successful model list retrieval."""
        logger.info(f"ModelListService: Received {len(models)} models for {provider_type}.")
        if provider_type == 'llm':
            self.llm_models_updated.emit(models)
        elif provider_type == 'summarizer':
            self.summarizer_models_updated.emit(models)

    @Slot(str, str)
    def _handle_worker_error(self, provider_type: str, error_message: str):
        """Internal slot to handle errors from the worker."""
        logger.error(f"ModelListService: Received error for {provider_type}: {error_message}")
        self.model_refresh_error.emit(provider_type, error_message)

    @Slot(str)
    def _handle_worker_finished(self, provider_type: str):
        """Internal slot called when a worker's finished signal is emitted.
           *** DO NOT REMOVE REFERENCES HERE ANYMORE *** """
        logger.debug(f"ModelListService: Worker task finished signal received for {provider_type}.")
        # No longer responsible for removing references here.

    # --- *** NEW SLOT *** ---
    @Slot(str)
    def _cleanup_references(self, provider_type: str):
        """Slot connected to thread.finished to safely remove references."""
        logger.debug(f"ModelListService: Thread finished signal received for '{provider_type}'. Cleaning up references.")
        # It's now safe to remove the references because the thread has fully stopped.
        if provider_type in self._active_threads:
            del self._active_threads[provider_type]
        if provider_type in self._active_workers:
            del self._active_workers[provider_type]
        logger.debug(f"ModelListService: Cleaned up references for finished {provider_type} worker/thread.")


    @Slot(str)
    def stop_refresh(self, provider_type: str):
         if provider_type in self._active_threads:
              logger.info(f"ModelListService: Requesting stop for '{provider_type}' refresh...")
              self._cleanup_thread(provider_type)
         else:
              logger.warning(f"ModelListService: Stop requested for '{provider_type}', but no active refresh found.")

    @Slot()
    def stop_all_refreshes(self):
         logger.info("ModelListService: Requesting stop for ALL active refreshes...")
         for provider_type in list(self._active_threads.keys()):
              self._cleanup_thread(provider_type)