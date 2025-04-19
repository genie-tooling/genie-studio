# --- START OF FILE pm/core/project_config.py ---
# pm/core/project_config.py
import json
from pathlib import Path
from loguru import logger

# Import AVAILABLE_RAG_MODELS from constants
from .constants import AVAILABLE_RAG_MODELS, AVAILABLE_SCINTILLA_THEMES # Import AVAILABLE_SCINTILLA_THEMES

from .prompts import ( PLANNER_PROMPT_TEMPLATE, CRITIC_PROMPT_TEMPLATE, EXECUTOR_PROMPT_TEMPLATE,
                       DIRECT_EXECUTOR_PROMPT_TEMPLATE, RAG_SUMMARIZER_PROMPT_TEMPLATE )

# --- Default RAG Patterns ---
DEFAULT_RAG_EXCLUDE_PATTERNS = [
    '*.min.js', '*.min.css', '*.map', 'package-lock.json', 'poetry.lock',
    '*.log', '*.tmp', '*.bak', '*.swp', '.DS_Store', 'Thumbs.db',
    '*.pyc', '*.pyo', '.git/*', '.venv/*', 'venv/*', '__pycache__/*',
    'node_modules/*', '.mypy_cache/*', '.pytest_cache/*',
    '*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp', '*.ico', '*.svg',
    '*.zip', '*.tar', '*.gz', '*.rar', '*.7z',
    '*.pdf', '*.doc', '*.docx', '*.xls', '*.xlsx', '*.ppt', '*.pptx',
    '*.o', '*.a', '*.so', '*.lib', '*.dll', '*.exe', '*.bin',
    '*.mp3', '*.wav', '*.ogg', '*.mp4', '*.mov', '*.avi', '*.webm',
    '*.db', '*.sqlite', '*.sqlite3',
]
DEFAULT_RAG_INCLUDE_PATTERNS = ['*']

# --- MODIFIED: Update DEFAULT_CONFIG for editor_theme ---
DEFAULT_CONFIG = {
    # LLM Settings
    "provider": "Ollama", "model": "llama3:8b", "api_key": "",
    "temperature": 0.3, "top_k": 40, "context_limit": 8192,

    # Prompts
    "system_prompt": "You are a helpful AI assistant expert in software development.",
    "planner_prompt_template": PLANNER_PROMPT_TEMPLATE, "critic_prompt_template": CRITIC_PROMPT_TEMPLATE,
    "executor_prompt_template": EXECUTOR_PROMPT_TEMPLATE, "direct_executor_prompt_template": DIRECT_EXECUTOR_PROMPT_TEMPLATE,
    "rag_summarizer_prompt_template": RAG_SUMMARIZER_PROMPT_TEMPLATE,

    # Features
    "patch_mode": True, "whole_file": True, "disable_critic_workflow": False,

    # RAG Settings
    "rag_local_enabled": False, "rag_local_sources": [],
    "rag_external_enabled": True, "rag_google_enabled": False, "rag_bing_enabled": True,
    "rag_stackexchange_enabled": True, "rag_github_enabled": True, "rag_arxiv_enabled": False,
    "rag_google_api_key": "", "rag_google_cse_id": "", "rag_bing_api_key": "",
    "rag_dir_max_depth": 3,
    "rag_dir_include_patterns": DEFAULT_RAG_INCLUDE_PATTERNS,
    "rag_dir_exclude_patterns": DEFAULT_RAG_EXCLUDE_PATTERNS,

    # Ranking Configuration
    "rag_ranking_model_name": AVAILABLE_RAG_MODELS[0] if AVAILABLE_RAG_MODELS else "", "rag_similarity_threshold": 0.30,

    # Query Summarizer Settings
    "rag_summarizer_enabled": True, "rag_summarizer_provider": "Ollama", "rag_summarizer_model_name": "llama3:8b",

    # Appearance
    'editor_font': 'Fira Code',
    'editor_font_size': 11,
    'theme': 'Dark', # Overall QSS theme
    # --- NEW: Editor Syntax Highlighting Theme ---
    'editor_theme': AVAILABLE_SCINTILLA_THEMES[0] if AVAILABLE_SCINTILLA_THEMES else "Native Dark", # Default syntax theme
    # --- REMOVED: Old syntax style ---
    # 'syntax_highlighting_style': 'native',

    # User Prompts
    'user_prompts': [],
    'selected_prompt_ids': [],
}
# ---------------------------------------------------

def get_effective_prompt(config: dict, template_key: str, placeholders: dict) -> str:
    template = config.get(template_key, DEFAULT_CONFIG.get(template_key, ''))
    system_prompt_base = config.get('system_prompt', DEFAULT_CONFIG.get('system_prompt', ''))
    selected_prompt_ids = config.get('selected_prompt_ids', [])
    all_prompts = config.get('user_prompts', [])
    prompts_by_id = {p['id']: p for p in all_prompts}
    user_prompt_content_parts = [prompts_by_id[pid]['content'] for pid in selected_prompt_ids if pid in prompts_by_id]
    final_system_prompt = system_prompt_base

    if user_prompt_content_parts:
        final_system_prompt += "\n\n--- User Instructions ---\n" + "\n\n".join(user_prompt_content_parts)

    placeholders['system_prompt'] = final_system_prompt
    placeholders['user_prompts'] = "\n".join([f"- {p.get('name', 'Prompt')}" for p in all_prompts if p.get('id') in selected_prompt_ids]) if selected_prompt_ids else "[No active user prompts]"

    try:
        return template.format(**placeholders)

    except KeyError as e:
        logger.error(f"Prompt template error formatting '{template_key}': Missing placeholder {e}. Placeholder keys: {list(placeholders.keys())}. Template Preview:\n{template[:200]}...")

        return placeholders.get('query', '')

    except Exception as e:
        logger.exception(f"Unexpected error formatting prompt template '{template_key}': {e}")

        return placeholders.get('query', '')

def load_project_config(path: Path) -> dict:
    return DEFAULT_CONFIG.copy()

def save_project_config(path: Path, cfg: dict):
    pass