# tests/test_token_utils.py
import pytest
from unittest.mock import patch

# Assume tiktoken might be unavailable in some test environments
# Mock it to test the fallback mechanism
try:
    # Attempt to import, this might fail if tiktoken isn't installed
    import tiktoken
    from pm.core.token_utils import count_tokens
    TIKTOKEN_AVAILABLE = True
except ImportError:
    # If tiktoken is not installed at all, define a dummy function
    # and ensure count_tokens exists for the fallback test
    def count_tokens(text: str, model: str = "cl100k_base") -> int:
        # Simulate the fallback logic directly
        return len(text.split())
    TIKTOKEN_AVAILABLE = False

@pytest.mark.skipif(not TIKTOKEN_AVAILABLE, reason="tiktoken library not installed")
def test_count_tokens_with_tiktoken():
    """Tests token counting using tiktoken (if available)."""
    # Re-import within the test if necessary to ensure correct version is used
    from pm.core.token_utils import count_tokens
    text1 = "Hello world!"
    text2 = "This is a test sentence."
    # Expected counts depend on the specific tokenizer (cl100k_base)
    assert count_tokens(text1) == 3 # "Hello", " world", "!"
    assert count_tokens(text2) == 6 # "This", " is", " a", " test", " sentence", "."

# Patch tiktoken at the *module level* where count_tokens imports it
@patch('pm.core.token_utils.tiktoken', None)
def test_count_tokens_fallback_to_word_count():
    """Tests token counting fallback to word count when tiktoken fails."""
    # Re-import count_tokens to make sure it sees the patched (None) tiktoken
    from pm.core.token_utils import count_tokens

    text1 = "Hello world!"
    text2 = "This is a test sentence."
    assert count_tokens(text1) == 2 # Fallback to word count
    assert count_tokens(text2) == 5 # Fallback to word count

def test_count_tokens_empty_string():
    """Tests token counting with an empty string."""
    # Import here as well for consistency, though fallback doesn't depend on tiktoken
    from pm.core.token_utils import count_tokens
    assert count_tokens("") == 0

