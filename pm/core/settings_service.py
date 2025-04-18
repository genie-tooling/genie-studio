# pm/core/settings_service.py
import json
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
# --- Add QtWidgets for QMessageBox ---
from PySide6.QtWidgets import QMessageBox, QApplication
from loguru import logger
from typing import Any, Dict, List, Optional

from .project_config import DEFAULT_CONFIG, AVAILABLE_PYGMENTS_STYLES, DEFAULT_STYLE, AVAILABLE_RAG_MODELS

class SettingsService(QObject):
    """
    Manages loading, saving, accessing, and validating application settings.
    Acts as the single source of truth for configuration.
    """
    # Signals remain the same...
    settings_loaded = Signal()
    settings_saved = Signal()
    settings_changed = Signal(str, Any)
    theme_changed = Signal(str)
    font_changed = Signal(str, int)
    syntax_style_changed = Signal(str)
    llm_config_changed = Signal()
    rag_config_changed = Signal()
    local_rag_sources_changed = Signal(list)
    project_path_changed = Signal(Path)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._settings: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self._project_path: Optional[Path] = None
        logger.info("SettingsService initialized.")

    # --- Core Load/Save ---

    def load_project(self, project_path: Path) -> bool:
        """Loads settings for a specific project path."""
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
        config_valid = True # Assume valid initially

        if config_exists:
            try:
                with open(cfg_path, "r", encoding='utf-8') as f:
                    loaded_config = json.load(f)
                logger.info(f"SettingsService: Loaded project config from {cfg_path}")
            except json.JSONDecodeError as e:
                logger.error(f"SettingsService: Invalid JSON in config file {cfg_path}: {e}. Using defaults.")
                config_valid = False
                loaded_config = {} # Ensure it's an empty dict on error
            except Exception as e:
                logger.error(f"SettingsService: Failed to read config file {cfg_path}: {e}. Using defaults.")
                config_valid = False
                loaded_config = {}
        else:
            logger.info(f"SettingsService: No project config found at {cfg_path}. Using defaults.")

        # --- Merge and Validate ---
        # Start with defaults, overlay loaded (if any), then validate
        temp_config = DEFAULT_CONFIG.copy()
        temp_config.update(loaded_config) # Overwrite defaults with loaded values

        # Validate the merged config
        validated_config, corrections_made = self._validate_config(temp_config)
        self._settings = validated_config
        self._settings['last_project_path'] = str(self._project_path) # Ensure correct path

        self.settings_loaded.emit() # Signal completion
        logger.info("SettingsService: Project settings loaded and validated.")

        # --- User Notification ---
        if not config_valid:
             QMessageBox.warning(QApplication.activeWindow(), "Configuration Error",
                                 f"The configuration file '.patchmind.json' in this project is invalid or corrupted.\n\nDefault settings have been loaded. The invalid file will be overwritten on save.")
        elif config_exists and corrections_made:
             logger.warning("SettingsService: Project configuration was updated to match current defaults.")
             # Optional: Inform user their config was updated
             # QMessageBox.information(QApplication.activeWindow(), "Configuration Updated",
             #                         "Project settings were updated to conform to the current application version.\nPlease review your settings if needed.")

        return True

    def save_settings(self) -> bool:
        """Saves the current settings to the project's config file."""
        if not self._project_path or not self._project_path.is_dir():
            logger.error("SettingsService: Cannot save settings, project path not set or invalid.")
            return False

        cfg_path = self._project_path / ".patchmind.json"
        logger.info(f"SettingsService: Saving settings to {cfg_path}...")

        try:
            # Create the config to save based ONLY on DEFAULT_CONFIG keys
            # This prevents saving old, unused keys.
            cfg_to_save = {}
            for key in DEFAULT_CONFIG.keys():
                cfg_to_save[key] = self._settings.get(key, DEFAULT_CONFIG[key]) # Use current or default

            # Always update last path
            cfg_to_save['last_project_path'] = str(self._project_path)

            # Ensure valid syntax style before saving
            if cfg_to_save.get('syntax_highlighting_style') not in AVAILABLE_PYGMENTS_STYLES:
                 logger.warning(f"Saving invalid style '{cfg_to_save.get('syntax_highlighting_style')}', using default.")
                 cfg_to_save['syntax_highlighting_style'] = DEFAULT_STYLE

            with open(cfg_path, "w", encoding='utf-8') as f:
                json.dump(cfg_to_save, f, indent=2, ensure_ascii=False)

            logger.info(f"SettingsService: Settings saved successfully.")
            self.settings_saved.emit()
            return True
        except Exception as e:
            logger.exception(f"SettingsService: Failed to save config to {cfg_path}: {e}")
            # Show error to user
            QMessageBox.critical(QApplication.activeWindow(), "Save Error",
                                 f"Failed to save settings to:\n{cfg_path}\n\nError: {e}")
            return False

    # --- Modified _validate_config ---
    def _validate_config(self, config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        """Validates a config dictionary, ensuring types and defaults.
           Returns the validated dictionary and a boolean indicating if corrections were made."""
        validated = {}
        corrections_made = False
        # Only process keys that exist in DEFAULT_CONFIG
        for key, default_value in DEFAULT_CONFIG.items():
            current_value = config.get(key) # Get value from the potentially loaded/merged config
            expected_type = type(default_value)
            corrected = False

            if current_value is None:
                validated[key] = default_value
                corrected = True
                logger.warning(f"SettingsService: Validation added missing key '{key}' with default.")
            elif not isinstance(current_value, expected_type):
                # Attempt type coercion for common cases
                original_type = type(current_value)
                try:
                    if expected_type is int and isinstance(current_value, (float, str)):
                         validated[key] = int(current_value)
                    elif expected_type is float and isinstance(current_value, (int, str)):
                         validated[key] = float(current_value)
                    elif expected_type is bool and isinstance(current_value, str):
                        if current_value.lower() == 'true': validated[key] = True
                        elif current_value.lower() == 'false': validated[key] = False
                        else: raise ValueError("Invalid boolean string")
                    elif expected_type is list and not isinstance(current_value, list):
                         raise ValueError("Expected list")
                    elif expected_type is dict and not isinstance(current_value, dict):
                         raise ValueError("Expected dict")
                    elif expected_type is str and not isinstance(current_value, str):
                         validated[key] = str(current_value) # Force to string if needed
                    else:
                         # Cannot coerce, use default
                         raise TypeError("Incompatible type")

                    # If coercion worked, log correction
                    logger.warning(f"SettingsService: Validation corrected type for '{key}'. Expected {expected_type}, got {original_type}. Coerced successfully.")
                    corrected = True

                except (ValueError, TypeError, Exception) as e:
                     # Coercion failed or other error, use default
                     logger.warning(f"SettingsService: Validation failed for '{key}' (Expected {expected_type}, Got {original_type}). Using default value. Error: {e}")
                     validated[key] = default_value
                     corrected = True
            else:
                # Type matches, assign directly
                validated[key] = current_value


            # Specific value validations (after type correction)
            if key == 'syntax_highlighting_style' and validated[key] not in AVAILABLE_PYGMENTS_STYLES:
                 logger.warning(f"SettingsService: Validation found invalid style '{validated[key]}'. Using default '{DEFAULT_STYLE}'.")
                 validated[key] = DEFAULT_STYLE; corrected = True
            elif key == 'main_prompt_template' and not str(validated[key]).strip():
                 logger.warning("SettingsService: Validation found empty main prompt template. Restoring default.")
                 validated[key] = DEFAULT_CONFIG['main_prompt_template']; corrected = True
            elif key == 'rag_ranking_model_name' and validated[key] not in AVAILABLE_RAG_MODELS:
                 logger.warning(f"SettingsService: Validation found invalid RAG model '{validated[key]}'. Using default.")
                 validated[key] = AVAILABLE_RAG_MODELS[0]; corrected = True
            elif key == 'rag_local_sources':
                sources = validated[key] # Already known to be a list if type check passed
                valid_sources = []
                list_changed = False
                for item in sources:
                    if isinstance(item, dict) and 'path' in item and isinstance(item['path'], str):
                        valid_sources.append({ 'path': item['path'], 'enabled': bool(item.get('enabled', True)) })
                    elif isinstance(item, str): # Allow simple list of paths initially
                        valid_sources.append({'path': item, 'enabled': True}); list_changed = True
                    else:
                         logger.warning(f"SettingsService: Validation removing invalid local RAG source item: {item}"); list_changed = True
                validated[key] = valid_sources
                if list_changed: corrected = True

            if corrected:
                 corrections_made = True

        # Log if any keys from loaded config were ignored
        ignored_keys = set(config.keys()) - set(DEFAULT_CONFIG.keys())
        if ignored_keys:
            logger.warning(f"SettingsService: Ignored unknown keys found in configuration file: {ignored_keys}")
            corrections_made = True # Ignoring keys counts as a correction

        return validated, corrections_made


    # --- Getters (remain the same) ---
    def get_setting(self, key: str, default: Optional[Any] = None) -> Any:
        return self._settings.get(key, default if default is not None else DEFAULT_CONFIG.get(key))

    def get_all_settings(self) -> Dict[str, Any]:
        return self._settings.copy()

    def get_project_path(self) -> Optional[Path]:
        return self._project_path

    # --- Setters (remain the same) ---
    @Slot(str, Any)
    def set_setting(self, key: str, value: Any):
        if key in DEFAULT_CONFIG:
             expected_type = type(DEFAULT_CONFIG[key])
             can_assign = False
             if isinstance(value, expected_type): can_assign = True
             elif expected_type is float and isinstance(value, int): value = float(value); can_assign = True
             if not can_assign:
                  logger.warning(f"SettingsService: Set rejected for '{key}'. Expected {expected_type}, got {type(value)}.")
                  return
        else: logger.warning(f"SettingsService: Setting unknown key '{key}'.")

        old_value = self._settings.get(key)
        if old_value != value:
            logger.debug(f"SettingsService: Setting '{key}' changed from '{old_value}' to '{value}'")
            self._settings[key] = value
            self.settings_changed.emit(key, value)
            self._emit_specific_signals(key, value)

    def _emit_specific_signals(self, key: str, value: Any):
        if key == 'theme': self.theme_changed.emit(value)
        elif key == 'editor_font': self.font_changed.emit(value, self.get_setting('editor_font_size'))
        elif key == 'editor_font_size': self.font_changed.emit(self.get_setting('editor_font'), value)
        elif key == 'syntax_highlighting_style': self.syntax_style_changed.emit(value)
        elif key in ['provider', 'model', 'api_key', 'temperature', 'top_k', 'context_limit']: self.llm_config_changed.emit()
        elif key.startswith('rag_'): self.rag_config_changed.emit()

    # --- Local RAG Source Management (remain the same) ---
    def get_local_rag_sources(self) -> List[Dict[str, Any]]:
        return [s.copy() for s in self._settings.get('rag_local_sources', [])]

    @Slot(str)
    def add_local_rag_source(self, path_str: str):
        path_str = str(Path(path_str).resolve())
        current_sources = self._settings.get('rag_local_sources', [])
        if not any(s['path'] == path_str for s in current_sources):
            logger.info(f"SettingsService: Adding local RAG source: {path_str}")
            current_sources.append({'path': path_str, 'enabled': True})
            self._settings['rag_local_sources'] = current_sources
            self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources())
            self.local_rag_sources_changed.emit(self.get_local_rag_sources())
            self.rag_config_changed.emit()
        else: logger.debug(f"SettingsService: Local RAG source already exists: {path_str}")

    @Slot(str)
    def remove_local_rag_source(self, path_str: str):
        path_str = str(Path(path_str).resolve())
        current_sources = self._settings.get('rag_local_sources', [])
        original_length = len(current_sources)
        updated_sources = [s for s in current_sources if s.get('path') != path_str]
        if len(updated_sources) < original_length:
            logger.info(f"SettingsService: Removing local RAG source: {path_str}")
            self._settings['rag_local_sources'] = updated_sources
            self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources())
            self.local_rag_sources_changed.emit(self.get_local_rag_sources())
            self.rag_config_changed.emit()
        else: logger.warning(f"SettingsService: Could not find local RAG source to remove: {path_str}")

    @Slot(str, bool)
    def set_local_rag_source_enabled(self, path_str: str, enabled: bool):
        path_str = str(Path(path_str).resolve())
        current_sources = self._settings.get('rag_local_sources', [])
        updated = False
        for source in current_sources:
            if source.get('path') == path_str:
                if source.get('enabled') != enabled:
                    source['enabled'] = enabled
                    logger.info(f"SettingsService: Set local RAG source '{path_str}' enabled state to {enabled}")
                    updated = True
                break
        if updated:
            self._settings['rag_local_sources'] = current_sources
            self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources())
            self.local_rag_sources_changed.emit(self.get_local_rag_sources())
            self.rag_config_changed.emit()
        else: logger.warning(f"SettingsService: Could not find local RAG source to set enabled state: {path_str}")

