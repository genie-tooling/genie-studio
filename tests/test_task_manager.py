# tests/test_task_manager.py
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer # Import QTimer if needed for delays

# Patch Worker and Services
@patch('pm.core.background_tasks.Worker')
@patch('pm.core.llm_service_provider.LLMServiceProvider')
@patch('pm.core.settings_service.SettingsService')
# Correct signature (no QThread)
def test_task_manager_start_stop(MockSettingsService, MockLLMProvider, MockWorker):
    """Tests basic start_generation, stop_generation, and is_busy state."""
    app = QApplication.instance() or QApplication([])
    from pm.core.task_manager import BackgroundTaskManager

    # --- Setup ---
    mock_settings = MockSettingsService.return_value
    mock_llm_provider = MockLLMProvider.return_value

    # --- CRITICAL: Ensure mock LLM provider returns a valid mock service ---
    mock_model_service = MagicMock(name="MockModelServiceInstance") # Create a mock *instance*
    mock_llm_provider.get_model_service.return_value = mock_model_service
    # --------------------------------------------------------------------
    mock_llm_provider.get_context_limit.return_value = 8192

    mock_worker_instance = MockWorker.return_value
    mock_worker_instance.assign_thread = MagicMock()
    mock_worker_instance.request_interruption = MagicMock()
    mock_worker_instance.process = MagicMock()
    mock_worker_instance.stream_finished = MagicMock()

    # Instantiate TaskManager
    task_manager = BackgroundTaskManager(
        settings_service=mock_settings,
        llm_provider=mock_llm_provider,
        parent=None
    )
    # Let TaskManager get the service itself upon start_generation or init if needed
    # task_manager.set_services(mock_model_service, None) # Call removed, let TM handle it

    # --- Test Start ---
    assert not task_manager.is_busy()
    # TaskManager should call llm_provider.get_model_service() internally now
    task_manager.start_generation(history_snapshot=[], checked_file_paths=[], project_path=Path('.'), disable_critic=False)

    # Check Worker was created and configured
    MockWorker.assert_called_once() # Now this should pass
    mock_worker_instance.assign_thread.assert_called_once()
    assert task_manager._thread is not None
    # Allow event loop to process thread start
    QApplication.processEvents()
    assert task_manager._thread.isRunning()
    assert task_manager.is_busy()
    # Check that get_model_service was called by TaskManager logic
    mock_llm_provider.get_model_service.assert_called()

    # --- Test Stop ---
    task_manager.stop_generation()
    mock_worker_instance.request_interruption.assert_called_once()

    # Force cleanup via internal method - waits for the real thread
    task_manager._request_stop_and_wait(timeout_ms=500)

    assert not task_manager.is_busy()
    assert task_manager._thread is None
    assert task_manager._worker is None

