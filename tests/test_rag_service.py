# tests/test_rag_service.py
import pytest
from unittest.mock import patch, MagicMock

MOCK_MODEL_NAME = 'mock-st-model'

# Patch where SentenceTransformer and util are likely imported from
@patch('sentence_transformers.util')
@patch('sentence_transformers.SentenceTransformer')
@patch('pm.core.rag_service._has_sentence_transformers', True)
# Correct signature order (matches decorators bottom-up)
def test_filter_and_rank_results_basic(mock_has_st_patch, MockSentenceTransformer_patch, mock_util_patch): # Renamed last arg
    """Tests basic ranking and threshold filtering."""
    from pm.core.rag_service import filter_and_rank_results

    # --- Setup Mocks (Use the correctly named arguments) ---
    mock_st_instance = MockSentenceTransformer_patch.return_value
    mock_st_instance.encode.return_value = MagicMock()

    mock_util_patch.semantic_search.return_value = [ # Configure the correct mock name
        [{'corpus_id': 2, 'score': 0.85}, {'corpus_id': 0, 'score': 0.75}, {'corpus_id': 1, 'score': 0.55}]
    ]

    # --- Test Data ---
    query = "test query"
    results_in = [
        {'url': 'url1', 'title': 'Result A', 'text_snippet': 'Relevant snippet about test.', 'source': 'web'},
        {'url': 'url2', 'title': 'Result B', 'text_snippet': 'Less relevant content.', 'source': 'web'},
        {'url': 'url3', 'title': 'Result C', 'text_snippet': 'Highly relevant test info.', 'source': 'git'},
        {'url': 'url4', 'title': 'Result D', 'text_snippet': '', 'source': 'web'},
    ]
    mock_settings = {
        'rag_ranking_model_name': MOCK_MODEL_NAME,
        'rag_similarity_threshold': 0.60,
    }
    max_results = 5

    # --- Action ---
    ranked_results = filter_and_rank_results(
        results=results_in,
        query=query,
        max_results_to_return=max_results,
        settings=mock_settings
    )

    # --- Assertions ---
    MockSentenceTransformer_patch.assert_called_once_with(MOCK_MODEL_NAME)
    assert mock_st_instance.encode.call_count == 2
    mock_util_patch.semantic_search.assert_called_once() # Use correct mock name

    assert len(ranked_results) == 2
    assert ranked_results[0]['url'] == 'url3'
    assert ranked_results[0]['score'] == 0.85
    assert ranked_results[1]['url'] == 'url1'
    assert ranked_results[1]['score'] == 0.75

