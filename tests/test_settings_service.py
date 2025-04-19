# tests/test_settings_service.py
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Assuming DEFAULT_CONFIG is importable or mockable
MOCK_DEFAULT_CONFIG = {
    'provider': 'Ollama', 'model': 'llama3:8b', 'temperature': 0.3,
    'top_k': 40, 'context_limit': 8192, 'patch_mode': True,
    'rag_similarity_threshold': 0.30, 'user_prompts': [],
    'syntax_highlighting_style': 'native',
    'rag_ranking_model_name': 'all-MiniLM-L6-v2', 'rag_dir_max_depth': 3,
    'rag_dir_include_patterns': ['*'], 'rag_dir_exclude_patterns': [],
    'api_key': '', 'rag_bing_api_key': '', 'rag_google_api_key': '',
    'rag_google_cse_id': '', 'disable_critic_workflow': False,
    'editor_font': 'Fira Code', 'editor_font_size': 11, 'theme': 'Dark',
    'last_project_path': str(Path.cwd()), 'rag_local_sources': [],
    # Add ALL keys from the real DEFAULT_CONFIG that are accessed or validated
}

MOCK_AVAILABLE_STYLES = ['native', 'default', 'friendly']
MOCK_AVAILABLE_RAG_MODELS = ['all-MiniLM-L6-v2', 'other-model']

@patch('pm.core.settings_service.DEFAULT_CONFIG', MOCK_DEFAULT_CONFIG)
@patch('pm.core.settings_service.AVAILABLE_RAG_MODELS', MOCK_AVAILABLE_RAG_MODELS)
# @patch('PyQt6.QtCore.QObject.__init__', return_value=None) # REMOVED: Let real QObject init run
def test_set_setting_validation():
    """Tests the validation logic within SettingsService.set_setting."""
    # Must import AFTER patches are applied if they affect imports
    from pm.core.settings_service import SettingsService

    # --- Setup ---
    # No need to mock parent if QObject init runs, pass None or a dummy QObject if required
    # Note: If SettingsService directly creates other QObjects internally without parent,
    # a QApplication instance might be needed for the test environment.
    # For now, assume parent=None works.
    service = SettingsService(parent=None)
    service._settings = MOCK_DEFAULT_CONFIG.copy()
    service._project_path = Path('/fake/project')

    # --- Test Cases ---
    # Valid type and value
    assert service.get_setting('temperature') == 0.3
    service.set_setting('temperature', 0.8)
    assert service.get_setting('temperature') == 0.8

    # Valid type coercion (int -> float)
    service.set_setting('temperature', 1) # Should become 1.0
    assert service.get_setting('temperature') == 1.0
    assert isinstance(service.get_setting('temperature'), float)

    # Invalid type (string -> float where string is not numeric) - Should be rejected
    initial_temp = service.get_setting('temperature')
    service.set_setting('temperature', "not-a-number")
    assert service.get_setting('temperature') == initial_temp # Should remain unchanged

    # Invalid type (list -> float) - Should be rejected
    service.set_setting('temperature', [0.5])
    assert service.get_setting('temperature') == initial_temp # Should remain unchanged

    # Valid specific value (syntax style)
    service.set_setting('syntax_highlighting_style', 'friendly')
    assert service.get_setting('syntax_highlighting_style') == 'friendly'

    # Invalid specific value (syntax style) - Should be rejected
    service.set_setting('syntax_highlighting_style', 'invalid-style')
    assert service.get_setting('syntax_highlighting_style') == 'friendly' # Should remain unchanged

    # Valid specific value (RAG model)
    service.set_setting('rag_ranking_model_name', 'other-model')
    assert service.get_setting('rag_ranking_model_name') == 'other-model'

    # Invalid specific value (RAG model) - Should be rejected
    service.set_setting('rag_ranking_model_name', 'unknown-model')
    assert service.get_setting('rag_ranking_model_name') == 'other-model' # Should remain unchanged

    # Valid specific value (RAG threshold)
    service.set_setting('rag_similarity_threshold', 0.95)
    assert service.get_setting('rag_similarity_threshold') == 0.95

    # Invalid specific value (RAG threshold - out of range) - Should be rejected
    service.set_setting('rag_similarity_threshold', 1.5)
    assert service.get_setting('rag_similarity_threshold') == 0.95 # Should remain unchanged

    # Unknown key - Should be rejected
    service.set_setting('unknown_key', 'some_value')
    assert 'unknown_key' not in service._settings # Should not be added

    # Valid list assignment
    new_prompts = [{'id': '1', 'name': 'p1', 'content': 'c1'}]
    service.set_setting('user_prompts', new_prompts)
    assert service.get_setting('user_prompts') == new_prompts

    # Invalid list assignment (assigning dict to list) - Should be rejected
    service.set_setting('user_prompts', {'id': '2'})
    assert service.get_setting('user_prompts') == new_prompts # Should remain unchanged

@patch('pm.core.settings_service.DEFAULT_CONFIG', MOCK_DEFAULT_CONFIG)
@patch('pm.core.settings_service.AVAILABLE_RAG_MODELS', MOCK_AVAILABLE_RAG_MODELS)
def test_add_delete_prompt():
    """Tests adding and deleting user prompts via SettingsService."""
    from pm.core.settings_service import SettingsService

    service = SettingsService(parent=None)
    service._settings = MOCK_DEFAULT_CONFIG.copy()
    service._project_path = Path('/fake/project')

    initial_prompts = service.get_user_prompts()
    assert len(initial_prompts) == 0

    # --- Add Prompt 1 ---
    prompt1_data = {'id': 'id1', 'name': 'Prompt One', 'content': 'Content 1'}
    added1 = service.add_prompt(prompt1_data.copy()) # Pass copy
    assert added1 is True
    prompts_after_add1 = service.get_user_prompts()
    assert len(prompts_after_add1) == 1
    assert prompts_after_add1[0]['id'] == 'id1'
    assert prompts_after_add1[0]['name'] == 'Prompt One'

    # --- Add Prompt 2 ---
    prompt2_data = {'id': 'id2', 'name': 'Prompt Two', 'content': 'Content 2'}
    added2 = service.add_prompt(prompt2_data.copy())
    assert added2 is True
    prompts_after_add2 = service.get_user_prompts()
    assert len(prompts_after_add2) == 2
    assert prompts_after_add2[1]['id'] == 'id2'
    assert prompts_after_add2[1]['name'] == 'Prompt Two'

    # --- Add Prompt with Duplicate ID (should regenerate) ---
    prompt3_data_dup = {'id': 'id1', 'name': 'Duplicate ID Prompt', 'content': 'Content 3'}
    added3 = service.add_prompt(prompt3_data_dup.copy())
    assert added3 is True
    prompts_after_add3 = service.get_user_prompts()
    assert len(prompts_after_add3) == 3
    # Find the third prompt (ID will be different from 'id1')
    third_prompt = next(p for p in prompts_after_add3 if p['name'] == 'Duplicate ID Prompt')
    assert third_prompt['id'] != 'id1'
    assert third_prompt['name'] == 'Duplicate ID Prompt'

    # --- Delete Prompt 1 ---
    deleted1 = service.delete_prompt('id1')
    assert deleted1 is True
    prompts_after_del1 = service.get_user_prompts()
    assert len(prompts_after_del1) == 2
    assert not any(p['id'] == 'id1' for p in prompts_after_del1)
    assert any(p['id'] == 'id2' for p in prompts_after_del1) # id2 should still be there
    assert any(p['id'] == third_prompt['id'] for p in prompts_after_del1) # Regenerated ID should be there

    # --- Delete Non-existent Prompt ---
    deleted_nonexistent = service.delete_prompt('id_does_not_exist')
    assert deleted_nonexistent is False
    assert len(service.get_user_prompts()) == 2 # Length should not change

