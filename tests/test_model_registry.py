# tests/test_model_registry.py
import pytest
from unittest.mock import patch, MagicMock
import ollama # Import the real ollama to check for ResponseError

# Import the function to test
from pm.core.model_registry import resolve_context_limit, _ollama_ctx_fallback

# Mock ollama.show behavior
@patch('pm.core.model_registry.ollama.show')
def test_resolve_context_limit_ollama_fallback(mock_ollama_show):
    """Tests context limit resolution fallback for Ollama when ollama.show fails."""

    # --- Case 1: ollama.show raises ResponseError (e.g., model not found) ---
    test_model_not_found = "nonexistent-model:latest"
    mock_ollama_show.side_effect = ollama.ResponseError("Model not found", status_code=404)

    # Expect fallback based on name heuristic (should be low for unknown)
    limit = resolve_context_limit(provider='ollama', model=test_model_not_found)
    assert limit == 4096 # Default fallback

    # --- Case 2: ollama.show returns data, but no context keys ---
    test_model_no_ctx = "model-without-context-info:latest"
    mock_details_obj = MagicMock()
    # Ensure common context keys are NOT present
    del mock_details_obj.num_ctx
    del mock_details_obj.context_length
    del mock_details_obj.max_position_embeddings
    del mock_details_obj.sliding_window

    mock_show_response = MagicMock()
    mock_show_response.details = mock_details_obj
    mock_show_response.modelfile = "" # Empty modelfile
    mock_show_response.parameters = "" # Empty parameters string

    mock_ollama_show.side_effect = None # Reset side effect
    mock_ollama_show.return_value = mock_show_response

    # Expect fallback based on name heuristic
    limit_no_ctx = resolve_context_limit(provider='ollama', model=test_model_no_ctx)
    # Use the fallback function directly to see expected value
    expected_fallback = _ollama_ctx_fallback(test_model_no_ctx)
    assert limit_no_ctx == expected_fallback

    # --- Case 3: Test a specific name fallback ---
    test_model_70b = "some-llama-70b-model:latest"
    mock_ollama_show.side_effect = ollama.ResponseError("Another error", status_code=500)
    limit_70b = resolve_context_limit(provider='ollama', model=test_model_70b)
    assert limit_70b == 32768 # Based on the heuristic in _ollama_ctx_fallback

    # --- Case 4: Test llama3.1 fallback ---
    test_model_llama31 = "meta/llama3.1-8b-instruct"
    mock_ollama_show.side_effect = ollama.ResponseError("Yet another error", status_code=500)
    limit_llama31 = resolve_context_limit(provider='ollama', model=test_model_llama31)
    assert limit_llama31 == 128 * 1024 # 128k specific override

