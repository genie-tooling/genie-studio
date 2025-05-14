# pm/core/model_registry.py
"""Dynamic model discovery and context‑window resolution."""
from __future__ import annotations
from typing import List, Optional, Any
import functools
import time
from loguru import logger
import re
import inspect # Keep for debugging if needed later

# --- Cache dictionary ---
_cache: dict[tuple, tuple[float, list[str]]] = {}

# --- Function to clear specific cache keys ---
def clear_model_list_cache():
    """Removes cached results for model listing functions."""
    keys_to_remove = [
        key for key in _cache
        if isinstance(key, tuple) and len(key) > 0 and key[0] in ('_list_ollama_raw', '_list_gemini_raw')
    ]
    if keys_to_remove:
        logger.info("Clearing model list cache keys: {}", keys_to_remove)
        for key in keys_to_remove:
            try:
                del _cache[key]
            except KeyError:
                 pass # Ignore if already gone
    else:
        logger.debug("Model list cache appears empty or keys not found.")

# --- Cache decorator ---
def _cached(ttl_seconds: int = 300):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            key = (fn.__name__, args, frozenset(kwargs.items())) # Standard key
            now = time.time()
            force_no_cache = kwargs.get('force_no_cache', False)
            if force_no_cache:
                 logger.trace(f"Cache bypass requested for {key}")
                 if key in _cache:
                      del _cache[key]
                      logger.trace(f"Cache key {key} removed.")
                 else:
                      logger.trace(f"Cache key {key} not found for removal.")

            if not force_no_cache and key in _cache and now - _cache[key][0] < ttl_seconds:
                logger.trace(f"Cache HIT for {key}"); return _cache[key][1]

            logger.trace(f"Cache MISS for {key}")
            original_kwargs = {k: v for k, v in kwargs.items() if k != 'force_no_cache'}
            try:
                 result = fn(*args, **original_kwargs)
            except TypeError as e:
                 sig = inspect.signature(fn)
                 if 'force_no_cache' in sig.parameters:
                      result = fn(*args, **kwargs)
                 else:
                      raise e
            _cache[key] = (now, result)
            return result
        return wrapped
    return decorator

# _list_gemini_raw remains the same
@_cached()
def _list_gemini_raw(api_key: Optional[str]):
    import google.generativeai as genai
    try:
        genai.configure(api_key=api_key)
        logger.debug("Attempting to list Gemini models...")
        models = [m.name for m in genai.list_models()]
        logger.debug(f"Successfully listed {len(models)} raw Gemini models.")
        return models
    except ImportError: logger.error("google.generativeai library missing."); return []
    except Exception as e: logger.exception(f"Failed to list Gemini models: {e}"); return []

# list_gemini_models remains the same
def list_gemini_models(api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    if not api_key: logger.warning("Gemini API key not provided."); return []
    raw = _list_gemini_raw(api_key, force_no_cache=force_no_cache)
    if not raw: return []
    keep_prefixes = ('models/gemini-1.5', 'models/gemini-1.0'); keep_explicit = set()
    remove_keywords = ('-001', '-002', 'live', 'learning', 'embed', 'aqa', 'vision', 'audio', 'video')
    filtered_models = []
    for model_name in sorted(raw):
        norm_name = model_name.removeprefix('models/')
        if model_name in keep_explicit: filtered_models.append(model_name); continue
        if not any(model_name.startswith(prefix) for prefix in keep_prefixes): continue
        if any(keyword in norm_name for keyword in remove_keywords): continue
        filtered_models.append(model_name)
    model_families = {}; base_name_regex = re.compile(r"^(models/)?(gemini-\d+(\.\d+)?-(pro|flash|ultra))")
    for model_name in sorted(filtered_models):
        match = base_name_regex.match(model_name)
        if match: base_name = match.group(2)
        else: base_name = model_name
        if model_name.endswith('-latest'): model_families[base_name] = model_name
        elif base_name not in model_families: model_families[base_name] = model_name
        else:
            if not model_families[base_name].endswith('-latest'):
                 model_families[base_name] = model_name

    final_list = sorted(list(model_families.values()))
    logger.info(f"Final filtered Gemini models: {final_list}")
    return final_list

# _list_ollama_raw remains the same
@_cached()
def _list_ollama_raw():
    import ollama
    logger.info("!!! ENTERING _list_ollama_raw !!!")
    names = []
    try:
        logger.debug("Calling ollama.list()...")
        response = ollama.list()
        logger.info("!!! ollama.list() RESPONSE: type={}, content={}", type(response), response)

        models_list = []
        if isinstance(response, (list, tuple)):
             models_list = response
             logger.info("!!! Accessed response directly as list/tuple, length: {}", len(models_list))
        elif isinstance(response, dict):
            models_list = response.get('models', [])
            logger.info("!!! Accessed response as dict, models_list type: {}, length: {}", type(models_list), len(models_list))
        elif hasattr(response, 'models'):
            models_list = getattr(response, 'models', [])
            logger.info("!!! Accessed response via getattr, models_list type: {}, length: {}", type(models_list), len(models_list))
        else:
            logger.warning("!!! Ollama list response is not directly iterable, dict, or has 'models' attribute.")
            logger.info("!!! EXITING _list_ollama_raw (unknown response structure) - Returning: {}", names)
            return names

        if not isinstance(models_list, list):
            logger.error(f"!!! Ollama list response 'models' field is not a list: {type(models_list)}")
            logger.info("!!! EXITING _list_ollama_raw (models not list) - Returning: {}", names)
            return names

        logger.info("!!! Starting loop over models_list (length {})", len(models_list))
        for i, item in enumerate(models_list):
            name = None; item_type = type(item).__name__
            logger.info("!!! Processing item {} type {}: {}", i, item_type, item)
            if hasattr(item, 'name'):
                name_attr = getattr(item, 'name', None)
                logger.info("!!! -> Item has 'name' attribute, value: {}, type: {}", repr(name_attr), type(name_attr))
                if isinstance(name_attr, str) and name_attr: name = name_attr; logger.info("!!! --> Extracted name via getattr('name'): {}", name)
                else: logger.warning(f"!!! Item {i} getattr('name') failed check: type={type(name_attr)}, value={name_attr!r}")
            elif hasattr(item, 'model'):
                name_attr = getattr(item, 'model', None)
                logger.info("!!! -> Item has 'model' attribute, value: {}, type: {}", repr(name_attr), type(name_attr))
                if isinstance(name_attr, str) and name_attr: name = name_attr; logger.info("!!! --> Extracted name via getattr('model'): {}", name)
                else: logger.warning(f"!!! Item {i} getattr('model') failed check: type={type(name_attr)}, value={name_attr!r}")
            elif isinstance(item, dict):
                logger.info("!!! -> Item is dict, checking 'name' key first...")
                name_key = item.get('name')
                logger.info("!!! -> Dict item.get('name') value: {}, type: {}", repr(name_key), type(name_key))
                if isinstance(name_key, str) and name_key: name = name_key; logger.info("!!! --> Extracted name via dict.get('name'): {}", name)
                else:
                    logger.warning(f"!!! Item {i} dict missing 'name' key or value not string. Checking 'model'...")
                    name_key_fallback = item.get('model')
                    logger.info("!!! -> Dict item.get('model') value: {}, type: {}", repr(name_key_fallback), type(name_key_fallback))
                    if isinstance(name_key_fallback, str) and name_key_fallback: name = name_key_fallback; logger.warning(f"!!! --> Used 'model' key fallback for dict item {i}: {name}")
            else: logger.warning(f"!!! Unexpected item type at index {i}: {item_type}")

            if name: logger.info("!!! Appending name: {}", name); names.append(name)
            else: logger.warning(f"!!! >>> Failed to extract valid model name from item at index {i}: {item}")

        valid_names = sorted(list(set(names)))
        logger.info("!!! Parsed Ollama models (final list): {}", valid_names)
        logger.info("!!! EXITING _list_ollama_raw (normal end) - Returning: {}", valid_names)
        return valid_names
    except ImportError: logger.error("Ollama library missing."); return []
    except Exception as e: logger.exception("!!! ollama.list() failed: {}", e); return []

# list_ollama_models remains the same
def list_ollama_models(*, force_no_cache: bool = False) -> List[str]:
    return _list_ollama_raw(force_no_cache=force_no_cache)

# list_models remains the same
def list_models(provider: str, api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    provider = provider.lower()
    if provider == "gemini": return list_gemini_models(api_key, force_no_cache=force_no_cache)
    if provider == "ollama": return list_ollama_models(force_no_cache=force_no_cache)
    logger.warning(f"Unknown provider '{provider}' requested in list_models.")
    return []

# _gemini_ctx remains the same
def _gemini_ctx(model: str) -> int:
    model_norm = model.lower().split('/')[-1]
    if "1.5" in model_norm: return 1_048_576
    if "flash" in model_norm: return 1_048_576
    if "1.0" in model_norm or "pro" in model_norm: return 32_768
    logger.warning(f"Unknown Gemini model '{model}' (norm: '{model_norm}'), defaulting context to 32768."); return 32_768

# resolve_context_limit remains the same
def resolve_context_limit(provider: str, model: str) -> int:
    provider = provider.lower()
    if not model: logger.warning("Ctx limit for empty model name (provider=%s)", provider); return 4096
    logger.debug(f"Resolving context limit for provider={provider}, model={model}")
    try:
        if provider == "gemini": limit = _gemini_ctx(model); logger.info(f"Resolved Gemini ctx for {model}: {limit}"); return limit
        if provider == "ollama": limit = _ollama_ctx(model); logger.info(f"Resolved Ollama ctx for {model}: {limit}"); return limit
        logger.warning(f"Unknown provider '{provider}' for ctx limit. Default 4096."); return 4096
    except Exception as e: logger.error(f"Error resolving ctx limit for {provider}/{model}: {e}. Fallback 4096."); return 4096

# _parse_context_value remains the same
def _parse_context_value(value: Any) -> Optional[int]:
    if isinstance(value, int): return value
    if isinstance(value, str):
        try:
            val_lower = value.lower().strip()
            if val_lower.endswith('k'): return int(val_lower[:-1].strip()) * 1024
            return int(val_lower)
        except ValueError: pass
    return None

# --- MODIFIED _ollama_ctx function AGAIN ---
def _ollama_ctx(model: str) -> int:
    """Attempts to get context length for an Ollama model using attribute access first."""
    import ollama
    logger.debug(f"Calling ollama.show('{model}') to determine context length.")
    try:
        meta = ollama.show(model)
        logger.trace(f"Ollama show response type: {type(meta)}, content snippet: {str(meta)[:200]}...")

        # --- Strategy 1: Try direct attribute access ---
        primary_ctx_keys = ['num_ctx', 'context_length']
        for key in primary_ctx_keys:
             if hasattr(meta, key):
                  value = getattr(meta, key)
                  parsed = _parse_context_value(value)
                  if parsed is not None:
                       logger.info(f"Found context via direct attribute meta.{key}: {parsed}")
                       return parsed

        # --- Strategy 2: Check the 'modelinfo' attribute --- NEW/MODIFIED ---
        modelinfo_dict = None
        if hasattr(meta, 'modelinfo') and isinstance(getattr(meta, 'modelinfo'), dict):
            modelinfo_dict = getattr(meta, 'modelinfo')
            logger.trace(f"Found 'modelinfo' dictionary: Keys={list(modelinfo_dict.keys())}")

            # Check common context keys *within* the 'modelinfo' dictionary
            # These keys often include the model family prefix (e.g., 'gemma3.context_length')
            modelinfo_ctx_keys = [
                'gemma3.context_length', # Specific key found in debug log
                'llama.context_length', 'qwen2.context_length', 'mistral.context_length',
                'gemma.context_length', 'phi3.context_length', 'general.context_length',
                'context_length', # Generic key
                'max_position_embeddings', 'n_positions' # Other potential keys
            ]
            for key in modelinfo_ctx_keys:
                if key in modelinfo_dict:
                    value = modelinfo_dict[key]
                    parsed = _parse_context_value(value)
                    if parsed is not None:
                         logger.info(f"Found context via modelinfo['{key}']: {parsed}")
                         return parsed
        else:
             logger.trace("No 'modelinfo' dictionary found on response object or it's not a dict.")

        # --- Strategy 3: Check the 'details' attribute ---
        details_dict = None
        # The 'details' attribute might hold a ModelDetails object, check its attributes or __dict__
        if hasattr(meta, 'details'):
            details_obj = getattr(meta, 'details')
            logger.trace(f"Found 'details' object: type={type(details_obj)}")
            # If details object itself has useful attributes or is a dict (less likely now)
            if isinstance(details_obj, dict):
                details_dict = details_obj # Handle if it IS a dict unexpectedly
            elif hasattr(details_obj, '__dict__'):
                 details_dict = details_obj.__dict__ # Check its internal dict
                 logger.trace(f"Details object __dict__: {details_dict}")
            else:
                 # Check common attributes directly on the details object?
                 pass # Add direct attribute checks here if needed

            if details_dict: # If we got a dictionary from details somehow
                 detail_ctx_keys = [ # Redundant with modelinfo check, but keep as fallback
                      'num_ctx', 'context_length', 'max_position_embeddings', 'n_positions'
                 ]
                 for key in detail_ctx_keys:
                     if key in details_dict:
                         value = details_dict[key]
                         parsed = _parse_context_value(value)
                         if parsed is not None:
                              logger.info(f"Found context via details['{key}']: {parsed}")
                              return parsed
        else:
             logger.trace("No 'details' attribute found on response object.")


        # --- Strategy 4: Parse the 'parameters' string (fallback) ---
        parameters_str = ""
        if hasattr(meta, 'parameters') and isinstance(getattr(meta, 'parameters'), str):
             parameters_str = getattr(meta, 'parameters')
             logger.trace(f"Found 'parameters' string attribute: {parameters_str[:100]}...")
        # Add check if parameters might be inside modelinfo or details dicts too? Less likely.

        if parameters_str:
            match = re.search(r'^\s*(?:num_ctx|context_length)\s+(\d+k?)\s*$', parameters_str, re.IGNORECASE | re.MULTILINE)
            if match:
                val_str = match.group(1)
                parsed = _parse_context_value(val_str)
                if parsed is not None:
                    logger.info(f"Found context {parsed} parsing parameters string ('{val_str}')")
                    return parsed
                else:
                    logger.warning(f"Found context pattern in parameters string but couldn't parse: '{val_str}'")
        else:
             logger.trace("No 'parameters' string found or available to parse.")

        # If none found, log debug info and fall back
        logger.warning(f"Could not reliably determine context length for '{model}' from ollama.show(). Using fallback logic.")
        try:
             meta_attrs = dir(meta)
             logger.debug(f"Available attributes/methods on ollama.show response object for '{model}': {meta_attrs}")
             if hasattr(meta, '__dict__'): logger.debug(f"__dict__ of response object: {meta.__dict__}")
        except Exception as debug_err: logger.error(f"Error trying to log debug info for ollama.show response: {debug_err}")

    except ImportError:
        logger.error("Ollama library missing.")
    except ollama.ResponseError as e:
        logger.error(f"Ollama API error getting info for model '{model}': {e}")
    except Exception as e:
        logger.exception(f"ollama.show('{model}') unexpected error during context resolution: {e}")

    # Fallback if any error or no value found
    return _ollama_ctx_fallback(model)


# _ollama_ctx_fallback function remains the same
def _ollama_ctx_fallback(model: str) -> int:
     logger.warning(f"Could not determine context length for Ollama model '{model}' from API. Using fallback logic based on name.")
     norm_model = model.lower().split(':')[0].split('/')[-1]
     if "gemma" in norm_model: return 8192 # Gemma models are typically 8k
     if any(x in norm_model for x in ("70b","large","mixtral", "qwen:72b")): return 32768
     if any(x in norm_model for x in ("13b","20b","30b","34b", "codellama", "llama3", "mistral")): return 8192
     if any(x in norm_model for x in ("7b","8b")): return 8192
     if any(x in norm_model for x in ("phi", "phi3", "qwen", "codeqwen", "starcoder")): return 8192
     if any(x in norm_model for x in ("3b","4b","small", "2b", "1.5b", "0.5b")): return 4096
     logger.warning(f"Using generic fallback context: 4096 for {model} (normalized: {norm_model})"); return 4096

