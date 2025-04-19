# tests/test_app_init.py
import pytest
from unittest.mock import patch, MagicMock

# Minimal test to see if AppCore initializes without crashing
# This will likely require mocking filesystem access and external services in conftest.py
# for more meaningful testing later.

@patch('pm.core.model_registry.list_models', return_value=['mock_model:latest']) # Mock model listing
@patch('pm.core.model_registry.resolve_context_limit', return_value=4096) # Mock context resolution
@patch('pm.core.settings_service.SettingsService._validate_config', side_effect=lambda x: (x, False)) # Bypass complex validation
@patch('pm.core.settings_service.SettingsService.load_project', return_value=True) # Mock project loading
@patch('pm.core.ollama_service.OllamaService.__init__', return_value=None) # Mock Ollama init
@patch('pm.core.gemini_service.GeminiService.__init__', return_value=None) # Mock Gemini init
def test_app_core_initialization(mock_gemini_init, mock_ollama_init, mock_load, mock_validate, mock_resolve, mock_list):
    """Tests basic initialization of AppCore."""
    try:
        # Mock QObject parent if necessary, or run headlessly
        from pm.core.app_core import AppCore
        # You might need to mock QObject if running without Qt event loop
        # with patch('PyQt6.QtCore.QObject.__init__', return_value=None):
        core = AppCore(parent=None) # Pass None as parent for basic test
        assert core is not None
        assert core.settings is not None
        assert core.llm is not None
        assert core.workspace is not None
        assert core.chat is not None
        assert core.tasks is not None
    except Exception as e:
        pytest.fail(f"AppCore initialization failed: {e}")

# Placeholder for basic MainWindow tests (would require more mocking)
# @patch('pm.ui.main_window.QApplication')
# @patch('pm.ui.main_window.QMainWindow')
# def test_main_window_init(mock_qmainwindow, mock_qapplication):
#     """ Placeholder: Tests basic initialization of MainWindow (requires significant mocking) """
#     # This kind of test is complex without a running event loop or extensive patching.
#     # from pm.ui.main_window import MainWindow
#     # try:
#     #     # Need to mock AppCore and many UI elements/handlers
#     #     window = MainWindow()
#     #     assert window is not None
#     # except Exception as e:
#     #     pytest.fail(f"MainWindow basic initialization failed: {e}")
#     pass # Keep as placeholder

