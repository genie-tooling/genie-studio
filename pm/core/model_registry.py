"""Dynamic model discovery and context‑window resolution."""
from __future__ import annotations
from typing import List, Optional
import functools
import time
from loguru import logger
import re

_cache: dict[tuple, tuple[float, list[str]]] = {}

def _cached(ttl_seconds: int = 300):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            key = (fn.__name__, args, frozenset(kwargs.items()))
            now = time.time()
            if key in _cache and now - _cache[key][0] < ttl_seconds:
                return _cache[key][1]
            result = fn(*args, **kwargs)
            _cache[key] = (now, result)
            return result
        return wrapped
    return decorator


@_cached()
def _list_gemini_raw(api_key: Optional[str]):
    import google.generativeai as genai
    try:
        if api_key: genai.configure(api_key=api_key)
        return [m.name for m in genai.list_models()]
    except Exception:
        logger.exception("Failed to list Gemini models")
        return []


def list_gemini_models(api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    if force_no_cache:
        _cache.pop(('_list_gemini_raw', (api_key,), frozenset()), None)

    raw = _list_gemini_raw(api_key)
    if not raw: return []

    # --- Filtering Logic ---
    keep_prefixes = ('models/gemini-1.5', 'models/gemini-1.0') # Keep 1.5 and 1.0 families
    # Keep specific models explicitly if needed (e.g., preview versions)
    # keep_explicit = {'models/gemini-pro-preview', 'models/gemini-pro-exp'} # Add specific model names if needed
    keep_explicit = set() # Example: Keep none explicitly for now
    # Remove models containing these substrings
    remove_keywords = ('-001', '-002', 'live', 'learning', 'embed', 'aqa', 'vision', 'audio', 'video') # Added vision/audio/video

    filtered_models = []
    for model_name in sorted(raw):
        # Normalize name by removing prefix if present
        norm_name = model_name.removeprefix('models/')

        # Check if it should be explicitly kept
        if model_name in keep_explicit:
             filtered_models.append(model_name)
             continue

        # Check if it starts with a desired prefix
        if not any(model_name.startswith(prefix) for prefix in keep_prefixes):
             logger.debug(f"Filtering Gemini: Skip (prefix) - {model_name}")
             continue

        # Check if it contains any removal keywords
        if any(keyword in norm_name for keyword in remove_keywords):
             logger.debug(f"Filtering Gemini: Skip (keyword) - {model_name}")
             continue

        # If passed all checks, keep it
        filtered_models.append(model_name)
        logger.debug(f"Filtering Gemini: Keep - {model_name}")

    # --- Deduplication for -latest ---
    model_families = {}
    base_name_regex = re.compile(r"^(models/)?(gemini-\d+(\.\d+)?-(pro|flash|ultra))")
    final_deduplicated = []

    for model_name in sorted(filtered_models): # Sort again for consistent processing
        match = base_name_regex.match(model_name)
        if match:
            base_name = match.group(2)
            if model_name.endswith('-latest'): model_families[base_name] = model_name # Prefer latest
            elif base_name not in model_families: model_families[base_name] = model_name # Keep first non-latest if no latest seen
        else: # If regex doesn't match (maybe a unique name like 'gemma' if it were Gemini), keep it
            if model_name not in model_families.values(): model_families[model_name] = model_name

    final_list = sorted(list(model_families.values()))
    logger.info(f"Final filtered Gemini models: {final_list}")
    return final_list


@_cached()
def _list_ollama_raw() -> list[str]:
    import ollama
    logger.debug("Calling ollama.list()")
    try:
        response = ollama.list(); logger.debug("ollama.list() raw: {}", response)
        if hasattr(response, "models"): names = [m.model for m in response.models if hasattr(m, "model")]; logger.debug("Parsed from response.models: {}", names); return names
        if isinstance(response, dict) and "models" in response: names = [m["name"] for m in response["models"] if "name" in m]; logger.debug("Parsed from dict: {}", names); return names
        logger.warning("ollama.list() unknown type: {}", type(response)); return []
    except Exception as e: logger.exception("ollama.list() failed: {}", e); return []


def list_ollama_models(*, force_no_cache: bool = False) -> List[str]:
    if force_no_cache: _cache.pop(('_list_ollama_raw', (), frozenset()), None)
    return _list_ollama_raw()


def list_models(provider: str, api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    provider = provider.lower()
    if provider == "gemini": return list_gemini_models(api_key, force_no_cache=force_no_cache)
    if provider == "ollama": return list_ollama_models(force_no_cache=force_no_cache)
    return []


def _gemini_ctx(model: str) -> int:
    if "1.5" in model: return 1_048_576 # 1M default
    if "1.0" in model: return 32_768    # 32k default for 1.0 Pro
    if "flash" in model: return 1_048_576 # Assume 1M for Flash 1.5
    logger.warning(f"Unknown Gemini model '{model}', defaulting context to 32768."); return 32_768


def resolve_context_limit(provider: str, model: str) -> int:
    provider = provider.lower()
    if not model: logger.warning("Ctx limit for empty model (provider=%s)", provider); return 4096
    logger.debug(f"Resolving context limit for provider={provider}, model={model}")
    if provider == "gemini": limit = _gemini_ctx(model); logger.info(f"Resolved Gemini ctx for {model}: {limit}"); return limit
    if provider == "ollama": limit = _ollama_ctx(model); logger.info(f"Resolved Ollama ctx for {model}: {limit}"); return limit
    logger.warning(f"Unknown provider '{provider}' for ctx limit, default 4096."); return 4096

def _ollama_ctx(model: str) -> int:
    import ollama
    logger.debug("Calling ollama.show({})", model)
    try:
        meta = ollama.show(model)
        model_info = meta.get("modelinfo", {})
        if model_info:
            logger.debug(f"Checking modelinfo keys: {list(model_info.keys())}")
            possible_keys = [k for k in model_info if k.endswith('.context_length')]+['num_ctx','max_position_embeddings','n_positions']
            for key in possible_keys:
                if key in model_info and isinstance(model_info[key], int): val=model_info[key]; logger.info(f"Found ctx {val} in modelinfo key '{key}'"); return val
                elif key in model_info: logger.warning(f"Found key '{key}' but type not int: {type(model_info[key])}")
        details = meta.get("details", {}); params = details.get("parameters", "")
        if isinstance(params, str) and params:
             logger.debug(f"Checking details.parameters string...")
             match = re.search(r'(?:num_ctx|context_length)\s+(\d+)', params)
             if match:
                 try: val=int(match.group(1)); logger.info(f"Found ctx {val} parsing details.parameters"); return val
                 except ValueError: logger.warning(f"Found ctx pattern but not int: '{match.group(1)}'")
        if details:
            logger.debug(f"Checking root details dict...")
            for key in ("context_length", "num_ctx"):
                 if key in details and isinstance(details[key], int): val=details[key]; logger.info(f"Found ctx {val} in root details key '{key}'"); return val
    except ImportError: logger.error("Ollama library missing.")
    except ollama.ResponseError as e: # Catch specific Ollama error
        logger.error(f"Ollama API error for model '{model}': {e}")
        # Don't fallback here, let the caller handle the fact that the model doesn't exist
        raise # Re-raise the exception
    except Exception as e: logger.exception(f"ollama.show({model}) parsing error: {e}") # Catch other errors

    # Fallback logic *only* if ollama.show succeeded but parsing failed
    logger.warning(f"Could not determine context length for Ollama model '{model}'. Using fallback.")
    if any(x in model for x in ("70b","large","mixtral")): return 32768
    if any(x in model for x in ("13b","20b","30b","34b")): return 8192
    if any(x in model for x in ("7b","8b","gemma","phi","medium")): return 8192
    if any(x in model for x in ("3b","4b","small")): return 4096
    logger.warning(f"Using generic fallback context: 4096 for {model}"); return 4096

