# tests/conftest.py
import pytest
from unittest.mock import patch

# Basic fixtures can be added here later if needed
# Example: Mocking external services

# @pytest.fixture(autouse=True)
# def mock_settings():
#     """Automatically mock settings loading/saving for most tests."""
#     with patch('pm.core.settings_service.SettingsService.load_project', return_value=True), \
#          patch('pm.core.settings_service.SettingsService.save_settings', return_value=True):
#         yield

# @pytest.fixture
# def mock_llm_service():
#     """Provides a mock LLM service."""
#     mock_service = MagicMock()
#     mock_service.send.return_value = "Mocked LLM response."
#     mock_service.stream.return_value = ["Mocked ", "LLM ", "stream."]
#     return mock_service

