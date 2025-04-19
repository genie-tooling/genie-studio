# tests/test_llm_service_provider.py
import pytest
from unittest.mock import MagicMock, patch, call
import ollama # Import for ResponseError

# Add spec=True to service patches
@patch('pm.core.llm_service_provider.ollama.Client')
@patch('pm.core.model_registry.ollama.show')
@patch('pm.core.llm_service_provider.QTimer', MagicMock())
@patch('pm.core.llm_service_provider.OllamaService', spec=True) # Add spec=True
@patch('pm.core.llm_service_provider.GeminiService', spec=True) # Add spec=True
@patch('pm.core.llm_service_provider.resolve_context_limit')
@patch('pm.core.llm_service_provider.SettingsService')
# Correct signature order again - based on patches that inject args (bottom-up)
def test_llm_provider_service_switching(MockSettingsService, mock_resolve_ctx, MockGeminiService_cls, MockOllamaService_cls, mock_ollama_show, mock_ollama_client):
    """Tests switching between Ollama and Gemini services based on settings."""
    from pm.core.llm_service_provider import LLMServiceProvider
    from pm.core.llm_service_provider import QTimer as MockQTimer # Access mock timer

    # --- Setup ---
    mock_settings = MockSettingsService.return_value
    settings_dict = {
        'provider': 'Ollama', 'model': 'llama3:8b', 'api_key': '',
        'temperature': 0.3, 'top_k': 40,
        'rag_summarizer_enabled': False,
    }
    mock_settings.get_setting.side_effect = lambda key, default=None: settings_dict.get(key, default)

    # Configure mock service *instances* returned by the mocked *classes*
    mock_ollama_instance = MockOllamaService_cls.return_value
    mock_ollama_instance.model = 'llama3:8b'
    mock_gemini_instance = MockGeminiService_cls.return_value
    mock_gemini_instance.model = 'gemini-pro'

    mock_resolve_ctx.side_effect = lambda provider, model: 8192 if provider == 'ollama' else 32768

    mock_ollama_client_instance = mock_ollama_client.return_value
    mock_ollama_client_instance.generate.return_value = {}

    provider = LLMServiceProvider(settings_service=mock_settings, parent=None)
    MockQTimer.singleShot.reset_mock()
    provider._connect_and_update()

    # --- Initial State (Ollama) ---
    # Check the instance type using the *mocked class*
    assert provider.get_model_service() is mock_ollama_instance
    # Check the class was called to create the instance
    MockOllamaService_cls.assert_called_once_with(model='llama3:8b')
    MockGeminiService_cls.assert_not_called()
    mock_resolve_ctx.assert_called_with('ollama', 'llama3:8b')

    # Reset mocks
    MockOllamaService_cls.reset_mock()
    MockGeminiService_cls.reset_mock()
    mock_resolve_ctx.reset_mock()
    MockQTimer.singleShot.reset_mock()
    mock_ollama_client.reset_mock()

    # --- Switch to Gemini ---
    print("Switching settings to Gemini...")
    settings_dict['provider'] = 'Gemini'
    settings_dict['model'] = 'gemini-pro'
    settings_dict['api_key'] = 'TEST_API_KEY'
    provider._update_services()

    # --- Check State (Gemini) ---
    assert provider.get_model_service() is mock_gemini_instance
    MockGeminiService_cls.assert_called_once_with(model='gemini-pro', api_key='TEST_API_KEY', temp=0.3, top_k=40)
    MockOllamaService_cls.assert_not_called()
    mock_resolve_ctx.assert_called_with('gemini', 'gemini-pro')

    # --- Check Ollama Unload ---
    MockQTimer.singleShot.assert_called()
    try:
        provider._request_ollama_unload('llama3:8b')
        mock_ollama_client.assert_called_once()
        mock_ollama_client_instance.generate.assert_called_once_with(
            model='llama3:8b', prompt="", stream=False, keep_alive=0
        )
    except Exception as e:
        pytest.fail(f"_request_ollama_unload failed during test: {e}")

