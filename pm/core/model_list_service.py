# pm/core/model_list_service.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread, QTimer # Added QTimer
from loguru import logger
from typing import List, Optional, Any, Dict

from .model_registry import list_models

# --- Worker Class (remains the same) ---
class ModelRefreshWorker(QObject):
    """Worker object to fetch models in a background thread."""
    models_ready = pyqtSignal(str, list) # provider_type ('llm'/'summarizer'), models_list
    error_occurred = pyqtSignal(str, str) # provider_type, error_message
    finished = pyqtSignal(str) # provider_type

    def __init__(self, provider_type: str, provider_name: str, api_key: Optional[str]):
        super().__init__()
        self.provider_type = provider_type
        self.provider_name = provider_name
        self.api_key = api_key
        self._is_interrupted = False
        self._thread_ref = None # Store owning thread ref for logging

    def assign_thread(self, thread: QThread):
        self._thread_ref = thread

    @pyqtSlot()
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
            logger.debug(f"ModelRefreshWorker ({self.provider_type} on {thread_id}): Emitting finished pyqtSignal.")
            self.finished.emit(self.provider_type)

    def request_interruption(self):
        self._is_interrupted = True

# --- Service Class (Modified) ---
class ModelListService(QObject):
    """
    Manages background fetching of model lists for different providers.
    Encapsulates QThread/Worker logic.
    """
    llm_models_updated = pyqtSignal(list)
    summarizer_models_updated = pyqtSignal(list)
    model_refresh_error = pyqtSignal(str, str) # provider_type, error_message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._active_threads: Dict[str, QThread] = {}
        self._active_workers: Dict[str, ModelRefreshWorker] = {}
        logger.info("ModelListService initialized.")

    def _cleanup_thread(self, provider_type: str):
        """Safely requests stop and cleans up a worker/thread pair for a specific type."""
        thread = self._active_threads.get(provider_type)
        worker = self._active_workers.get(provider_type)

        # Disconnect pyqtSignals FIRST
        if worker:
            try: worker.models_ready.disconnect(self._handle_worker_models_ready)
            except RuntimeError: pass
            try: worker.error_occurred.disconnect(self._handle_worker_error)
            except RuntimeError: pass
            try: worker.finished.disconnect(self._handle_worker_finished)
            except RuntimeError: pass
            try: worker.finished.disconnect(thread.quit)
            except (RuntimeError, TypeError): pass
            # We don't explicitly disconnect worker.deleteLater connection

        if thread:
             # Disconnect thread pyqtSignals
            try: thread.finished.disconnect(self._schedule_reference_cleanup) # Disconnect new pyqtSlot
            except RuntimeError: pass
            try: thread.finished.disconnect(thread.deleteLater)
            except RuntimeError: pass
            try: thread.started.disconnect(worker.run)
            except (RuntimeError, TypeError): pass

        # Now handle thread shutdown
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

        # --- References are now removed in _cleanup_references via QTimer ---
        # self._active_threads.pop(provider_type, None) # REMOVED FROM HERE
        # self._active_workers.pop(provider_type, None) # REMOVED FROM HERE
        # logger.debug(f"ModelListService: References for '{provider_type}' *will be removed* after thread finishes.")

    @pyqtSlot(str, str, str)
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

        # --- Connect Worker pyqtSignals ---
        worker.models_ready.connect(self._handle_worker_models_ready)
        worker.error_occurred.connect(self._handle_worker_error)
        worker.finished.connect(self._handle_worker_finished)

        # --- Connect Thread Lifecycle pyqtSignals ---
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit) # Worker finishing tells thread to stop its loop
        worker.finished.connect(worker.deleteLater) # Worker cleans itself up
        thread.finished.connect(thread.deleteLater) # Thread cleans itself up *after* finishing

        # --- Connect thread.finished to the *scheduling* pyqtSlot ---
        thread.finished.connect(lambda pt=provider_type: self._schedule_reference_cleanup(pt))

        thread.start()
        logger.debug(f"ModelListService: Started background thread for {provider_type} refresh ({thread.objectName()}).")

    @pyqtSlot(str, list)
    def _handle_worker_models_ready(self, provider_type: str, models: list):
        """Internal pyqtSlot to handle successful model list retrieval."""
        logger.info(f"ModelListService: Received {len(models)} models for {provider_type}.")
        if provider_type == 'llm':
            self.llm_models_updated.emit(models)
        elif provider_type == 'summarizer':
            self.summarizer_models_updated.emit(models)

    @pyqtSlot(str, str)
    def _handle_worker_error(self, provider_type: str, error_message: str):
        """Internal pyqtSlot to handle errors from the worker."""
        logger.error(f"ModelListService: Received error for {provider_type}: {error_message}")
        self.model_refresh_error.emit(provider_type, error_message)

    @pyqtSlot(str)
    def _handle_worker_finished(self, provider_type: str):
        """Internal pyqtSlot called when a worker's finished pyqtSignal is emitted."""
        logger.debug(f"ModelListService: Worker task finished pyqtSignal received for {provider_type}.")
        # No reference cleanup here.

    # --- NEW pyqtSlot ---
    @pyqtSlot(str)
    def _schedule_reference_cleanup(self, provider_type: str):
        """Schedules the final reference cleanup using a QTimer."""
        logger.debug(f"ModelListService: Thread finished pyqtSignal received for '{provider_type}'. Scheduling reference cleanup.")
        QTimer.singleShot(0, lambda: self._cleanup_references(provider_type))

    # --- Renamed original cleanup ---
    def _cleanup_references(self, provider_type: str):
        """pyqtSlot called via QTimer to safely remove references *after* thread.finished event processing."""
        logger.debug(f"ModelListService: Deleting references for '{provider_type}'.")
        # It's now safer to remove the references because the thread has fully stopped,
        # and deleteLater should have had a chance to be processed by the event loop.
        if provider_type in self._active_threads:
            del self._active_threads[provider_type]
        if provider_type in self._active_workers:
            del self._active_workers[provider_type]
        logger.debug(f"ModelListService: Cleaned up references for finished {provider_type} worker/thread.")

    @pyqtSlot(str)
    def stop_refresh(self, provider_type: str):
         if provider_type in self._active_threads:
              logger.info(f"ModelListService: Requesting stop for '{provider_type}' refresh...")
              self._cleanup_thread(provider_type)
         else:
              logger.warning(f"ModelListService: Stop requested for '{provider_type}', but no active refresh found.")

    @pyqtSlot()
    def stop_all_refreshes(self):
         logger.info("ModelListService: Requesting stop for ALL active refreshes...")
         for provider_type in list(self._active_threads.keys()): # Iterate over a copy of keys
              self._cleanup_thread(provider_type) # This will now just request stop