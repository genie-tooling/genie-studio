# --- START OF FILE pm/core/settings_service.py ---
# pm/core/settings_service.py
import json
import uuid
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMessageBox, QApplication
from loguru import logger
from typing import Any, Dict, List, Optional

from .project_config import DEFAULT_CONFIG, AVAILABLE_RAG_MODELS
# Import AVAILABLE_SCINTILLA_THEMES from constants
from .constants import AVAILABLE_SCINTILLA_THEMES

# Attempt to get available Pygments styles (still needed for old validation key, or if used elsewhere)
try:
    from pygments.styles import get_all_styles
    AVAILABLE_PYGMENTS_STYLES = list(get_all_styles())
except ImportError:
    # logger.warning("Pygments library not found...") # Logged in constants
    AVAILABLE_PYGMENTS_STYLES = ["native"] # Provide a fallback

class SettingsService(QObject):
    """
    Manages loading, saving, accessing, and validating application settings.
    Acts as the single source of truth for configuration (merging defaults + project).
    """
    settings_loaded = pyqtSignal()
    settings_saved = pyqtSignal()
    settings_changed = pyqtSignal(str, object) # key, new_value
    prompts_changed = pyqtSignal(list)
    theme_changed = pyqtSignal(str) # For overall QSS theme (Dark/Light)
    font_changed = pyqtSignal(str, int)
    # --- RENAMED/NEW: Signal for editor syntax theme change ---
    # Keeping syntax_style_changed for backward compat if needed, but using new one
    # syntax_style_changed = pyqtSignal(str)
    editor_theme_changed = pyqtSignal(str)
    # ----------------------------------------------------------
    llm_config_changed = pyqtSignal()
    rag_config_changed = pyqtSignal()
    local_rag_sources_changed = pyqtSignal(list)
    project_path_changed = pyqtSignal(Path)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._settings: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self._project_path: Optional[Path] = None
        logger.info("SettingsService initialized.")

    def load_project(self, project_path: Path) -> bool:
        logger.info(f"SettingsService: Loading project at {project_path}")
        path = Path(project_path).resolve()
        if not path.is_dir():
            logger.error(f"SettingsService: Invalid project path provided: {path}")
            return False

        self._project_path = path
        self.project_path_changed.emit(path)

        cfg_path = path / ".patchmind.json"
        loaded_config = {}
        config_exists = cfg_path.exists() and cfg_path.is_file()
        config_valid = True

        if config_exists:
            try:
                with open(cfg_path, "r", encoding='utf-8') as f:
                    loaded_config = json.load(f)
                logger.info(f"SettingsService: Loaded project config from {cfg_path}")
            except json.JSONDecodeError as e:
                logger.error(f"SettingsService: Invalid JSON in config file {cfg_path}: {e}. Using defaults.")
                config_valid = False
                loaded_config = {}
            except Exception as e:
                logger.error(f"SettingsService: Failed to read config file {cfg_path}: {e}. Using defaults.")
                config_valid = False
                loaded_config = {}
        else:
            logger.info(f"SettingsService: No project config found at {cfg_path}. Using defaults.")

        temp_config = DEFAULT_CONFIG.copy()
        temp_config.update(loaded_config)

        # --- Handle migration/fallback for old 'syntax_highlighting_style' ---
        corrections_made = False # Initialize flag for this method

        if 'syntax_highlighting_style' in loaded_config and 'editor_theme' not in loaded_config:
             old_style = loaded_config['syntax_highlighting_style']
             # Simple migration: map old 'native' to new 'Native Dark'
             if old_style == 'native':
                  temp_config['editor_theme'] = 'Native Dark'
                  logger.info("Migrated old 'syntax_highlighting_style' ('native') to 'editor_theme' ('Native Dark').")
                  corrections_made = True
             else:
                  logger.warning(f"Ignoring unknown old 'syntax_highlighting_style': '{old_style}'. Using default 'editor_theme'.")
                  # If old style is unknown, still mark correction if it was present
                  if old_style is not None: corrections_made = True

             # Remove the old key to prevent it from appearing in saved settings
             if 'syntax_highlighting_style' in temp_config:
                  del temp_config['syntax_highlighting_style']
                  corrections_made = True # Removing an old key counts as a correction

        # ----------------------------------------------------------------------

        validated_config, corrections_made_validation = self._validate_config(temp_config)
        self._settings = validated_config
        self._settings['last_project_path'] = str(self._project_path)

        # Combine migration corrections with validation corrections
        total_corrections_made = corrections_made or corrections_made_validation

        self.settings_loaded.emit()
        logger.info("SettingsService: Project settings loaded and validated.")

        if not config_valid:
            QMessageBox.warning(QApplication.activeWindow(), "Configuration Error",
                                 f"The project config '.patchmind.json' is invalid.\nDefault settings loaded. Invalid file will be overwritten on save.")
        elif config_exists and total_corrections_made:
            logger.warning("SettingsService: Project configuration updated to match current defaults/structure.")

        self._emit_all_specific_pyqtSignals()

        return True

    def save_settings(self) -> bool:
        """Saves the current IN-MEMORY settings to the project's config file."""
        if not self._project_path or not self._project_path.is_dir():
            logger.error("SettingsService: Cannot save settings, project path not set or invalid.")
            return False

        cfg_path = self._project_path / ".patchmind.json"
        logger.info(f"SettingsService: Saving effective settings to {cfg_path}...")

        try:
            # Create a dictionary to save, including only keys from DEFAULT_CONFIG
            # This prevents saving transient or internal keys like 'last_project_path'
            # directly into the project config file, unless they are explicitly in DEFAULT_CONFIG.
            # However, 'last_project_path' IS in DEFAULT_CONFIG, so it will be saved.
            # If you want to exclude 'last_project_path' from project config,
            # remove it from DEFAULT_CONFIG and handle it as a global setting (e.g., in QSettings).
            # For now, keeping it simple and saving all keys in DEFAULT_CONFIG.
            cfg_to_save = {k: self._settings[k] for k in DEFAULT_CONFIG.keys() if k in self._settings}

            # Ensure prompts list is valid before saving
            prompts = cfg_to_save.get('user_prompts', [])
            if not isinstance(prompts, list):
                logger.error("Invalid 'user_prompts' type during save, saving empty list.")
                cfg_to_save['user_prompts'] = []
            else:
                # Filter out any invalid prompt structures just in case
                cfg_to_save['user_prompts'] = [p for p in prompts if isinstance(p, dict) and all(k in p for k in ['id', 'name', 'content'])]

            # Ensure local RAG sources list is valid before saving
            local_rag_sources = cfg_to_save.get('rag_local_sources', [])
            if not isinstance(local_rag_sources, list):
                 logger.error("Invalid 'rag_local_sources' type during save, saving empty list.")
                 cfg_to_save['rag_local_sources'] = []
            else:
                 # Filter out any invalid source structures
                 cfg_to_save['rag_local_sources'] = [s for s in local_rag_sources if isinstance(s, dict) and 'path' in s and isinstance(s['path'], str)]


            with open(cfg_path, "w", encoding='utf-8') as f:
                json.dump(cfg_to_save, f, indent=2, ensure_ascii=False)

            logger.info(f"SettingsService: Settings saved successfully to project file.")
            self.settings_saved.emit()

            return True

        except Exception as e:
            logger.exception(f"SettingsService: Failed to save config to {cfg_path}: {e}")
            # Use QApplication.activeWindow() for parent if self.parent() is None
            parent_widget = self.parent() if self.parent() else QApplication.activeWindow()
            QMessageBox.critical(parent_widget, "Save Error",
                                 f"Failed to save settings to:\n{cfg_path}\n\nError: {e}")

            return False

    def _validate_config(self, config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        """Validates config dict against DEFAULT_CONFIG, ensures types, applies defaults."""
        validated = {}
        corrections_made = False

        for key, default_value in DEFAULT_CONFIG.items():
            current_value = config.get(key)
            expected_type = type(default_value)
            corrected = False

            if current_value is None:
                validated[key] = default_value
                corrected = True
                logger.debug(f"Validate: Added missing key '{key}' with default.")

            elif not isinstance(current_value, expected_type):
                original_type = type(current_value)

                try:
                    if expected_type is int and isinstance(current_value, (float, str)):
                        validated[key] = int(current_value)

                    elif expected_type is float and isinstance(current_value, (int, str)):
                        validated[key] = float(current_value)

                    elif expected_type is bool and isinstance(current_value, str):
                        val_lower = current_value.lower()

                        if val_lower in ['true', '1', 'yes']:
                            validated[key] = True

                        elif val_lower in ['false', '0', 'no']:
                            validated_value = False
                            can_assign = True # Need to set validated_value here
                            validated[key] = validated_value # Assign validated_value

                        else:
                            raise ValueError("Invalid boolean string")

                    elif expected_type is list and isinstance(current_value, (tuple)):
                        validated[key] = list(current_value)

                    elif expected_type is list and not isinstance(current_value, list):
                        raise ValueError("Expected list")

                    elif expected_type is dict and not isinstance(current_value, dict):
                        raise ValueError("Expected dict")

                    elif expected_type is str and not isinstance(current_value, str):
                         # Ensure str is handled carefully to avoid coercing lists/dicts to "[...]" or "{...}"
                         if original_type in (list, dict):
                              raise TypeError(f"Cannot coerce {original_type} to {expected_type}")
                         validated[key] = str(current_value)

                    else:
                        # If none of the specific coercions worked, try a generic cast
                        validated[key] = expected_type(current_value)


                    logger.warning(f"Validate: Corrected type for '{key}'. Expected {expected_type}, got {original_type}.")
                    corrected = True

                except (ValueError, TypeError, Exception) as e:
                    logger.warning(f"Validate: Failed type correction for '{key}' (Expected {expected_type}, Got {original_type}). Using default. Error: {e}")
                    validated[key] = default_value
                    corrected = True

            else:
                validated[key] = current_value

            # --- Specific Value Validations ---
            if key == 'rag_ranking_model_name':
                # Ensure AVAILABLE_RAG_MODELS is not empty before checking
                if AVAILABLE_RAG_MODELS and validated[key] not in AVAILABLE_RAG_MODELS:
                    logger.warning(f"Validate: Invalid RAG model '{validated[key]}'. Using default '{AVAILABLE_RAG_MODELS[0]}'.")
                    validated[key] = AVAILABLE_RAG_MODELS[0]
                    corrected = True
                elif not AVAILABLE_RAG_MODELS:
                     logger.warning("Validate: AVAILABLE_RAG_MODELS is empty. Cannot validate 'rag_ranking_model_name'. Keeping value.")


            elif key == 'rag_similarity_threshold':
                val = validated[key]

                if not isinstance(val, float) or not (0.0 <= val <= 1.0):
                    logger.warning(f"Validate: Invalid RAG threshold '{val}'. Clamping to [0,1].")
                    # Ensure default value is also clamped if needed
                    default_clamped = max(0.0, min(1.0, float(DEFAULT_CONFIG.get(key, 0.30))))
                    validated[key] = max(0.0, min(1.0, float(val) if isinstance(val, (int, float, str)) else default_clamped))
                    corrected = True

            elif key == 'rag_local_sources':
                sources = validated[key]
                valid_sources = []
                list_changed = False

                if not isinstance(sources, list):
                    logger.warning(f"Validate: Correcting 'rag_local_sources' from {type(sources)} to list.")
                    sources = []
                    list_changed = True

                for item in sources:
                    if isinstance(item, dict) and 'path' in item and isinstance(item['path'], str):
                        # Ensure 'enabled' key exists and is boolean
                        valid_sources.append({'path':item['path'],'enabled':bool(item.get('enabled',True))})

                    elif isinstance(item, str):
                        valid_sources.append({'path':item,'enabled':True})
                        list_changed = True

                    else:
                        logger.warning(f"Validate: Removing invalid local RAG source structure: {item}")
                        list_changed = True

                validated[key] = valid_sources

                if list_changed:
                    corrected = True

            elif key == 'user_prompts':
                prompts = validated[key]
                valid_prompts = []
                list_changed = False

                if not isinstance(prompts, list):
                    logger.warning(f"Validate: Correcting 'user_prompts' from {type(prompts)} to list.")
                    prompts = []
                    list_changed = True

                seen_ids = set()

                for i, p in enumerate(prompts):
                    # Check for required keys and types
                    if isinstance(p, dict) and \
                       p.get('id') and isinstance(p.get('id'), str) and \
                       p.get('name') and isinstance(p.get('name'), str) and \
                       isinstance(p.get('content'), str): # Content can be empty string
                        prompt_id = p['id']

                        if prompt_id in seen_ids:
                            logger.warning(f"Validate: Duplicate prompt ID '{prompt_id}' found at index {i}. Regenerating ID.")
                            p['id'] = str(uuid.uuid4())
                            list_changed = True

                        seen_ids.add(p['id'])
                        # Store a clean version
                        valid_prompts.append({'id': p['id'], 'name': p['name'], 'content': p['content']})

                    else:
                        logger.warning(f"Validate: Removing invalid user prompt structure at index {i}: {p}")
                        list_changed = True

                validated[key] = valid_prompts

                if list_changed:
                    corrected = True

            elif key == 'rag_dir_max_depth':
                val = validated[key]

                if not isinstance(val, int) or not (0 <= val <= 10):
                    logger.warning(f"Validate: Invalid RAG depth '{val}'. Clamping to [0, 10].")
                    # Ensure default is also clamped
                    default_clamped = max(0, min(10, int(DEFAULT_CONFIG.get(key, 3))))
                    validated[key] = max(0, min(10, int(val) if isinstance(val, (int, float, str)) else default_clamped))
                    corrected = True

            elif key == 'rag_dir_include_patterns':
                 if not isinstance(validated[key], list):
                      logger.warning(f"Validate: Correcting 'rag_dir_include_patterns' from {type(validated[key])} to list.")
                      validated[key] = DEFAULT_CONFIG.get(key, []) # Use default list if available
                      corrected = True
                 # Optional: Validate list elements are strings

            elif key == 'rag_dir_exclude_patterns':
                 if not isinstance(validated[key], list):
                      logger.warning(f"Validate: Correcting 'rag_dir_exclude_patterns' from {type(validated[key])} to list.")
                      validated[key] = DEFAULT_CONFIG.get(key, []) # Use default list if available
                      corrected = True
                 # Optional: Validate list elements are strings

            # --- NEW Validation for editor_theme ---
            elif key == 'editor_theme':
                 # Ensure AVAILABLE_SCINTILLA_THEMES is not empty before checking
                 if AVAILABLE_SCINTILLA_THEMES and validated[key] not in AVAILABLE_SCINTILLA_THEMES:
                      logger.warning(f"Validate: Invalid editor theme '{validated[key]}'. Using default '{DEFAULT_CONFIG.get(key, AVAILABLE_SCINTILLA_THEMES[0])}'.")
                      validated[key] = DEFAULT_CONFIG.get(key, AVAILABLE_SCINTILLA_THEMES[0] if AVAILABLE_SCINTILLA_THEMES else "Native Dark")
                      corrected = True
                 elif not AVAILABLE_SCINTILLA_THEMES:
                      logger.warning("Validate: AVAILABLE_SCINTILLA_THEMES is empty. Cannot validate 'editor_theme'. Keeping value.")

            # --- Removed old syntax_highlighting_style validation ---
            # elif key == 'syntax_highlighting_style': ... removed ...

            if corrected:
                corrections_made = True

        # Check for unknown keys in the loaded config that are NOT in DEFAULT_CONFIG
        # This helps clean up old/unused keys in the config file on save
        ignored_keys = set(config.keys()) - set(DEFAULT_CONFIG.keys())

        if ignored_keys:
            logger.warning(f"Validate: Ignored unknown keys from config file: {ignored_keys}")
            # These keys are not added to `validated`, so they won't be saved.

        return validated, corrections_made

    def get_setting(self, key: str, default: Optional[Any] = None) -> Any:
        # Use DEFAULT_CONFIG as the ultimate fallback if key isn't even in _settings
        fallback = DEFAULT_CONFIG.get(key, default)

        return self._settings.get(key, fallback)

    def get_all_settings(self) -> Dict[str, Any]:
        return self._settings.copy()

    def get_project_path(self) -> Optional[Path]:
        return self._project_path

    @pyqtSlot(str, object)
    def set_setting(self, key: str, value: Any):
        if key not in DEFAULT_CONFIG:
            logger.warning(f"SettingsService: Set rejected for unknown key '{key}'.")
            return

        expected_type = type(DEFAULT_CONFIG[key])
        validated_value = value
        can_assign = False

        # Attempt type coercion if necessary
        if isinstance(validated_value, expected_type):
            can_assign = True

        else:
            try:
                if expected_type is float and isinstance(validated_value, int):
                    validated_value = float(validated_value)
                    can_assign = True

                elif expected_type is int and isinstance(validated_value, (float, str)):
                    # Try converting float/string to int
                    validated_value = int(float(validated_value)) if isinstance(validated_value, str) else int(validated_value)
                    can_assign = True

                elif expected_type is float and isinstance(validated_value, str):
                    validated_value = float(validated_value)
                    can_assign = True

                elif expected_type is bool and isinstance(validated_value, str):
                    val_lower = validated_value.lower()

                    if val_lower in ['true', '1', 'yes']:
                        validated_value = True
                        can_assign = True

                    elif val_lower in ['false', '0', 'no']:
                        validated_value = False
                        can_assign = True

                    else:
                        raise ValueError("Invalid boolean string")

                elif expected_type is list and isinstance(validated_value, (tuple)):
                    validated_value = list(validated_value)
                    can_assign = True

                elif expected_type is list and not isinstance(validated_value, list):
                    raise ValueError("Expected list")

                elif expected_type is dict and not isinstance(validated_value, dict):
                    raise ValueError("Expected dict")

                elif expected_type is str and not isinstance(validated_value, str):
                    # Ensure str is handled carefully to avoid coercing lists/dicts
                     if type(value) in (list, dict): # Check original type here
                         raise TypeError(f"Cannot coerce {type(value)} to {expected_type}")
                     validated_value = str(validated_value)
                     can_assign = True # Mark as assignable if str conversion worked

                # If none of the specific coercions worked, and can_assign is still False,
                # the types are incompatible. The check below will handle this.

            except (ValueError, TypeError, Exception) as e:
                logger.warning(f"SettingsService: Set rejected for '{key}'. Type mismatch or coercion failed. Expected {expected_type}, got {type(value)}. Error: {e}")

                return # Stop here if coercion failed

        # If after coercion attempt, the type is still not the expected type, reject.
        if not isinstance(validated_value, expected_type):
             logger.warning(f"SettingsService: Set rejected for '{key}'. Final validated value type {type(validated_value)} does not match expected {expected_type}. Original type: {type(value)}")
             return


        try:
            # --- Specific Value Validations (after type is confirmed) ---
            if key == 'rag_ranking_model_name':
                # Ensure AVAILABLE_RAG_MODELS is not empty before checking
                if AVAILABLE_RAG_MODELS and validated_value not in AVAILABLE_RAG_MODELS:
                    logger.warning(f"Set rejected for RAG model '{validated_value}', not available. Keeping old.")

                    return
                elif not AVAILABLE_RAG_MODELS:
                     logger.warning("Set: AVAILABLE_RAG_MODELS is empty. Cannot validate 'rag_ranking_model_name'. Setting value.")


            if key == 'rag_similarity_threshold':
                # Type is already float due to coercion attempt
                if not (0.0 <= validated_value <= 1.0):
                    logger.warning(f"Set rejected for RAG threshold '{validated_value}', out of range [0,1]. Keeping old.")

                    return

            if key == 'rag_dir_max_depth':
                # Type is already int due to coercion attempt
                if not (0 <= validated_value <= 10):
                    logger.warning(f"Set rejected for RAG depth '{validated_value}', out of range [0, 10]. Keeping old.")

                    return

            if key == 'user_prompts':
                # Type is already list due to coercion attempt
                # Perform basic validation of list contents
                if not all(isinstance(p, dict) and all(k in p for k in ['id', 'name', 'content']) for p in validated_value):
                     logger.warning(f"Set rejected for 'user_prompts'. List contains invalid prompt structures. Keeping old.")
                     return
                # Optional: Check for duplicate IDs here if needed, but validation handles it on load/save


            # --- NEW Validation for editor_theme ---
            if key == 'editor_theme':
                 # Ensure AVAILABLE_SCINTILLA_THEMES is not empty before checking
                 if AVAILABLE_SCINTILLA_THEMES and validated_value not in AVAILABLE_SCINTILLA_THEMES:
                      logger.warning(f"Set rejected for editor theme '{validated_value}', not available. Keeping old.")

                      return
                 elif not AVAILABLE_SCINTILLA_THEMES:
                      logger.warning("Set: AVAILABLE_SCINTILLA_THEMES is empty. Cannot validate 'editor_theme'. Setting value.")

            # --- Removed old syntax_highlighting_style validation ---
            # if key == 'syntax_highlighting_style': ... removed ...

        except Exception as e:
            logger.error(f"Error during specific validation for key '{key}', value '{validated_value}': {e}")

            return # Stop here if specific validation failed

        old_value = self._settings.get(key)

        # Compare values. Special handling for lists/dicts if necessary (deep comparison)
        # For simplicity, assume direct comparison is sufficient for now, or rely on validation
        # ensuring consistent structure.
        if old_value != validated_value:
            logger.debug(f"SettingsService: Setting '{key}' changed from '{old_value}' to '{validated_value}' (in memory)")
            self._settings[key] = validated_value
            self.settings_changed.emit(key, validated_value)
            self._emit_specific_pyqtSignals(key, validated_value)

        else:
            logger.trace(f"SettingsService: Set skipped for '{key}', value unchanged.")

    def _emit_specific_pyqtSignals(self, key: str, value: Any):
        logger.trace(f"SettingsService: Emitting specific pyqtSignals for key '{key}'")

        if key == 'theme':
            self.theme_changed.emit(value)

        elif key == 'editor_font':
            # Ensure font size is also passed, fetching it from settings
            font_size = self.get_setting('editor_font_size', DEFAULT_CONFIG.get('editor_font_size', 11))
            self.font_changed.emit(value, font_size)

        elif key == 'editor_font_size':
            # Ensure font family is also passed, fetching it from settings
            font_family = self.get_setting('editor_font', DEFAULT_CONFIG.get('editor_font', 'Fira Code'))
            self.font_changed.emit(font_family, value)

        # --- NEW Signal for editor_theme ---
        elif key == 'editor_theme':
             self.editor_theme_changed.emit(value)
        # --- Removed old syntax_highlighting_style signal emit ---
        # elif key == 'syntax_highlighting_style': ... removed ...

        elif key in ['provider', 'model', 'api_key', 'temperature', 'top_k',
                     'rag_summarizer_provider', 'rag_summarizer_model_name', 'rag_summarizer_enabled']:
            self.llm_config_changed.emit()

        elif key.startswith('rag_') and key not in ['rag_local_sources', 'rag_dir_max_depth', 'rag_dir_include_patterns', 'rag_dir_exclude_patterns', 'rag_ranking_model_name', 'rag_similarity_threshold', 'rag_summarizer_provider', 'rag_summarizer_model_name', 'rag_summarizer_enabled']:
             # Catch other rag keys not specifically handled
             self.rag_config_changed.emit()

        elif key in ['rag_dir_max_depth', 'rag_dir_include_patterns', 'rag_dir_exclude_patterns', 'rag_ranking_model_name', 'rag_similarity_threshold']:
             # These also affect RAG context gathering logic
             self.rag_config_changed.emit()

        elif key == 'user_prompts':
            # Emitting the list itself is fine, handlers can fetch the full list via get_user_prompts
            if isinstance(value, list):
                self.prompts_changed.emit(self.get_user_prompts())

            else:
                logger.error(f"Internal error: Tried to emit prompts_changed but value is not list: {type(value)}")

        elif key == 'selected_prompt_ids':
             # This also affects LLM config (prompts included in context)
             self.llm_config_changed.emit()

        elif key == 'rag_local_sources':
            if isinstance(value, list):
                self.local_rag_sources_changed.emit(self.get_local_rag_sources())
                # Changes to local sources also affect RAG config
                self.rag_config_changed.emit()

            else:
                logger.error(f"Internal error: Tried to emit local_rag_sources_changed but value is not list: {type(value)}")

        elif key in ['patch_mode', 'whole_file', 'disable_critic_workflow']:
             # These affect task execution logic
             self.rag_config_changed.emit() # Re-using rag_config_changed for now, maybe need a 'workflow_config_changed'

    def _emit_all_specific_pyqtSignals(self):
        logger.debug("SettingsService: Emitting all specific pyqtSignals post-load.")

        # Emit signals in a logical order
        # Appearance first
        self._emit_specific_pyqtSignals('theme', self.get_setting('theme'))
        self._emit_specific_pyqtSignals('editor_font', self.get_setting('editor_font'))
        self._emit_specific_pyqtSignals('editor_font_size', self.get_setting('editor_font_size'))
        self._emit_specific_pyqtSignals('editor_theme', self.get_setting('editor_theme'))

        # LLM/RAG config (order might matter for dependencies)
        self._emit_specific_pyqtSignals('provider', self.get_setting('provider'))
        self._emit_specific_pyqtSignals('model', self.get_setting('model'))
        self._emit_specific_pyqtSignals('api_key', self.get_setting('api_key'))
        self._emit_specific_pyqtSignals('temperature', self.get_setting('temperature'))
        self._emit_specific_pyqtSignals('top_k', self.get_setting('top_k'))
        self._emit_specific_pyqtSignals('rag_summarizer_provider', self.get_setting('rag_summarizer_provider'))
        self._emit_specific_pyqtSignals('rag_summarizer_model_name', self.get_setting('rag_summarizer_model_name'))
        self._emit_specific_pyqtSignals('rag_summarizer_enabled', self.get_setting('rag_summarizer_enabled'))

        # RAG sources/defaults
        self._emit_specific_pyqtSignals('rag_local_enabled', self.get_setting('rag_local_enabled'))
        self._emit_specific_pyqtSignals('rag_local_sources', self.get_setting('rag_local_sources')) # This emits local_rag_sources_changed & rag_config_changed
        self._emit_specific_pyqtSignals('rag_external_enabled', self.get_setting('rag_external_enabled'))
        self._emit_specific_pyqtSignals('rag_google_enabled', self.get_setting('rag_google_enabled'))
        self._emit_specific_pyqtSignals('rag_bing_enabled', self.get_setting('rag_bing_enabled'))
        self._emit_specific_pyqtSignals('rag_stackexchange_enabled', self.get_setting('rag_stackexchange_enabled'))
        self._emit_specific_pyqtSignals('rag_github_enabled', self.get_setting('rag_github_enabled'))
        self._emit_specific_pyqtSignals('rag_arxiv_enabled', self.get_setting('rag_arxiv_enabled'))
        self._emit_specific_pyqtSignals('rag_google_api_key', self.get_setting('rag_google_api_key'))
        self._emit_specific_pyqtSignals('rag_google_cse_id', self.get_setting('rag_google_cse_id'))
        self._emit_specific_pyqtSignals('rag_bing_api_key', self.get_setting('rag_bing_api_key'))
        self._emit_specific_pyqtSignals('rag_dir_max_depth', self.get_setting('rag_dir_max_depth'))
        self._emit_specific_pyqtSignals('rag_dir_include_patterns', self.get_setting('rag_dir_include_patterns'))
        self._emit_specific_pyqtSignals('rag_dir_exclude_patterns', self.get_setting('rag_dir_exclude_patterns'))
        self._emit_specific_pyqtSignals('rag_ranking_model_name', self.get_setting('rag_ranking_model_name'))
        self._emit_specific_pyqtSignals('rag_similarity_threshold', self.get_setting('rag_similarity_threshold'))

        # Prompts
        self._emit_specific_pyqtSignals('user_prompts', self.get_setting('user_prompts')) # This emits prompts_changed
        self._emit_specific_pyqtSignals('selected_prompt_ids', self.get_setting('selected_prompt_ids')) # This emits llm_config_changed

        # Features
        self._emit_specific_pyqtSignals('patch_mode', self.get_setting('patch_mode'))
        self._emit_specific_pyqtSignals('whole_file', self.get_setting('whole_file'))
        self._emit_specific_pyqtSignals('disable_critic_workflow', self.get_setting('disable_critic_workflow'))


    def get_user_prompts(self) -> List[Dict[str, Any]]:
        prompts = self._settings.get('user_prompts', [])

        if not isinstance(prompts, list):
            logger.error("Internal state error: 'user_prompts' is not a list. Returning empty.")

            return []

        # Return a copy to prevent external modification of internal state
        return [p.copy() for p in prompts if isinstance(p, dict)]

    def get_prompt_by_id(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        prompts = self._settings.get('user_prompts', [])

        if not isinstance(prompts, list):
            return None

        for prompt in prompts:
            if isinstance(prompt, dict) and prompt.get('id') == prompt_id:
                return prompt.copy() # Return a copy

        return None

    def add_prompt(self, prompt_data: Dict[str, Any]) -> bool:
        if not isinstance(prompt_data, dict):
            logger.error(f"Add prompt failed: Input data is not a dict: {prompt_data}")

            return False

        # Basic validation of required keys and types
        if not all(k in prompt_data for k in ['id', 'name', 'content']) or \
           not isinstance(prompt_data.get('id'), str) or \
           not isinstance(prompt_data.get('name'), str) or \
           not isinstance(prompt_data.get('content'), str):
            logger.error(f"Add prompt failed: Invalid data structure or types: {prompt_data}")

            return False

        prompt_id = prompt_data['id']

        # Generate new ID if empty or already exists
        if not prompt_id or self.get_prompt_by_id(prompt_id):
            if prompt_id: logger.warning(f"Add prompt: Provided ID '{prompt_id}' already exists. Generating new one.")
            else: logger.warning("Add prompt: Provided ID was empty, generating new one.")
            prompt_id = str(uuid.uuid4())
            prompt_data['id'] = prompt_id

        # Clean up name and content
        prompt_data['name'] = prompt_data['name'].strip()
        prompt_data['content'] = prompt_data['content'].strip()

        if not prompt_data['name']:
            logger.warning("Add prompt: Prompt name cannot be empty. Setting default 'Unnamed Prompt'.")
            prompt_data['name'] = "Unnamed Prompt"

        prompts_list = self.get_user_prompts() # Get a copy
        prompts_list.append(prompt_data)

        logger.info(f"Adding new prompt: '{prompt_data['name']}' (ID: {prompt_id})")
        self.set_setting('user_prompts', prompts_list) # Use set_setting to trigger validation/signal

        return True

    def update_prompt(self, prompt_id: str, updated_data: Dict[str, Any]) -> bool:
        if not isinstance(updated_data, dict):
            logger.error(f"Update prompt failed for ID '{prompt_id}': Invalid updated_data.")

            return False

        prompts_list = self.get_user_prompts() # Get a copy
        updated = False
        found_index = -1

        for i, prompt in enumerate(prompts_list):
            if isinstance(prompt, dict) and prompt.get('id') == prompt_id:
                found_index = i
                # Get new name and content, falling back to existing if not provided
                new_name = str(updated_data.get('name', prompt.get('name', ''))).strip()
                new_content = str(updated_data.get('content', prompt.get('content', ''))).strip()

                if not new_name:
                    logger.warning(f"Update prompt {prompt_id}: Name cannot be empty. Keeping old name '{prompt.get('name')}'.")
                    new_name = prompt.get('name') # Keep the old name if new is empty

                # Check if content or name actually changed
                if prompts_list[i].get('name') != new_name or prompts_list[i].get('content') != new_content:
                    prompts_list[i]['name'] = new_name
                    prompts_list[i]['content'] = new_content
                    logger.info(f"Updated prompt '{new_name}' (ID: {prompt_id})")
                    updated = True

                else:
                    logger.debug(f"Update prompt skipped for ID '{prompt_id}', no changes detected.")
                    # Even if no change, if the ID was found, consider it a success
                    return True

                break # Stop after finding and potentially updating

        if updated:
            self.set_setting('user_prompts', prompts_list) # Use set_setting to trigger validation/signal

            return True

        elif found_index != -1:
            # Found the prompt but no changes were made
            return True

        else:
            logger.warning(f"Update prompt failed: ID '{prompt_id}' not found.")

            return False

    def delete_prompt(self, prompt_id: str) -> bool:
        prompts_list = self.get_user_prompts() # Get a copy
        original_length = len(prompts_list)
        prompt_name_deleted = "Unknown"
        updated_list = []
        found = False

        for p in prompts_list:
            if isinstance(p, dict) and p.get('id') == prompt_id:
                prompt_name_deleted = p.get('name', 'Unknown')
                found = True
                # Do not append this prompt to updated_list

            else:
                updated_list.append(p)

        if found:
            logger.info(f"Deleting prompt '{prompt_name_deleted}' (ID: {prompt_id})")
            self.set_setting('user_prompts', updated_list) # Use set_setting to trigger validation/signal

            # Also remove from selected_prompt_ids if it was selected
            selected_ids = self.get_setting('selected_prompt_ids', [])
            if prompt_id in selected_ids:
                 logger.debug(f"Removing deleted prompt {prompt_id} from selected_prompt_ids.")
                 new_selected_ids = [pid for pid in selected_ids if pid != prompt_id]
                 self.set_setting('selected_prompt_ids', new_selected_ids) # This will emit settings_changed & llm_config_changed

            return True

        else:
            logger.warning(f"Delete prompt failed: ID '{prompt_id}' not found.")

            return False

    def get_local_rag_sources(self) -> List[Dict[str, Any]]:
        sources = self._settings.get('rag_local_sources', [])

        if not isinstance(sources, list):
            logger.error("Internal state error: 'rag_local_sources' is not a list. Returning empty.")

            return []

        # Return a copy to prevent external modification
        return [s.copy() for s in sources if isinstance(s, dict)]

    @pyqtSlot(str)
    def add_local_rag_source(self, path_str: str):
        try:
            # Resolve path to absolute path for consistent storage
            path_str_resolved = str(Path(path_str).resolve())

        except Exception as e:
            logger.error(f"Invalid path provided to add_local_rag_source: {path_str}, Error: {e}")

            return

        current_sources = self.get_local_rag_sources() # Get a copy

        # Check if the resolved path already exists in the list
        if not any(s.get('path') == path_str_resolved for s in current_sources):
            logger.info(f"SS: Adding local RAG: {path_str_resolved}")
            current_sources.append({'path': path_str_resolved, 'enabled': True})
            self.set_setting('rag_local_sources', current_sources) # Use set_setting

        else:
            logger.debug(f"SS: Local RAG source already exists: {path_str_resolved}")

    @pyqtSlot(str)
    def remove_local_rag_source(self, path_str: str):
        try:
            # Resolve path to absolute path for consistent comparison
            path_str_resolved = str(Path(path_str).resolve())

        except Exception as e:
            logger.error(f"Invalid path provided to remove_local_rag_source: {path_str}, Error: {e}")

            return

        current_sources = self.get_local_rag_sources() # Get a copy
        original_length = len(current_sources)
        # Filter out the source with the matching resolved path
        updated_sources = [s for s in current_sources if s.get('path') != path_str_resolved]

        if len(updated_sources) < original_length:
            logger.info(f"SS: Removing local RAG: {path_str_resolved}")
            self.set_setting('rag_local_sources', updated_sources) # Use set_setting

        else:
            logger.warning(f"SS: Could not find local RAG to remove: {path_str_resolved}")

    @pyqtSlot(str, bool)
    def set_local_rag_source_enabled(self, path_str: str, enabled: bool):
        try:
            # Resolve path to absolute path for consistent comparison
            path_str_resolved = str(Path(path_str).resolve())

        except Exception as e:
            logger.error(f"Invalid path provided to set_local_rag_source_enabled: {path_str}, Error: {e}")

            return

        current_sources = self.get_local_rag_sources() # Get a copy
        updated = False

        for source in current_sources:
            if source.get('path') == path_str_resolved:
                # Check if the enabled state is actually changing
                if source.get('enabled') != enabled:
                    source['enabled'] = enabled
                    logger.info(f"SS: Set local RAG '{path_str_resolved}' enabled={enabled}")
                    updated = True

                break # Found the source, no need to continue loop

        if updated:
            self.set_setting('rag_local_sources', current_sources) # Use set_setting
# --- END OF FILE pm/core/settings_service.py ---