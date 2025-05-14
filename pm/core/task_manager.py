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
    # Optional intermediate signals (passed through from Worker)
    plan_generated = Signal(list)
    plan_critiqued = Signal(dict)
    plan_accepted = Signal(list)

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

    # <<< MODIFIED SIGNATURE to accept disable_critic flag >>>
    @Slot(list, list, Path, bool)
    def start_generation(self,
                         history_snapshot: list[dict],
                         checked_file_paths: List[Path],
                         project_path: Path,
                         disable_critic: bool): # <<< NEW PARAMETER <<<
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
            logger.warning("Task Manager: Cleaning up previous thread/worker before starting new one.")
            self._request_stop_and_wait(timeout_ms=1000)
        if self._is_generating or self._thread is not None or self._worker is not None:
             logger.error("Task Manager: State not clean after cleanup attempt! Aborting start.")
             self._reset_state()
             self.generation_finished.emit(True)
             return
        # -----------------------------------------

        logger.info(f"Task Manager: Initiating background worker thread (Critic Disabled: {disable_critic})...")
        self._is_generating = True
        self._stop_requested = False

        self._thread = QThread()
        self._thread.setObjectName("LLMWorkerThread")
        current_settings = self.settings_service.get_all_settings()

        # <<< PASS disable_critic to Worker constructor >>>
        self._worker = Worker(
            settings=current_settings.copy(),
            history=history_snapshot,
            main_services={'model_service': self.model_service, 'summarizer_service': self.summarizer_service},
            checked_file_paths=checked_file_paths,
            project_path=project_path,
            disable_critic=disable_critic # <<< PASS FLAG HERE <<<
        )
        self._worker.assign_thread(self._thread)

        worker_obj = self._worker
        thread_obj = self._thread

        worker_obj.moveToThread(thread_obj)

        # --- Connections ---
        worker_obj.status_update.connect(self.status_update, Qt.ConnectionType.QueuedConnection)
        worker_obj.context_info.connect(self.context_info, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_chunk.connect(self.stream_chunk, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_error.connect(self.stream_error, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_finished.connect(self._handle_worker_finished_signal, Qt.ConnectionType.QueuedConnection)

        # --- Optional: Connect intermediate signals ---
        # worker_obj.plan_generated.connect(self.plan_generated, Qt.ConnectionType.QueuedConnection)
        # worker_obj.plan_critiqued.connect(self.plan_critiqued, Qt.ConnectionType.QueuedConnection)
        # worker_obj.plan_accepted.connect(self.plan_accepted, Qt.ConnectionType.QueuedConnection)
        # --- End Optional Connections ---

        # Thread lifecycle
        thread_obj.started.connect(worker_obj.process)
        worker_obj.stream_finished.connect(thread_obj.quit, Qt.ConnectionType.DirectConnection)
        thread_obj.finished.connect(worker_obj.deleteLater)
        thread_obj.finished.connect(thread_obj.deleteLater)
        thread_obj.finished.connect(self._on_thread_finished)

        thread_obj.start()
        logger.info(f"Task Manager: Started background worker thread ({thread_obj.objectName()}).")
        self.generation_started.emit()

    @Slot()
    def stop_generation(self):
        thread = self._thread
        worker = self._worker

        if not self._is_generating:
            logger.warning("Task Manager: Stop requested but not generating.")
            return
        if not thread or not thread.isRunning():
            logger.warning("Task Manager: Stop requested but no active thread found/running.")
            if self._is_generating:
                self._reset_state()
                self.generation_finished.emit(True)
            return

        logger.info(f"Task Manager: Stop requested for thread {thread.objectName()}. Interrupting worker...")
        self._stop_requested = True
        if worker:
             worker.request_interruption()
        else:
             logger.warning("Task Manager: Stop requested, but worker object is None.")

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

            if not thread_to_stop.wait(timeout_ms):
                logger.error(f"Task Manager: Old thread {thread_id} did not finish quitting within timeout! Terminating.")
                thread_to_stop.terminate()
                thread_to_stop.wait(500)
            else:
                logger.info(f"Task Manager: Old thread {thread_id} finished quitting gracefully.")
        else:
             logger.debug(f"Task Manager: No running thread found for {thread_id} during _request_stop_and_wait.")

        self._disconnect_signals(worker_to_stop, thread_to_stop)

        self._worker = None
        self._thread = None
        self._is_generating = False

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
            # --- Optional: Disconnect intermediate signals ---
            # try: worker.plan_generated.disconnect(self.plan_generated)
            # except RuntimeError: pass
            # try: worker.plan_critiqued.disconnect(self.plan_critiqued)
            # except RuntimeError: pass
            # try: worker.plan_accepted.disconnect(self.plan_accepted)
            # except RuntimeError: pass
            # --- End Optional ---
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
        # Thread quit is handled by DirectConnection

    @Slot()
    def _on_thread_finished(self):
        """Slot called AFTER the QThread event loop finishes."""
        thread_id = f"Thread_{id(self._thread)}" if self._thread else "N/A (already gone)"
        logger.debug(f"Task Manager: Thread finished signal received for {thread_id}.")
        was_stopped = self._stop_requested
        QTimer.singleShot(0, lambda: self._finalize_generation(was_stopped, thread_id))

    def _finalize_generation(self, was_stopped: bool, thread_id_info: str):
        """Called via QTimer to perform final state reset and signal emission."""
        logger.debug(f"Task Manager: Finalizing generation for {thread_id_info}.")
        current_thread = self._thread
        current_worker = self._worker
        self._disconnect_signals(current_worker, current_thread)
        self._worker = None
        self._thread = None
        self._is_generating = False
        # self._stop_requested = False # Reset stop flag here

        logger.debug(f"Task Manager: Emitting generation_finished({was_stopped}) for {thread_id_info}.")
        self.generation_finished.emit(was_stopped)
        logger.debug(f"Task Manager: Finalization complete for {thread_id_info}.")


    def _reset_state(self):
        """Resets the manager's internal references. Primarily for forced/emergency cleanup."""
        logger.warning("Task Manager: Performing forced state reset.")
        self._disconnect_signals(self._worker, self._thread)
        self._worker = None
        self._thread = None
        self._is_generating = False
        self._stop_requested = False
        logger.warning("Task Manager: Forced state reset complete.")
