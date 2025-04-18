# pm/core/task_manager.py
from PySide6.QtCore import QObject, Signal, Slot, QThread, QTimer, Qt
from loguru import logger
from pathlib import Path
from typing import List, Dict, Optional, Any

from .background_tasks import Worker
from .gemini_service import GeminiService
from .ollama_service import OllamaService
from .settings_service import SettingsService


class BackgroundTaskManager(QObject):
    """Manages the lifecycle of background LLM tasks."""

    generation_started = Signal()
    generation_finished = Signal(bool) # bool: True if stopped by user, False otherwise
    status_update = Signal(str)
    context_info = Signal(int, int)
    stream_chunk = Signal(str)
    stream_error = Signal(str)

    def __init__(self, settings_service: SettingsService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings_service = settings_service
        self.model_service: Optional[OllamaService | GeminiService] = None
        self.summarizer_service: Optional[OllamaService | GeminiService] = None

        self._thread: Optional[QThread] = None
        self._worker: Optional[Worker] = None
        self._is_generating: bool = False
        self._stop_requested: bool = False

    def set_services(self, model_service: Optional[Any], summarizer_service: Optional[Any]):
        logger.debug("BackgroundTaskManager: Updating service references.")
        self.model_service = model_service
        self.summarizer_service = summarizer_service

    def is_busy(self) -> bool:
        return self._is_generating

    @Slot(list, list, Path)
    def start_generation(self,
                         history_snapshot: list[dict],
                         checked_file_paths: List[Path],
                         project_path: Path):
        if self._is_generating:
            logger.warning("Task Manager: Generation already in progress. Cannot start new task.")
            return
        if not self.model_service:
            logger.error("Task Manager: Cannot start generation, model service is not set.")
            self.stream_error.emit("Model service not available.")
            return
        if not self.settings_service:
            logger.error("Task Manager: Cannot start generation, settings service is not set.")
            self.stream_error.emit("Settings service not available.")
            return

        # --- Aggressive Cleanup Before Starting ---
        if self._thread is not None:
            logger.warning("Task Manager: Cleaning up previous thread before starting new one.")
            self._request_stop_and_wait(timeout_ms=500) # Shorter timeout
        # -----------------------------------------

        logger.info("Task Manager: Initiating background worker thread...")
        self._is_generating = True
        self._stop_requested = False

        self._thread = QThread()
        self._thread.setObjectName("LLMWorkerThread")
        current_settings = self.settings_service.get_all_settings()

        # Create worker *before* connecting signals that might reference it
        self._worker = Worker(
            settings=current_settings.copy(),
            history=history_snapshot,
            main_services={'model_service': self.model_service, 'summarizer_service': self.summarizer_service},
            checked_file_paths=checked_file_paths,
            project_path=project_path
        )
        worker_obj = self._worker # Local reference for connections

        worker_obj.moveToThread(self._thread)

        # --- Connections (Ensure using local refs worker_obj, self._thread where appropriate) ---
        worker_obj.status_update.connect(self.status_update)
        worker_obj.context_info.connect(self.context_info)
        worker_obj.stream_chunk.connect(self.stream_chunk)
        worker_obj.stream_error.connect(self.stream_error)
        worker_obj.stream_finished.connect(self._handle_worker_finished_signal)

        self._thread.started.connect(worker_obj.process)
        worker_obj.stream_finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection) # Try direct connection

        # CRITICAL: Connect deleteLater *before* the _on_thread_finished slot
        # This schedules deletion as soon as the thread's event loop finishes.
        self._thread.finished.connect(worker_obj.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        logger.debug("Task Manager: Connected deleteLater for worker and thread.")

        # Connect manager state reset *after* deleteLater is scheduled.
        self._thread.finished.connect(self._on_thread_finished)
        # ---------------------------------------------------------------------

        self._thread.start()
        logger.info(f"Task Manager: Started background worker thread ({self._thread.objectName()}).")
        self.generation_started.emit()

    @Slot()
    def stop_generation(self):
        thread = self._thread # Use local refs in case self._thread is nulled elsewhere
        worker = self._worker
        if not self._is_generating or not thread or not thread.isRunning():
            logger.warning("Task Manager: Stop requested but no active generation found.")
            return

        logger.info("Task Manager: Stop requested. Interrupting...")
        self._stop_requested = True
        if worker:
             worker.request_interruption()
        if thread:
             # thread.requestInterruption() # This might not be effective if thread is busy in Python code
             # Instead, rely on worker checking its flag and thread.quit()
             pass


    def _request_stop_and_wait(self, timeout_ms: int = 1000):
        thread = self._thread
        worker = self._worker
        if thread and thread.isRunning():
            logger.warning(f"Task Manager: Requesting old thread stop and waiting ({timeout_ms}ms)...")
            self._stop_requested = True # Set manager flag
            if worker: worker.request_interruption() # Set worker flag

            # Ask thread to quit, then wait
            thread.quit()
            if not thread.wait(timeout_ms):
                logger.error(f"Task Manager: Old thread did not finish quitting within timeout! Terminating.")
                thread.terminate()
                thread.wait(500) # Wait after terminate
            else:
                logger.info("Task Manager: Old thread finished quitting gracefully.")
        else:
             logger.debug("Task Manager: No running thread found during _request_stop_and_wait.")

        # Explicitly disconnect signals before nullifying refs
        if worker and thread:
            try: worker.stream_finished.disconnect(thread.quit)
            except RuntimeError: pass
            try: thread.finished.disconnect(worker.deleteLater)
            except RuntimeError: pass
            try: thread.finished.disconnect(thread.deleteLater)
            except RuntimeError: pass
            try: thread.finished.disconnect(self._on_thread_finished)
            except RuntimeError: pass
        # Nullify immediately after wait/terminate
        self._worker = None
        self._thread = None
        self._is_generating = False # Ensure state is reset
        logger.debug("Task Manager: Old thread references nulled after stop/wait.")


    @Slot()
    def _handle_worker_finished_signal(self):
        logger.debug("Task Manager: Worker's stream_finished signal received.")
        # Minimal logic here, actual cleanup is triggered by thread.finished

    @Slot()
    def _on_thread_finished(self):
        """Slot called AFTER the QThread event loop finishes."""
        # --- CRITICAL: Reset state BEFORE emitting generation_finished ---
        logger.debug("Task Manager: Thread finished signal received.")
        was_stopped = self._stop_requested
        thread_name = f"Thread_{id(self._thread)}" if self._thread else "N/A" # Get ID before reset

        logger.debug(f"Task Manager: Resetting state for {thread_name} before emitting finished.")
        self._reset_state() # <<< RESET STATE HERE

        logger.debug(f"Task Manager: Emitting generation_finished({was_stopped}) for {thread_name}.")
        self.generation_finished.emit(was_stopped) # <<< EMIT SIGNAL AFTER RESET
        # -------------------------------------------------------------
        logger.debug(f"Task Manager: _on_thread_finished completed for {thread_name}.")


    def _reset_state(self):
        """Resets the manager's internal references. IMPORTANT: Only call when safe."""
        logger.debug("Task Manager: Resetting internal state (references to None).")
        # Disconnect signals from worker/thread if they haven't been disconnected yet
        # This is defensive programming
        worker = self._worker
        thread = self._thread
        if worker:
            try: worker.status_update.disconnect(self.status_update)
            except RuntimeError: pass
            # Add disconnects for other worker signals if necessary
        # Nullify references
        self._worker = None
        self._thread = None
        self._is_generating = False
        # Keep _stop_requested until generation_finished is emitted in _on_thread_finished
        # self._stop_requested = False # Don't reset here

