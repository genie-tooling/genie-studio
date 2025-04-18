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

# Define standard placeholders for the prompt template
DEFAULT_PROMPT_TEMPLATE = """<SYSTEM_PROMPT>
{system_prompt}
INSTRUCTIONS: Use the information provided in the <CONTEXT_SOURCES> section below to answer the <USER_QUERY>. Prioritize information from <CONTEXT_SOURCES> over general knowledge. If the context doesn't contain the answer, state that. Cite the source file or RAG title/URL if possible.
</SYSTEM_PROMPT>

<CHAT_HISTORY>
{chat_history}
</CHAT_HISTORY>

<CONTEXT_SOURCES>
[Code Context]
{code_context}

[Local Context]
{local_context}

[External Context]
{remote_context}
</CONTEXT_SOURCES>

<USER_QUERY>
{user_query}
</USER_QUERY>

Assistant Response:"""

DEFAULT_CONFIG = {
    # LLM Settings
    "provider": "Ollama", "model": "llama3:8b", "api_key": "",
    "temperature": 0.3, "top_k": 40, "context_limit": 8192,

    # --- Prompts ---
    "system_prompt": "You are a helpful AI assistant expert in software development.",
    "main_prompt_template": DEFAULT_PROMPT_TEMPLATE, # <<< ADDED
    # --- (Keep RAG Summarizer Prompt Separate for now) ---
    "rag_summarizer_prompt_template": """Condense the following chat history and user query into a concise and effective search query suitable for web search engines or code repositories. Focus on the key entities, concepts, and the user's goal.

<CHAT_HISTORY_AND_QUERY>
{original_query}
</CHAT_HISTORY_AND_QUERY>

Search Query:""",

    # Features (Core)
    "patch_mode": True, "whole_file": True,

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
    # rag_summarizer_prompt_template defined above

    # Appearance
    'editor_font': 'Fira Code', 'editor_font_size': 11, 'theme': 'Dark',
    'syntax_highlighting_style': DEFAULT_STYLE,
    'last_project_path': str(Path.cwd())
}

# ... (load_project_config function) ...
def load_project_config(path: Path) -> dict:
    # ... (previous loading logic) ...
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

    # --- Validate and Ensure Correct Types (ensure new template is string) ---
    # ... (keep existing validations) ...
    str_keys = [
        'provider', 'model', 'api_key', 'system_prompt',
        'main_prompt_template', # <<< ADDED TO VALIDATION
        'rag_google_api_key',
        'rag_google_cse_id', 'rag_bing_api_key', 'rag_summarizer_provider',
        'rag_summarizer_model_name', 'rag_summarizer_prompt_template',
        'syntax_highlighting_style', # <<< ADD TO VALIDATION
        'editor_font', 'theme', 'last_project_path'
    ]
    for key in str_keys:
        # Ensure key exists and is a string, falling back to default then empty string
        default_value = DEFAULT_CONFIG.get(key, '')
        config[key] = str(config.get(key, default_value))

    if config['syntax_highlighting_style'] not in AVAILABLE_PYGMENTS_STYLES:
        logger.warning(f"Configured style '{config['syntax_highlighting_style']}' not found. Using default '{DEFAULT_STYLE}'.")
        config['syntax_highlighting_style'] = DEFAULT_STYLE

    # --- Ensure default template if missing or empty after load ---
    if not config.get('main_prompt_template', '').strip():
        logger.warning("Main prompt template missing or empty in config, restoring default.")
        config['main_prompt_template'] = DEFAULT_CONFIG['main_prompt_template']


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

        with open(cfg_path, "w", encoding='utf-8') as f:
            json.dump(cfg_to_save, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved config: {cfg_path}")
    except Exception as e:
        logger.error(f"Failed save config {cfg_path}: {e}")