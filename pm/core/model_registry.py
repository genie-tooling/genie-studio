# pm/core/model_registry.py
"""Dynamic model discovery and context‑window resolution."""
from __future__ import annotations
from typing import List, Optional, Any
import functools
import time
import re
import ollama # Keep ollama import here for show/list
import google.generativeai as genai # Keep genai import here
from loguru import logger
import traceback # Added for better exception logging
import inspect # To inspect details object

_cache: dict[tuple, tuple[float, list[str]]] = {}

def clear_model_list_cache():
    """Clears cached model list results."""
    keys_to_remove = [ key for key in _cache if isinstance(key, tuple) and len(key) > 0 and key[0] in ('_list_ollama_raw', '_list_gemini_raw') ]
    if keys_to_remove:
        logger.info("Clearing model list cache keys: {}", keys_to_remove)
        for key in keys_to_remove:
            try:
                del _cache[key]
            except KeyError:
                pass
    else:
        logger.debug("Model list cache appears empty or keys not found.")

def _cached(ttl_seconds: int = 300):
    """Decorator for caching function results with a time-to-live and bypass option."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            # Create a cache key including function name, args, and kwargs
            key = (fn.__name__, args, frozenset(kwargs.items()))
            now = time.time()

            # Check if force_no_cache is True to bypass cache
            force_no_cache = kwargs.get('force_no_cache', False)
            if force_no_cache and key in _cache:
                logger.trace(f"Cache bypass requested for {key}")
                try:
                    del _cache[key]
                except KeyError:
                    pass

            # Check if result is in cache and not expired
            if key in _cache and now - _cache[key][0] < ttl_seconds:
                logger.trace(f"Cache HIT for {key}"); return _cache[key][1]

            # Cache miss or expired/bypassed
            logger.trace(f"Cache MISS for {key}")
            # Remove force_no_cache before calling the original function
            original_kwargs = {k: v for k, v in kwargs.items() if k != 'force_no_cache'}
            try:
                # Execute the function
                result = fn(*args, **original_kwargs)
            except Exception as e:
                logger.error(f"Error executing cached function {fn.__name__}: {e}"); result = [] # Return empty list on error to prevent caching failures

            # Store result in cache
            _cache[key] = (now, result); return result
        return wrapped
    return decorator

@_cached()
def _list_gemini_raw(api_key: Optional[str]):
    """Fetches the raw list of models from the Gemini API."""
    try:
        if not api_key:
            raise ValueError("API key required for Gemini.")
        genai.configure(api_key=api_key)
        logger.debug("Attempting to list Gemini models...")
        models = list(genai.list_models())
        logger.debug(f"Successfully listed {len(models)} raw Gemini models.")
        return models
    except ImportError:
        logger.error("google.generativeai library missing."); return []
    except Exception as e:
        logger.exception(f"Failed to list Gemini models: {e}"); return []

def list_gemini_models(api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    """Lists available text-generation Gemini models, filtering out non-generative/utility models."""
    if not api_key:
        logger.warning("Gemini API key not provided."); return []
    raw_models = _list_gemini_raw(api_key=api_key, force_no_cache=force_no_cache)
    if not raw_models:
        return []

    # Keywords to filter out non-text-generation models
    remove_keywords = ('embed', 'aqa', 'vision', 'audio', 'video', 'tuned', 'unknown', 'retriever', 'reranker')
    filtered_models = []
    logger.debug(f"Filtering {len(raw_models)} raw Gemini models...")
    for model in raw_models:
        model_name = model.name
        # Check if the model supports the standard text generation method
        if 'generateContent' not in model.supported_generation_methods:
            logger.trace(f"Skipping Gemini model '{model_name}': No 'generateContent'."); continue

        # Check base model name (part after /) for exclusion keywords
        base_model_name = model_name.split('/')[-1]
        if any(keyword in base_model_name for keyword in remove_keywords):
            logger.trace(f"Skipping Gemini model '{model_name}': Keyword exclusion on '{base_model_name}'."); continue

        # Specific check for models ending in -v1 (often older/less capable)
        if base_model_name.endswith('-v1'):
            logger.trace(f"Skipping Gemini model '{model_name}': Ends with '-v1'."); continue

        filtered_models.append(model_name)
        logger.trace(f"Keeping Gemini model '{model_name}'")

    final_list = sorted(filtered_models)
    logger.info(f"Final filtered Gemini models ({len(final_list)}): {final_list}")
    return final_list

@_cached()
def _list_ollama_raw():
    """Fetches the raw list of models from the Ollama API."""
    logger.debug("Fetching Ollama model list...")
    names = []
    try:
        response = ollama.list()
        logger.trace("Ollama list() raw response type: {}, content: {}", type(response), response)

        # Determine the actual list of model items from the response structure
        models_list = []
        if isinstance(response, (list, tuple)):
            models_list = response # Response is directly the list
        elif isinstance(response, dict):
            models_list = response.get('models', []) # Response is a dict containing 'models'
        elif hasattr(response, 'models'):
            models_list = getattr(response, 'models', []) # Response is an object with 'models' attribute
        else:
            logger.warning("Ollama list response has unknown structure."); return names # Return empty list

        if not isinstance(models_list, list):
            logger.error(f"Ollama response 'models' field is not a list: {type(models_list)}"); return names # Ensure we have a list

        logger.debug(f"Processing {len(models_list)} items from Ollama list response.")
        for i, item in enumerate(models_list):
            name = None
            item_type = type(item).__name__
            logger.trace("Processing item {} type {}: {}", i, item_type, item)

            # Prioritize 'model' attribute if the item is an object
            if hasattr(item, 'model'):
                name_attr = getattr(item, 'model', None)
                if isinstance(name_attr, str) and name_attr:
                    name = name_attr; logger.trace("--> Extracted name via getattr: {}", name)
                else:
                    logger.trace(f"Item {i} has 'model' attr, but not valid: {name_attr!r}")
            # Fallback to dict access if it's a dictionary
            elif isinstance(item, dict):
                name_key = item.get('model') # Prefer 'model' key
                if isinstance(name_key, str) and name_key:
                    name = name_key; logger.trace("--> Extracted name via dict.get('model'): {}", name)
                else:
                    name_key_fallback = item.get('name') # Fallback to 'name' key
                    if isinstance(name_key_fallback, str) and name_key_fallback:
                         name = name_key_fallback; logger.trace(f"--> Used 'name' key fallback for dict item {i}: {name}")
                    else:
                         logger.trace(f"Item {i} dict missing 'model'/'name'.")
            # Log if item type is unexpected
            else:
                 logger.warning(f"Unexpected item type at index {i}: {item_type}")

            if name:
                names.append(name)
            else:
                 logger.warning(f"Failed to extract model name from item {i}: {item}")

        valid_names = sorted(names)
        logger.debug("Parsed Ollama models (final): {}", valid_names)
        return valid_names
    except ImportError:
        logger.error("Ollama library missing."); return []
    except Exception as e:
        logger.error("ollama.list() failed: {}", e); logger.error("Traceback:\n{}", traceback.format_exc()); return []

def list_ollama_models(*, force_no_cache: bool = False) -> List[str]:
    """Lists available Ollama models."""
    return _list_ollama_raw(force_no_cache=force_no_cache)

def list_models(provider: str, api_key: Optional[str] = None, *, force_no_cache: bool = False) -> List[str]:
    """Lists models for the specified provider."""
    provider = provider.lower()
    if provider == "gemini":
        return list_gemini_models(api_key=api_key, force_no_cache=force_no_cache)
    if provider == "ollama":
        return list_ollama_models(force_no_cache=force_no_cache)
    logger.warning(f"Unknown provider '{provider}' requested in list_models.")
    return []

def _gemini_ctx(model: str) -> int:
    """Estimates context window size for Gemini models based on name."""
    model_norm = model.lower().split('/')[-1];
    if "gemini-1.5" in model_norm:
        return 1_048_576 # 1M tokens
    if "flash" in model_norm:
        return 1_048_576 # 1M tokens (as of announcement)
    # Handle gemini-pro (assuming 1.0 pro)
    if model_norm == "gemini-pro":
        return 32_768 # 32k context
    if "gemini-1.0-pro" in model_norm:
         return 32_768
    # Older/unspecified might be 32k
    if "gemini-1.0" in model_norm or "pro" in model_norm:
        return 32_768
    logger.warning(f"Unknown Gemini model '{model}' (norm: '{model_norm}'), defaulting ctx to 32768."); return 32_768

def resolve_context_limit(provider: str, model: str) -> int:
    """Resolves the context window size for a given model and provider."""
    provider = provider.lower()
    if not model:
        logger.warning("Ctx limit requested for empty model name (provider=%s)", provider); return 4096
    logger.debug(f"Resolving context limit for provider={provider}, model={model}")
    try:
        if provider == "gemini":
            limit = _gemini_ctx(model); logger.info(f"Resolved Gemini ctx for {model}: {limit}"); return limit
        if provider == "ollama":
            limit = _ollama_ctx(model); logger.info(f"Resolved Ollama ctx for {model}: {limit}"); return limit
        logger.warning(f"Unknown provider '{provider}' for ctx limit. Default 4096."); return 4096
    except Exception as e:
        logger.error(f"Error resolving ctx limit for {provider}/{model}: {e}. Fallback 4096."); return 4096

def _parse_context_value(value: Any) -> Optional[int]:
    """Attempts to parse context length values, handling 'k' suffix."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            val_lower = value.lower().strip()
            # Handle 'k' suffix for thousands (commonly used for tokens)
            if val_lower.endswith('k'):
                # Allow float parsing before int for values like '8.5k'
                return int(float(val_lower[:-1].strip()) * 1024)
            return int(val_lower)
        except ValueError:
            logger.warning(f"Could not parse context value string: '{value}'")
    return None

def _ollama_ctx(model: str) -> int:
    """Resolves context window size for an Ollama model using ollama.show() with enhanced checks and logging."""
    logger.debug(f"Calling ollama.show('{model}') for context length...")
    try:
        meta = ollama.show(model)
        logger.trace(f"ollama.show response type: {type(meta)}")

        # --- Get potential data sources ---
        details_obj = getattr(meta, 'details', None)
        modelfile_content = getattr(meta, 'modelfile', "")
        parameters_str = getattr(meta, 'parameters', "")

        # --- Detailed Logging of Sources ---
        logger.trace(f"--- ollama show response details for '{model}' ---")
        if details_obj:
            try:
                # Log attributes using inspect for better reliability
                details_attrs = inspect.getmembers(details_obj)
                logger.trace(f"  details object attributes: {dict(details_attrs)}")
            except Exception as inspect_err:
                logger.warning(f"  Could not inspect details object attributes: {inspect_err}")
        else:
            logger.trace("  details object: Not found or None")
        logger.trace(f"  modelfile content (first 500 chars): {modelfile_content[:500]!r}")
        logger.trace(f"  parameters string: {parameters_str!r}")
        logger.trace(f"--- End response details for '{model}' ---")
        # --- End Detailed Logging ---

        # 1. Check primary keys directly on the details object
        if details_obj:
            primary_keys = ['num_ctx', 'context_length'] # Most common names
            for key in primary_keys:
                value = getattr(details_obj, key, None)
                if value is not None:
                    logger.trace(f"Attempting details.{key} (value: {value!r})")
                    ctx = _parse_context_value(value)
                    if ctx:
                        logger.info(f"Using context length {ctx} from details.{key}"); return ctx
                    else:
                        logger.warning(f"Found key '{key}' on details obj but couldn't parse value: '{value!r}'")

        # 2. Parse the modelfile content
        if isinstance(modelfile_content, str) and modelfile_content:
            logger.trace("Attempting to parse modelfile content for context length...")
            # Regex allows more flexible whitespace around value
            pattern = r"^\s*PARAMETER\s+(?:num_ctx|context_length)\s+(\S+)\s*(?:#.*)?$"
            found_in_modelfile = False
            for i, line in enumerate(modelfile_content.splitlines()):
                line_stripped = line.strip()
                # Skip empty lines or pure comments
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                logger.trace(f"Checking modelfile line {i+1}: '{line_stripped}'") # Log each line check
                match = re.match(pattern, line_stripped, re.IGNORECASE)
                if match:
                    val_str = match.group(1)
                    logger.trace(f"  Regex matched on modelfile line {i+1}! Captured value string: '{val_str}'")
                    ctx = _parse_context_value(val_str)
                    if ctx:
                        logger.info(f"Using context length {ctx} from modelfile (parsed '{val_str}')"); return ctx
                    else:
                        logger.warning(f"Matched context pattern in modelfile line {i+1} but couldn't parse value: '{val_str}'")
                    found_in_modelfile = True # Mark if pattern was matched, even if parsing failed
            if not found_in_modelfile:
                logger.trace("Context length directive pattern not matched in modelfile content.")
        else:
            logger.trace("Modelfile content is empty or not a string.")

        # 3. Check secondary keys on the details object
        if details_obj:
            secondary_keys = ['max_position_embeddings', 'n_positions', 'sliding_window'] # Added sliding_window
            for key in secondary_keys:
                value = getattr(details_obj, key, None)
                if value is not None:
                    logger.trace(f"Attempting details.{key} (value: {value!r})")
                    ctx = _parse_context_value(value)
                    if ctx:
                        logger.info(f"Using context length {ctx} from details.{key}"); return ctx
                    else:
                        logger.warning(f"Found key '{key}' on details obj but couldn't parse value: '{value!r}'")
            logger.trace("Secondary context length keys not found or unparsable in details object.")

        # 4. Fallback: Parse the raw 'parameters' string
        if isinstance(parameters_str, str) and parameters_str:
            logger.trace(f"Attempting fallback parsing of parameters string: {parameters_str!r}")
            # Regex to find num_ctx followed by digits (optionally with 'k')
            match = re.search(r'num_ctx\s+([\d.]+[kK]?)', parameters_str, re.I)
            if match:
                val_str = match.group(1)
                logger.trace(f"  Regex matched on parameters string! Captured value string: '{val_str}'")
                ctx = _parse_context_value(val_str)
                if ctx:
                    logger.info(f"Using context length {ctx} from fallback parameters string parsing ('{val_str}')"); return ctx
                else:
                    logger.warning(f"Found num_ctx pattern in parameters string but couldn't parse: '{val_str}'")
            else:
                 logger.trace("num_ctx pattern not found in parameters string via regex.")
        else:
             logger.trace("Parameters string is empty or not a string.")

        # 5. If nothing found after all checks
        logger.warning(f"Could not find context length in ollama.show() response for '{model}' after checking details, modelfile, and parameters string.")

    except ImportError:
        logger.error("Ollama library missing.")
    except ollama.ResponseError as e:
        logger.error(f"Ollama API error getting info for '{model}': {e} (status: {e.status_code})");
    except Exception as e:
        logger.exception(f"ollama.show('{model}') unexpected error during context resolution: {e}")

    # 6. Final Fallback based on model name heuristic
    return _ollama_ctx_fallback(model)

# --- UPDATED FALLBACK ---
def _ollama_ctx_fallback(model: str) -> int:
    """Fallback context length based on common model name patterns, with specific overrides."""
    logger.warning(f"Could not determine context for Ollama model '{model}' directly. Using fallback based on name.")
    # Normalize: lowercase, remove ':latest' or similar tags, take base name if user/repo format
    norm = model.lower().split(':')[0].split('/')[-1]

    # --- Specific Overrides for known large-context models ---
    if "llama3.1" in norm or "gemma2" in norm or "gemma3" in norm or "qwen2" in norm:
        # Assuming recent models have large context, default high
        logger.info(f"Applying specific large context fallback (128k) for model name containing '{norm}'.")
        return 128 * 1024 # 128k

    # --- General Size-Based Heuristics ---
    if any(x in norm for x in ("70b", "qwen:72b", "8x7b", "mixtral", "deepseek-67b")):
        return 32768
    if any(x in norm for x in ("30b", "32b", "34b", "deepseek-33b")):
        return 16384
    # Most common ~8k models (Llama 3 base, older Mistral, etc.)
    if any(x in norm for x in ("llama3", "llama-3", "mistral", "qwen", "codellama", "deepseek-coder", "starcoder2")):
        return 8192
    if any(x in norm for x in ("12b", "13b","14b","15b","16b")):
        return 8192
    if any(x in norm for x in ("7b", "8b", "gemma", "phi3", "phi-3", "command-r")): # Note: Removed gemma3/qwen2 here
        return 8192
    # Smaller context models
    if any(x in norm for x in ("phi", "phi-2")): # Original Phi often smaller
         return 4096
    if any(x in norm for x in ("3b","4b","small", "2b", "1.5b", "0.5b")): # Very small models often 4k
        return 4096

    logger.warning(f"Using generic fallback context: 4096 for {model} (norm: {norm}) - No specific rule matched."); return 4096
# --- END UPDATED FALLBACK ---

def _parse_size_to_bytes(size_str: str) -> Optional[int]:
    """Parses a size string (e.g., '4.3B', '7.1GB') into bytes."""
    size_str = size_str.strip().upper()
    # Match floating point or integer values, optional space, and units
    match = re.match(r'([\d.]+)\s*([KMGT]?B?)', size_str)
    if not match:
        logger.warning(f"Could not parse size string: '{size_str}'")
        return None
    try:
        value = float(match.group(1))
        unit = match.group(2)
    except (IndexError, ValueError):
        logger.warning(f"Could not parse size string components: '{size_str}'")
        return None

    # Determine multiplier based on unit
    if unit == 'B' : multiplier = 1
    elif unit == 'M' : multiplier = .0001
    
    else: logger.warning(f"Unknown size unit '{unit}' in string: '{size_str}'"); return None

    return int(value * multiplier)

def estimate_ollama_ram(model: str) -> Optional[float]:
    """Estimates RAM usage in GB for an Ollama model based on its size from ollama.show()."""
    logger.debug(f"Estimating RAM for Ollama model: {model}")
    try:
        meta = ollama.show(model)
        details_obj = getattr(meta, 'details', None)
        size_bytes = None

        # 1. Try details.parameter_size first (e.g., "4.3B")
        if details_obj:
            param_size_str = getattr(details_obj, 'parameter_size', None)
            if isinstance(param_size_str, str) and param_size_str:
                logger.trace(f"Found details.parameter_size: '{param_size_str}'")
                size_bytes = _parse_size_to_bytes(param_size_str)
                if size_bytes: logger.debug(f"Parsed parameter_size '{param_size_str}' to {size_bytes} bytes.")
                else: logger.warning(f"Could not parse details.parameter_size: '{param_size_str}'")

        # 2. Fallback to top-level size attribute (numeric bytes)
        if size_bytes is None:
            size_attr = getattr(meta, 'size', None)
            if isinstance(size_attr, (int, float)) and size_attr > 0:
                 size_bytes = int(size_attr)
                 logger.debug(f"Using top-level size attribute: {size_bytes} bytes.")
            else:
                 # Log details object content if size cannot be determined
                 details_content = vars(details_obj) if details_obj else "N/A"
                 logger.warning(f"Could not get valid size from details.parameter_size or meta.size for {model}. Details object content: {details_content}")
                 return None # Cannot estimate RAM

        # 3. Estimate RAM based on size and quantization level heuristic
        quantization_level = getattr(details_obj, 'quantization_level', '').upper() if details_obj else ""
        ram_multiplier = 1.1 # Default overhead estimate
        # Adjust multiplier based on common quantization levels
        if 'Q4' in quantization_level: ram_multiplier = 0.6 # Rough estimate for Q4 types
        elif 'Q5' in quantization_level: ram_multiplier = 0.7
        elif 'Q6' in quantization_level: ram_multiplier = 0.8
        elif 'Q8' in quantization_level: ram_multiplier = 1.1 # Closer to full size
        elif 'F16' in quantization_level: ram_multiplier = 2.1 # FP16 needs more
        elif 'F32' in quantization_level: ram_multiplier = 4.1 # FP32 needs much more
        
        estimated_bytes = size_bytes * ram_multiplier
        estimated_gb = estimated_bytes / (1024**3)
        logger.info(f"Estimated RAM for {model} (Quant: {quantization_level}): {estimated_gb:.2f} GB (Multiplier: {ram_multiplier:.1f}, Base Size: {size_bytes / (1024**3):.2f} GB)")
        return estimated_gb

    except ImportError: logger.error("Ollama library missing for RAM estimate."); return None
    except ollama.ResponseError as e: logger.error(f"Ollama API error getting info for RAM estimate '{model}': {e}"); return None
    except Exception as e: logger.exception(f"ollama.show({model}) unexpected error during RAM estimate: {e}"); return None
