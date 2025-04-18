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
        # Ensure previous thread/worker are fully stopped and cleaned up
        if self._thread is not None:
            logger.warning("Task Manager: Cleaning up previous thread/worker before starting new one.")
            self._request_stop_and_wait(timeout_ms=1000) # Wait a bit longer if needed
        # Double check state after waiting
        if self._is_generating or self._thread is not None or self._worker is not None:
             logger.error("Task Manager: State not clean after cleanup attempt! Aborting start.")
             # Force reset state just in case
             self._worker = None
             self._thread = None
             self._is_generating = False
             self._stop_requested = False
             self.generation_finished.emit(True) # Emit finished(stopped) to reset UI
             return
        # -----------------------------------------

        logger.info("Task Manager: Initiating background worker thread...")
        self._is_generating = True
        self._stop_requested = False # Reset stop flag for new task

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
        # --- Assign thread reference to worker ---
        self._worker.assign_thread(self._thread)
        # -----------------------------------------

        worker_obj = self._worker # Local reference for connections
        thread_obj = self._thread # Local reference for connections

        worker_obj.moveToThread(thread_obj)

        # --- Connections ---
        worker_obj.status_update.connect(self.status_update, Qt.ConnectionType.QueuedConnection)
        worker_obj.context_info.connect(self.context_info, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_chunk.connect(self.stream_chunk, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_error.connect(self.stream_error, Qt.ConnectionType.QueuedConnection)
        # Connect worker finish signal to trigger cleanup sequence
        worker_obj.stream_finished.connect(self._handle_worker_finished_signal, Qt.ConnectionType.QueuedConnection)

        # Thread lifecycle
        thread_obj.started.connect(worker_obj.process)
        # Worker finishing tells thread event loop to stop
        worker_obj.stream_finished.connect(thread_obj.quit, Qt.ConnectionType.DirectConnection)
        # Schedule objects for deletion *after* the thread's event loop finishes
        thread_obj.finished.connect(worker_obj.deleteLater)
        thread_obj.finished.connect(thread_obj.deleteLater)
        # Connect manager state reset *after* deleteLater is scheduled.
        thread_obj.finished.connect(self._on_thread_finished)
        # ---------------------------------------------------------------------

        thread_obj.start()
        logger.info(f"Task Manager: Started background worker thread ({thread_obj.objectName()}).")
        self.generation_started.emit() # Emit start *after* setup is complete

    @Slot()
    def stop_generation(self):
        thread = self._thread # Use local refs
        worker = self._worker

        if not self._is_generating:
            logger.warning("Task Manager: Stop requested but not generating.")
            return
        if not thread or not thread.isRunning():
            logger.warning("Task Manager: Stop requested but no active thread found/running.")
            # Force state reset if inconsistent
            if self._is_generating:
                self._reset_state()
                self.generation_finished.emit(True) # Indicate stopped
            return

        logger.info(f"Task Manager: Stop requested for thread {thread.objectName()}. Interrupting worker...")
        self._stop_requested = True
        if worker:
             worker.request_interruption() # Signal worker to stop its task loop
        else:
             logger.warning("Task Manager: Stop requested, but worker object is None.")

        # Don't call thread.quit() here directly. Let the worker finish its current step
        # and emit stream_finished, which is connected to thread.quit.
        # Relying on the worker's interrupt check is safer.


    def _request_stop_and_wait(self, timeout_ms: int = 1000):
        """Internal helper to request stop and wait for thread completion."""
        thread_to_stop = self._thread
        worker_to_stop = self._worker
        thread_id = thread_to_stop.objectName() if thread_to_stop else "N/A"

        if thread_to_stop and thread_to_stop.isRunning():
            logger.warning(f"Task Manager: Requesting stop for old thread {thread_id} and waiting ({timeout_ms}ms)...")
            self._stop_requested = True # Set manager flag
            if worker_to_stop:
                worker_to_stop.request_interruption() # Set worker flag

            # Ask thread to quit its event loop (triggered by worker finishing)
            # Don't call thread_to_stop.quit() directly here unless worker is unresponsive

            # Wait for the thread's 'finished' signal (up to timeout)
            if not thread_to_stop.wait(timeout_ms):
                logger.error(f"Task Manager: Old thread {thread_id} did not finish quitting within timeout! Terminating.")
                thread_to_stop.terminate()
                thread_to_stop.wait(500) # Brief wait after terminate
            else:
                logger.info(f"Task Manager: Old thread {thread_id} finished quitting gracefully.")
        else:
             logger.debug(f"Task Manager: No running thread found for {thread_id} during _request_stop_and_wait.")

        # --- Explicitly disconnect signals before nullifying refs ---
        # This prevents signals from being processed after objects might be invalid
        self._disconnect_signals(worker_to_stop, thread_to_stop)

        # Nullify immediately after wait/terminate and disconnect
        self._worker = None
        self._thread = None
        self._is_generating = False # Ensure state is reset
        # Don't reset self._stop_requested here, it's needed by _on_thread_finished

        logger.debug(f"Task Manager: Old thread {thread_id} references nulled after stop/wait.")

    def _disconnect_signals(self, worker, thread):
        """Safely disconnect signals between worker, thread, and manager."""
        if not worker and not thread:
            return
        logger.trace("Task Manager: Disconnecting signals...")
        if worker:
            try: worker.status_update.disconnect(self.status_update)
            except RuntimeError: pass
            try: worker.context_info.disconnect(self.context_info)
            except RuntimeError: pass
            try: worker.stream_chunk.disconnect(self.stream_chunk)
            except RuntimeError: pass
            try: worker.stream_error.disconnect(self.stream_error)
            except RuntimeError: pass
            try: worker.stream_finished.disconnect(self._handle_worker_finished_signal)
            except RuntimeError: pass
            if thread:
                 try: worker.stream_finished.disconnect(thread.quit)
                 except RuntimeError: pass

        if thread:
            if worker:
                 try: thread.started.disconnect(worker.process)
                 except RuntimeError: pass
                 try: thread.finished.disconnect(worker.deleteLater)
                 except RuntimeError: pass
            try: thread.finished.disconnect(thread.deleteLater)
            except RuntimeError: pass
            try: thread.finished.disconnect(self._on_thread_finished)
            except RuntimeError: pass
        logger.trace("Task Manager: Signal disconnection attempt complete.")


    @Slot()
    def _handle_worker_finished_signal(self):
        """Slot called when the worker's task logic is complete."""
        logger.debug("Task Manager: Worker's stream_finished signal received.")
        # This signal should trigger thread.quit via the DirectConnection.
        # The thread.finished signal will handle the rest of the cleanup.

    @Slot()
    def _on_thread_finished(self):
        """Slot called AFTER the QThread event loop finishes."""
        thread_id = f"Thread_{id(self._thread)}" if self._thread else "N/A (already gone)"
        logger.debug(f"Task Manager: Thread finished signal received for {thread_id}.")

        # State reset should happen *after* this signal handler completes,
        # as the deleteLater calls for worker/thread are scheduled based on this signal.
        # The _reset_state method is now primarily for emergency/forced cleanup.

        # Determine if stop was requested *before* nullifying state
        was_stopped = self._stop_requested

        # Schedule the final state reset and signal emission using a zero-timer
        # This ensures it happens after the current event processing is done.
        QTimer.singleShot(0, lambda: self._finalize_generation(was_stopped, thread_id))

    def _finalize_generation(self, was_stopped: bool, thread_id_info: str):
        """Called via QTimer to perform final state reset and signal emission."""
        logger.debug(f"Task Manager: Finalizing generation for {thread_id_info}.")

        # It's now safer to nullify references as deleteLater should have been scheduled
        current_thread = self._thread # Keep local refs just in case
        current_worker = self._worker

        # Disconnect signals again defensively before nullifying
        self._disconnect_signals(current_worker, current_thread)

        self._worker = None
        self._thread = None
        self._is_generating = False
        # _stop_requested is handled by passing was_stopped

        logger.debug(f"Task Manager: Emitting generation_finished({was_stopped}) for {thread_id_info}.")
        self.generation_finished.emit(was_stopped)
        logger.debug(f"Task Manager: Finalization complete for {thread_id_info}.")


    def _reset_state(self):
        """Resets the manager's internal references. Primarily for forced/emergency cleanup."""
        logger.warning("Task Manager: Performing forced state reset.")
        # Disconnect signals defensively
        self._disconnect_signals(self._worker, self._thread)
        # Nullify references
        self._worker = None
        self._thread = None
        self._is_generating = False
        self._stop_requested = False
        logger.warning("Task Manager: Forced state reset complete.")

