# pm/core/project_config.py
import json
from pathlib import Path
from loguru import logger
from pygments.styles import get_all_styles
AVAILABLE_RAG_MODELS = [ 'all-MiniLM-L6-v2', 'msmarco-distilbert-base-v4', 'all-mpnet-base-v2', ]
# --- Get available styles ---
try:
    AVAILABLE_PYGMENTS_STYLES = sorted(list(get_all_styles()))
    DEFAULT_STYLE = 'native' if 'native' in AVAILABLE_PYGMENTS_STYLES else 'default'
except ImportError:
    logger.warning("Pygments not installed. Syntax highlighting styles unavailable.")
    AVAILABLE_PYGMENTS_STYLES = ['default']
    DEFAULT_STYLE = 'default'

# Import prompt templates
from .prompts import (
    PLANNER_PROMPT_TEMPLATE,
    CRITIC_PROMPT_TEMPLATE,
    EXECUTOR_PROMPT_TEMPLATE,
    DIRECT_EXECUTOR_PROMPT_TEMPLATE,
    RAG_SUMMARIZER_PROMPT_TEMPLATE,
)

DEFAULT_CONFIG = {
    # LLM Settings
    "provider": "Ollama", "model": "llama3:8b", "api_key": "",
    "temperature": 0.3, "top_k": 40, "context_limit": 8192,

    # --- Prompts ---
    # Note: These are defaults; they aren't directly editable in Settings UI yet.
    "system_prompt": "You are a helpful AI assistant expert in software development.",
    "planner_prompt_template": PLANNER_PROMPT_TEMPLATE,
    "critic_prompt_template": CRITIC_PROMPT_TEMPLATE,
    "executor_prompt_template": EXECUTOR_PROMPT_TEMPLATE,
    "direct_executor_prompt_template": DIRECT_EXECUTOR_PROMPT_TEMPLATE,
    "rag_summarizer_prompt_template": RAG_SUMMARIZER_PROMPT_TEMPLATE,

    # Features (Core)
    "patch_mode": True,
    "whole_file": True,
    "disable_critic_workflow": False, # <<< NEW SETTING <<<

    # --- RAG Settings ---
    "rag_local_enabled": False, "rag_local_sources": [],
    "rag_external_enabled": True,
    "rag_google_enabled": False, # Google Search (Optional, requires setup)
    "rag_bing_enabled": True,    # NEW: Enable Bing by default? Requires Key.
    "rag_stackexchange_enabled": True, # Will use DDG and/or Bing
    "rag_github_enabled": True,        # Will use DDG and/or Bing
    "rag_arxiv_enabled": False,        # Uses direct API

    # External RAG Configuration
    "rag_google_api_key": "", "rag_google_cse_id": "",
    "rag_bing_api_key": "", # <<< NEW BING KEY SETTING

    # Ranking Configuration
    "rag_ranking_model_name": AVAILABLE_RAG_MODELS[0],
    "rag_similarity_threshold": 0.30,

    # Query Summarizer Settings (Kept separate)
    "rag_summarizer_enabled": True,
    "rag_summarizer_provider": "Ollama",
    "rag_summarizer_model_name": "llama3:8b",

    # Appearance
    'editor_font': 'Fira Code', 'editor_font_size': 11, 'theme': 'Dark',
    'syntax_highlighting_style': DEFAULT_STYLE,
    'last_project_path': str(Path.cwd()),
    'main_window_geometry': "", # Store as hex string
    'main_window_state': "",    # Store as hex string
    'main_splitter_state': [],  # Store list of hex strings (though likely just one)
    # User Prompts (Used by Executor)
    'user_prompts': [] # List of strings {id, name, content} - Managed via PromptActionHandler/ConfigDock
}

# --- Function to load effective prompts (merging system prompt if template uses it) ---
def get_effective_prompt(config: dict, template_key: str, placeholders: dict) -> str:
    """Gets the template, injects system prompt if needed, formats."""
    template = config.get(template_key, DEFAULT_CONFIG.get(template_key, ''))
    placeholders['system_prompt'] = config.get('system_prompt', DEFAULT_CONFIG.get('system_prompt', ''))

    # Inject user prompts for executor templates
    if template_key in ('executor_prompt_template', 'direct_executor_prompt_template'):
        user_prompts_list = config.get('user_prompts', [])
        # Format user prompts for inclusion - adjust as needed
        user_prompts_str = "\n".join([f"- {p.get('name', 'Prompt')}: {p.get('content', '')[:50]}..." for p in user_prompts_list])
        placeholders['user_prompts'] = user_prompts_str if user_prompts_str else "[No active user prompts]"
    else:
         # Ensure placeholder exists even if not used by template to avoid KeyError
         placeholders['user_prompts'] = "[N/A]"


    try:
        return template.format(**placeholders)
    except KeyError as e:
        logger.error(f"Prompt template error formatting '{template_key}': Missing placeholder {e}. Template Preview:\n{template[:200]}...")
        # Fallback to just the query? Or a very basic structure?
        return placeholders.get('query', '') # Simplistic fallback
    except Exception as e:
        logger.exception(f"Unexpected error formatting prompt template '{template_key}': {e}")
        return placeholders.get('query', '')


def load_project_config(path: Path) -> dict:
    cfg_path = path / ".patchmind.json"
    config = DEFAULT_CONFIG.copy() # Start with fresh defaults

    if cfg_path.exists() and cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding='utf-8') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
            logger.info(f"Loaded project config from {cfg_path}")
        except Exception as e:
            logger.error(f"Failed to load project config from {cfg_path}: {e}. Using defaults.")
    else:
        logger.info(f"No project config found at {cfg_path}. Using defaults.")

    # --- Validate and Ensure Correct Types ---
    str_keys = [
        'provider', 'model', 'api_key', 'system_prompt',
        'planner_prompt_template', 'critic_prompt_template',
        'executor_prompt_template', 'direct_executor_prompt_template',
        'rag_summarizer_prompt_template', 'rag_google_api_key',
        'rag_google_cse_id', 'rag_bing_api_key', 'rag_summarizer_provider',
        'rag_summarizer_model_name',
        'syntax_highlighting_style',
        'editor_font', 'theme', 'last_project_path'
    ]
    bool_keys = [
        'patch_mode', 'whole_file', 'disable_critic_workflow', # <<< ADDED
        'rag_local_enabled', 'rag_external_enabled', 'rag_google_enabled',
        'rag_bing_enabled', 'rag_stackexchange_enabled', 'rag_github_enabled',
        'rag_arxiv_enabled', 'rag_summarizer_enabled'
    ]
    float_keys = ['temperature', 'rag_similarity_threshold']
    int_keys = ['top_k', 'context_limit', 'editor_font_size']
    list_keys = ['rag_local_sources', 'user_prompts'] # Add user_prompts

    for key in str_keys:
        default_value = DEFAULT_CONFIG.get(key, '')
        config[key] = str(config.get(key, default_value))
    for key in bool_keys:
        default_value = DEFAULT_CONFIG.get(key, False)
        config[key] = bool(config.get(key, default_value))
    for key in float_keys:
        default_value = DEFAULT_CONFIG.get(key, 0.0)
        try: config[key] = float(config.get(key, default_value))
        except (ValueError, TypeError): config[key] = default_value
    for key in int_keys:
        default_value = DEFAULT_CONFIG.get(key, 0)
        try: config[key] = int(config.get(key, default_value))
        except (ValueError, TypeError): config[key] = default_value
    for key in list_keys:
        default_value = DEFAULT_CONFIG.get(key, [])
        val = config.get(key, default_value)
        config[key] = list(val) if isinstance(val, list) else default_value

    # Specific validations
    if config['syntax_highlighting_style'] not in AVAILABLE_PYGMENTS_STYLES:
        logger.warning(f"Configured style '{config['syntax_highlighting_style']}' not found. Using default '{DEFAULT_STYLE}'.")
        config['syntax_highlighting_style'] = DEFAULT_STYLE
    if config['rag_ranking_model_name'] not in AVAILABLE_RAG_MODELS:
        logger.warning(f"Configured RAG model '{config['rag_ranking_model_name']}' not found. Using default.")
        config['rag_ranking_model_name'] = AVAILABLE_RAG_MODELS[0]
    if not (0.0 <= config['rag_similarity_threshold'] <= 1.0):
         logger.warning(f"Configured RAG threshold '{config['rag_similarity_threshold']}' out of range. Clamping.")
         config['rag_similarity_threshold'] = max(0.0, min(1.0, config['rag_similarity_threshold']))
    # Validate user_prompts structure (optional)
    valid_user_prompts = []
    for p in config['user_prompts']:
        if isinstance(p, dict) and 'id' in p and 'name' in p and 'content' in p:
            valid_user_prompts.append(p)
        else:
             logger.warning(f"Ignoring invalid user prompt structure: {p}")
    config['user_prompts'] = valid_user_prompts


    return config

def save_project_config(path: Path, cfg: dict):
    cfg_path = path / ".patchmind.json";
    if not path.is_dir(): logger.error(f"Save config fail: invalid path {path}"); return
    try:
        # Ensure all default keys are present in the saved file
        cfg_to_save = {k: cfg.get(k, v) for k, v in DEFAULT_CONFIG.items()}
        cfg_to_save['last_project_path'] = str(path); # Always update last path
        # Make sure the saved style is valid before writing
        if cfg_to_save['syntax_highlighting_style'] not in AVAILABLE_PYGMENTS_STYLES:
             cfg_to_save['syntax_highlighting_style'] = DEFAULT_STYLE
        # Make sure RAG model is valid
        if cfg_to_save['rag_ranking_model_name'] not in AVAILABLE_RAG_MODELS:
             cfg_to_save['rag_ranking_model_name'] = AVAILABLE_RAG_MODELS[0]

        with open(cfg_path, "w", encoding='utf-8') as f:
            json.dump(cfg_to_save, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved config: {cfg_path}")
    except Exception as e:
        logger.error(f"Failed save config {cfg_path}: {e}")
