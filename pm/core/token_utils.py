import tiktoken

def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Return token count, fallback to word count if tiktoken missing."""
    try:
        encoding = tiktoken.get_encoding(model)
        return len(encoding.encode(text))
    except Exception:
        return len(text.split())
