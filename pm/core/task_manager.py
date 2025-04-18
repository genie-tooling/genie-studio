# pm/core/task_manager.py
from PySide6.QtCore import QObject, Signal, Slot, QThread, QTimer
from loguru import logger
from pathlib import Path
from typing import List, Dict, Optional, Any

from .background_tasks import Worker
from .gemini_service import GeminiService
from .ollama_service import OllamaService
# Managers might not be needed directly if data is passed in
# from .workspace_manager import WorkspaceManager
# from .chat_manager import ChatManager


class BackgroundTaskManager(QObject):
    """Manages the lifecycle of background LLM tasks."""

    # --- Signals relayed from Worker or indicating state change ---
    generation_started = Signal()
    generation_finished = Signal(bool) # bool: True if stopped by user, False otherwise
    status_update = Signal(str)        # Relayed from Worker
    context_info = Signal(int, int)    # Relayed from Worker
    stream_chunk = Signal(str)         # Relayed from Worker
    stream_error = Signal(str)         # Relayed from Worker

    def __init__(self, settings: dict, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = settings # Keep a reference to main settings
        # Service references will be updated by MainWindow
        self.model_service: Optional[OllamaService | GeminiService] = None
        self.summarizer_service: Optional[OllamaService | GeminiService] = None

        self._thread: Optional[QThread] = None
        self._worker: Optional[Worker] = None
        self._is_generating: bool = False
        self._stop_requested: bool = False

    def set_services(self, model_service: Optional[Any], summarizer_service: Optional[Any]):
        """Update service references (called by MainWindow when services change)."""
        logger.debug("BackgroundTaskManager: Updating service references.")
        self.model_service = model_service
        self.summarizer_service = summarizer_service

    def is_busy(self) -> bool:
        """Returns True if a generation task is currently active."""
        return self._is_generating

    @Slot(list, list, Path)
    def start_generation(self,
                         history_snapshot: list[dict],
                         checked_file_paths: List[Path],
                         project_path: Path):
        """Starts the LLM generation process in a background thread."""
        if self._is_generating:
            logger.warning("Task Manager: Generation already in progress. Cannot start new task.")
            return
        if not self.model_service:
            logger.error("Task Manager: Cannot start generation, model service is not set.")
            self.stream_error.emit("Model service not available.") # Inform UI
            return

        # --- Stop and Clean Up Previous Thread if Exists ---
        # Should ideally not be necessary if state is managed correctly, but safety check
        if self._thread is not None and self._thread.isRunning():
            logger.warning("Task Manager: Previous thread found running unexpectedly. Attempting cleanup.")
            self._request_stop_and_wait() # Ensure old thread finishes

        logger.info("Task Manager: Initiating background worker thread...")
        self._is_generating = True
        self._stop_requested = False # Reset stop flag

        # --- Create Worker and Thread ---
        self._thread = QThread() # No parent needed, will be managed by deleteLater
        self._thread.setObjectName("LLMWorkerThread")
        self._worker = Worker(
            settings=self.settings.copy(), # Pass copy of settings
            history=history_snapshot,
            main_services={'model_service': self.model_service, 'summarizer_service': self.summarizer_service},
            checked_file_paths=checked_file_paths,
            project_path=project_path
        )
        self._worker.moveToThread(self._thread)

        # --- Connect Worker Signals to Manager Slots/Relay Signals ---
        self._worker.status_update.connect(self.status_update) # Relay
        self._worker.context_info.connect(self.context_info)   # Relay
        self._worker.stream_chunk.connect(self.stream_chunk)   # Relay
        self._worker.stream_error.connect(self.stream_error)   # Relay
        self._worker.stream_finished.connect(self._handle_worker_finished) # Internal handler

        # --- Connect Thread Signals ---
        self._thread.started.connect(self._worker.process)
        # Ensure thread quits when worker is done (either finished or error)
        self._worker.stream_finished.connect(self._thread.quit)
        # Schedule cleanup
        self._worker.stream_finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        # Connect thread finished signal for final state reset in manager
        self._thread.finished.connect(self._on_thread_finished)

        # --- Start Thread ---
        self._thread.start()
        logger.info(f"Task Manager: Started background worker thread ({self._thread.objectName()}).")
        self.generation_started.emit() # Signal UI that process has started

    @Slot()
    def stop_generation(self):
        """Requests the current background task to stop."""
        if not self._is_generating or not self._thread or not self._thread.isRunning():
            logger.warning("Task Manager: Stop requested but no active generation found.")
            return

        logger.info("Task Manager: Stop requested. Interrupting thread...")
        self._stop_requested = True
        self._thread.requestInterruption()
        # Don't reset self._is_generating here, let _handle_worker_finished do it.

    def _request_stop_and_wait(self, timeout_ms: int = 2000):
        """Requests stop and waits briefly for thread to finish (use cautiously)."""
        if self._thread and self._thread.isRunning():
             logger.warning(f"Task Manager: Requesting old thread stop and waiting ({timeout_ms}ms)...")
             self._stop_requested = True
             self._thread.requestInterruption()
             if not self._thread.wait(timeout_ms):
                  logger.error(f"Task Manager: Old thread did not finish within timeout! Forcing termination.")
                  self._thread.terminate() # Use as last resort
                  self._thread.wait() # Wait after terminate
             else:
                  logger.info("Task Manager: Old thread finished gracefully.")
        self._reset_state() # Ensure state is reset after waiting/termination

    @Slot()
    def _handle_worker_finished(self):
        """Handles the worker's finished signal (normal or stopped)."""
        logger.debug("Task Manager: Worker finished signal received.")
        # The generation_finished signal needs to know *if* it was stopped
        was_stopped = self._stop_requested
        self.generation_finished.emit(was_stopped)
        # State reset now happens in _on_thread_finished after thread truly exits

    @Slot()
    def _on_thread_finished(self):
        """Slot called when the QThread itself has finished execution."""
        # This is the definitive point where the thread's event loop has stopped
        thread_name = self._thread.objectName() if self._thread else "N/A"
        logger.info(f"Task Manager: Thread '{thread_name}' execution finished.")
        self._reset_state()

    def _reset_state(self):
        """Resets the manager's state after a task completes or is stopped."""
        logger.debug("Task Manager: Resetting internal state.")
        self._is_generating = False
        self._stop_requested = False
        self._worker = None # Allow GC
        self._thread = None # Allow GC

