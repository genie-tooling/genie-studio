# pm/core/task_manager.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread, QTimer, Qt
from loguru import logger
from pathlib import Path
from typing import List, Dict, Optional, Any

from .background_tasks import Worker
from .gemini_service import GeminiService
from .ollama_service import OllamaService
from .settings_service import SettingsService
# --- Import LLMServiceProvider ---
from .llm_service_provider import LLMServiceProvider
# --- Import DEFAULT_CONFIG for fallback ---
from .project_config import DEFAULT_CONFIG

class BackgroundTaskManager(QObject):
    """Manages the lifecycle of background LLM tasks."""

    generation_started = pyqtSignal()
    generation_finished = pyqtSignal(bool) # bool: True if stopped by user, False otherwise
    status_update = pyqtSignal(str)
    context_info = pyqtSignal(int, int)
    stream_chunk = pyqtSignal(str)
    stream_error = pyqtSignal(str)
    plan_generated = pyqtSignal(list)
    plan_critiqued = pyqtSignal(dict)
    plan_accepted = pyqtSignal(list)

    # --- MODIFIED: Accept LLMServiceProvider ---
    def __init__(self, settings_service: SettingsService, llm_provider: LLMServiceProvider, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings_service = settings_service
        self.llm_provider = llm_provider # Store the provider
        self.model_service: Optional[OllamaService | GeminiService] = None
        self.summarizer_service: Optional[OllamaService | GeminiService] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[Worker] = None
        self._is_generating: bool = False
        self._stop_requested: bool = False
        logger.info("TaskManager initialized.")

    def set_services(self, model_service: Optional[Any], summarizer_service: Optional[Any]):
        logger.debug("TaskManager: Updating service references.")
        self.model_service = model_service
        self.summarizer_service = summarizer_service

    def is_busy(self) -> bool:
        return self._is_generating

    @pyqtSlot(list, list, Path, bool)
    def start_generation(self,
                         history_snapshot: list[dict],
                         checked_file_paths: List[Path],
                         project_path: Path,
                         disable_critic: bool):
        if self._is_generating:
            logger.warning("Task Manager: Generation already in progress.")
            return
        if not self.model_service:
            logger.error("Task Manager: Cannot start generation, model service is not set."); self.stream_error.emit("Model service not available."); return
        if not self.settings_service:
            logger.error("Task Manager: Cannot start generation, settings service not set."); self.stream_error.emit("Settings service not available."); return
        # --- ADDED: Check for LLM Provider ---
        if not self.llm_provider:
            logger.error("Task Manager: Cannot start generation, LLM provider reference is missing."); self.stream_error.emit("LLM Provider not available."); return
        # ------------------------------------

        if self._thread is not None:
            logger.warning("Task Manager: Cleaning up previous thread/worker before starting new one.")
            self._request_stop_and_wait(timeout_ms=1000)
        if self._is_generating or self._thread is not None or self._worker is not None:
             logger.error("Task Manager: State not clean after cleanup attempt! Aborting start.")
             self._reset_state(emit_finished=True, finished_state=True); return

        logger.info(f"Task Manager: Initiating background worker thread (Critic Disabled: {disable_critic})...")
        self._is_generating = True
        self._stop_requested = False

        # --- Resolve the CORRECT context limit NOW ---
        try:
             resolved_limit = self.llm_provider.get_context_limit()
             logger.info(f"Task Manager: Resolved context limit for worker: {resolved_limit}")
        except Exception as e:
             logger.error(f"Task Manager: Failed to resolve context limit before worker start: {e}. Using default.")
             resolved_limit = DEFAULT_CONFIG.get('context_limit', 8192)
        # --------------------------------------------

        self._thread = QThread()
        self._thread.setObjectName("LLMWorkerThread")
        current_settings = self.settings_service.get_all_settings()

        # --- MODIFIED: Pass resolved_limit to Worker ---
        self._worker = Worker(
            settings=current_settings.copy(),
            history=history_snapshot,
            main_services={'model_service': self.model_service, 'summarizer_service': self.summarizer_service},
            checked_file_paths=checked_file_paths,
            project_path=project_path,
            disable_critic=disable_critic,
            resolved_context_limit=resolved_limit # Pass the correct limit
        )
        # ---------------------------------------------
        self._worker.assign_thread(self._thread)

        worker_obj = self._worker; thread_obj = self._thread
        worker_obj.moveToThread(thread_obj)

        # Connections (remain the same)
        worker_obj.status_update.connect(self.status_update, Qt.ConnectionType.QueuedConnection)
        worker_obj.context_info.connect(self.context_info, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_chunk.connect(self.stream_chunk, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_error.connect(self.stream_error, Qt.ConnectionType.QueuedConnection)
        worker_obj.stream_finished.connect(self._handle_worker_finished_pyqtSignal, Qt.ConnectionType.QueuedConnection)
        thread_obj.started.connect(worker_obj.process)
        worker_obj.stream_finished.connect(thread_obj.quit, Qt.ConnectionType.DirectConnection)
        thread_obj.finished.connect(worker_obj.deleteLater)
        thread_obj.finished.connect(thread_obj.deleteLater)
        thread_obj.finished.connect(self._on_thread_finished)

        thread_obj.start()
        logger.info(f"Task Manager: Started background worker thread ({thread_obj.objectName()}).")
        self.generation_started.emit()

    # --- stop_generation, _request_stop_and_wait, _disconnect_pyqtSignals, _handle_worker_finished_pyqtSignal, _on_thread_finished, _finalize_generation, _reset_state ---
    # (These methods remain unchanged from the previous version)
    @pyqtSlot()
    def stop_generation(self):
        thread = self._thread; worker = self._worker
        if not self._is_generating: logger.warning("Task Manager: Stop requested but not generating."); return
        if not thread or not thread.isRunning():
            logger.warning("Task Manager: Stop requested but no active thread/running.")
            if self._is_generating: self._reset_state(emit_finished=True, finished_state=True)
            return
        logger.info(f"Task Manager: Stop requested for thread {thread.objectName()}. Requesting interruption...")
        self._stop_requested = True
        if worker: QTimer.singleShot(0, worker.request_interruption)
        else: logger.warning("Task Manager: Stop requested, but worker object is None.")

    def _request_stop_and_wait(self, timeout_ms: int = 1000):
        thread_to_stop = self._thread; worker_to_stop = self._worker
        thread_id = thread_to_stop.objectName() if thread_to_stop else "N/A"; state_was_generating = self._is_generating
        if thread_to_stop and thread_to_stop.isRunning():
            logger.debug(f"Task Manager ({thread_id}): Requesting stop and wait ({timeout_ms}ms)...")
            self._stop_requested = True
            if worker_to_stop: QTimer.singleShot(0, worker_to_stop.request_interruption)
            self._disconnect_pyqtSignals(worker_to_stop, thread_to_stop)
            if not thread_to_stop.wait(timeout_ms):
                logger.error(f"Task Manager ({thread_id}): Thread did not finish quitting within timeout! Terminating.")
                thread_to_stop.terminate(); thread_to_stop.wait(500)
            else: logger.debug(f"Task Manager ({thread_id}): Thread finished quitting gracefully.")
        elif thread_to_stop:
             logger.debug(f"Task Manager ({thread_id}): Thread already finished during stop/wait.")
             self._disconnect_pyqtSignals(worker_to_stop, thread_to_stop)
        else: logger.debug(f"Task Manager (N/A): No thread found during _request_stop_and_wait.")
        self._worker = None; self._thread = None
        if state_was_generating: self._is_generating = False
        logger.debug(f"Task Manager: Stop/wait sequence complete for {thread_id}. References cleared.")

    def _disconnect_pyqtSignals(self, worker, thread):
        if not worker and not thread: return
        logger.trace("Task Manager: Disconnecting pyqtSignals...")
        if worker:
            try: worker.status_update.disconnect(self.status_update)
            except RuntimeError: pass
            try: worker.context_info.disconnect(self.context_info)
            except RuntimeError: pass
            try: worker.stream_chunk.disconnect(self.stream_chunk)
            except RuntimeError: pass
            try: worker.stream_error.disconnect(self.stream_error)
            except RuntimeError: pass
            try: worker.stream_finished.disconnect(self._handle_worker_finished_pyqtSignal)
            except RuntimeError: pass
            if thread:
                 try: worker.stream_finished.disconnect(thread.quit)
                 except RuntimeError: pass
        if thread:
            if worker:
                 try: thread.started.disconnect(worker.process)
                 except RuntimeError: pass
            try: thread.finished.disconnect(self._on_thread_finished)
            except RuntimeError: pass
        logger.trace("Task Manager: pyqtSignal disconnection attempt complete.")

    @pyqtSlot()
    def _handle_worker_finished_pyqtSignal(self):
        thread_id = self._thread.objectName() if self._thread else "N/A (thread gone)"
        logger.debug(f"Task Manager ({thread_id}): Worker's stream_finished pyqtSignal received.")

    @pyqtSlot()
    def _on_thread_finished(self):
        finished_thread = self.sender()
        thread_id = finished_thread.objectName() if isinstance(finished_thread, QThread) else "UnknownThread"
        logger.debug(f"Task Manager ({thread_id}): Thread finished pyqtSignal received.")
        QTimer.singleShot(0, lambda tid=thread_id: self._finalize_generation(tid))

    def _finalize_generation(self, thread_id_info: str):
        logger.debug(f"Task Manager: Finalizing generation for {thread_id_info}.")
        if not self._is_generating:
            logger.warning(f"Task Manager ({thread_id_info}): Finalize called, but not generating.")
            self._reset_state(emit_finished=False)
            return
        was_stopped = self._stop_requested
        self._disconnect_pyqtSignals(self._worker, self._thread)
        self._worker = None; self._thread = None
        self._is_generating = False; self._stop_requested = False
        logger.debug(f"Task Manager ({thread_id_info}): Emitting generation_finished(stopped={was_stopped}).")
        self.generation_finished.emit(was_stopped)
        logger.debug(f"Task Manager: Finalization complete for {thread_id_info}.")

    def _reset_state(self, emit_finished: bool = False, finished_state: bool = True):
        logger.warning("Task Manager: Performing state reset.")
        self._disconnect_pyqtSignals(self._worker, self._thread)
        self._worker = None; self._thread = None
        self._is_generating = False; self._stop_requested = False
        if emit_finished:
             logger.warning("Task Manager: Emitting generation_finished due to reset.")
             self.generation_finished.emit(finished_state)
        logger.warning("Task Manager: State reset complete.")

