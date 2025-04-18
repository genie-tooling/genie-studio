# pm/core/settings_service.py
import json
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QApplication
from loguru import logger
from typing import Any, Dict, List, Optional

from .project_config import DEFAULT_CONFIG, AVAILABLE_PYGMENTS_STYLES, DEFAULT_STYLE, AVAILABLE_RAG_MODELS

class SettingsService(QObject):
    """
    Manages loading, saving, accessing, and validating application settings.
    Acts as the single source of truth for configuration (merging defaults + project).
    """
    # Signals remain the same...
    settings_loaded = Signal()
    settings_saved = Signal()
    settings_changed = Signal(str, Any)
    theme_changed = Signal(str)
    font_changed = Signal(str, int)
    syntax_style_changed = Signal(str)
    llm_config_changed = Signal()
    rag_config_changed = Signal() # Emitted for ANY rag change (global default or project enable)
    local_rag_sources_changed = Signal(list) # Specific signal for UI list update
    project_path_changed = Signal(Path)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Holds the *effective* settings (Defaults merged with Project .patchmind.json)
        self._settings: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self._project_path: Optional[Path] = None
        logger.info("SettingsService initialized.")

    # --- Core Load/Save ---

    def load_project(self, project_path: Path) -> bool:
        """Loads project settings, merging with defaults and validating."""
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
                config_valid = False; loaded_config = {}
            except Exception as e:
                logger.error(f"SettingsService: Failed to read config file {cfg_path}: {e}. Using defaults.")
                config_valid = False; loaded_config = {}
        else:
            logger.info(f"SettingsService: No project config found at {cfg_path}. Using defaults.")

        # --- Merge and Validate ---
        temp_config = DEFAULT_CONFIG.copy()
        temp_config.update(loaded_config) # Project settings override defaults

        validated_config, corrections_made = self._validate_config(temp_config)
        self._settings = validated_config # Store the final, validated, merged settings
        self._settings['last_project_path'] = str(self._project_path)

        self.settings_loaded.emit()
        logger.info("SettingsService: Project settings loaded and validated.")

        # --- User Notification ---
        if not config_valid:
             QMessageBox.warning(QApplication.activeWindow(), "Configuration Error",
                                 f"The project config '.patchmind.json' is invalid.\nDefault settings loaded. Invalid file will be overwritten on save.")
        elif config_exists and corrections_made:
             logger.warning("SettingsService: Project configuration updated to match current defaults/structure.")

        return True

    def save_settings(self) -> bool:
        """Saves the current IN-MEMORY settings to the project's config file.
           This is called by SettingsDialog accept and potentially MainWindow close."""
        if not self._project_path or not self._project_path.is_dir():
            logger.error("SettingsService: Cannot save settings, project path not set or invalid.")
            return False

        cfg_path = self._project_path / ".patchmind.json"
        logger.info(f"SettingsService: Saving effective settings to {cfg_path}...")

        try:
            # Use the current _settings which reflect the merged+validated state
            cfg_to_save = self._settings.copy()

            # Filter out any keys NOT present in the original DEFAULT_CONFIG
            # This prevents saving potentially stale keys if defaults change later
            final_cfg_to_save = {k: cfg_to_save[k] for k in DEFAULT_CONFIG.keys() if k in cfg_to_save}

            # Always update last path
            final_cfg_to_save['last_project_path'] = str(self._project_path)

            # Ensure valid syntax style just before saving
            if final_cfg_to_save.get('syntax_highlighting_style') not in AVAILABLE_PYGMENTS_STYLES:
                 logger.warning(f"Saving invalid style '{final_cfg_to_save.get('syntax_highlighting_style')}', using default.")
                 final_cfg_to_save['syntax_highlighting_style'] = DEFAULT_STYLE

            with open(cfg_path, "w", encoding='utf-8') as f:
                json.dump(final_cfg_to_save, f, indent=2, ensure_ascii=False)

            logger.info(f"SettingsService: Settings saved successfully to project file.")
            self.settings_saved.emit()
            return True
        except Exception as e:
            logger.exception(f"SettingsService: Failed to save config to {cfg_path}: {e}")
            QMessageBox.critical(QApplication.activeWindow(), "Save Error",
                                 f"Failed to save settings to:\n{cfg_path}\n\nError: {e}")
            return False

    def _validate_config(self, config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        """Validates config dict against DEFAULT_CONFIG, ensures types, applies defaults."""
        validated = {}
        corrections_made = False
        # Process only keys present in DEFAULT_CONFIG
        for key, default_value in DEFAULT_CONFIG.items():
            current_value = config.get(key)
            expected_type = type(default_value)
            corrected = False

            if current_value is None:
                validated[key] = default_value
                corrected = True; logger.warning(f"Validate: Added missing key '{key}'")
            elif not isinstance(current_value, expected_type):
                # Type coercion logic (remains the same as previous version)
                original_type = type(current_value)
                try:
                    if expected_type is int and isinstance(current_value, (float, str)): validated[key] = int(current_value)
                    elif expected_type is float and isinstance(current_value, (int, str)): validated[key] = float(current_value)
                    elif expected_type is bool and isinstance(current_value, str):
                        if current_value.lower() == 'true': validated[key] = True
                        elif current_value.lower() == 'false': validated[key] = False
                        else: raise ValueError("Invalid boolean string")
                    elif expected_type is list and not isinstance(current_value, list): raise ValueError("Expected list")
                    elif expected_type is dict and not isinstance(current_value, dict): raise ValueError("Expected dict")
                    elif expected_type is str and not isinstance(current_value, str): validated[key] = str(current_value)
                    else: raise TypeError("Incompatible type")
                    logger.warning(f"Validate: Corrected type for '{key}'. Expected {expected_type}, got {original_type}.")
                    corrected = True
                except (ValueError, TypeError, Exception) as e:
                     logger.warning(f"Validate: Failed for '{key}' (Expected {expected_type}, Got {original_type}). Using default. Error: {e}")
                     validated[key] = default_value; corrected = True
            else: # Type matches
                validated[key] = current_value

            # Specific value validations (after type correction)
            if key == 'syntax_highlighting_style' and validated[key] not in AVAILABLE_PYGMENTS_STYLES:
                 logger.warning(f"Validate: Invalid style '{validated[key]}'. Using default '{DEFAULT_STYLE}'.")
                 validated[key] = DEFAULT_STYLE; corrected = True
            elif key == 'main_prompt_template' and not str(validated[key]).strip():
                 logger.warning("Validate: Empty main prompt template. Restoring default."); validated[key] = DEFAULT_CONFIG['main_prompt_template']; corrected = True
            # --- Validate Global RAG Settings ---
            elif key == 'rag_ranking_model_name' and validated[key] not in AVAILABLE_RAG_MODELS:
                 logger.warning(f"Validate: Invalid RAG model '{validated[key]}'. Using default '{AVAILABLE_RAG_MODELS[0]}'.")
                 validated[key] = AVAILABLE_RAG_MODELS[0]; corrected = True
            elif key == 'rag_similarity_threshold':
                 val = validated[key]
                 if not (0.0 <= val <= 1.0):
                     logger.warning(f"Validate: Invalid RAG threshold '{val}'. Clamping to [0,1].")
                     validated[key] = max(0.0, min(1.0, val)); corrected = True
            # --- End Global RAG Validation ---
            elif key == 'rag_local_sources': # Validate structure of the list
                sources = validated[key]; valid_sources = []; list_changed = False
                for item in sources:
                    if isinstance(item, dict) and 'path' in item and isinstance(item['path'], str): valid_sources.append({'path':item['path'],'enabled':bool(item.get('enabled',True))})
                    elif isinstance(item, str): valid_sources.append({'path':item,'enabled':True}); list_changed=True
                    else: logger.warning(f"Validate: Removing invalid local RAG source: {item}"); list_changed=True
                validated[key] = valid_sources;
                if list_changed: corrected = True

            if corrected: corrections_made = True

        # Log ignored keys
        ignored_keys = set(config.keys()) - set(DEFAULT_CONFIG.keys())
        if ignored_keys:
            logger.warning(f"Validate: Ignored unknown keys from config file: {ignored_keys}")
            corrections_made = True

        return validated, corrections_made

    # --- Getters ---
    def get_setting(self, key: str, default: Optional[Any] = None) -> Any:
        # Return from the merged settings, providing a default if necessary
        return self._settings.get(key, default if default is not None else DEFAULT_CONFIG.get(key))

    def get_all_settings(self) -> Dict[str, Any]:
        return self._settings.copy() # Return copy of the effective settings

    def get_project_path(self) -> Optional[Path]:
        return self._project_path

    # --- Setters ---
    @Slot(str, Any)
    def set_setting(self, key: str, value: Any):
        """Updates a setting in the current IN-MEMORY configuration."""
        if key not in DEFAULT_CONFIG: # Only allow known keys
            logger.warning(f"SettingsService: Set rejected for unknown key '{key}'.")
            return

        expected_type = type(DEFAULT_CONFIG[key])
        can_assign = False
        original_value = value # Keep original for logging
        if isinstance(value, expected_type): can_assign = True
        elif expected_type is float and isinstance(value, int): value = float(value); can_assign = True # Allow int->float
        # Add other coercions if needed (e.g., str -> int/bool) but be careful

        if not can_assign:
             logger.warning(f"SettingsService: Set rejected for '{key}'. Expected {expected_type}, got {type(original_value)}.")
             return

        # Perform specific value validation before assignment
        if key == 'syntax_highlighting_style' and value not in AVAILABLE_PYGMENTS_STYLES:
             logger.warning(f"Set rejected for style '{value}', not available. Keeping old.")
             return
        if key == 'rag_ranking_model_name' and value not in AVAILABLE_RAG_MODELS:
             logger.warning(f"Set rejected for RAG model '{value}', not available. Keeping old.")
             return
        if key == 'rag_similarity_threshold' and not (0.0 <= float(value) <= 1.0):
             logger.warning(f"Set rejected for RAG threshold '{value}', out of range [0,1]. Keeping old.")
             return


        old_value = self._settings.get(key)
        if old_value != value:
            logger.debug(f"SettingsService: Setting '{key}' changed from '{old_value}' to '{value}' (in memory)")
            self._settings[key] = value
            self.settings_changed.emit(key, value)
            self._emit_specific_signals(key, value)
            # NOTE: This does NOT automatically save to file. Saving happens explicitly
            # via save_settings() (usually called by dialog accept or main window close).

    def _emit_specific_signals(self, key: str, value: Any):
        """Emits detailed signals based on the changed key."""
        if key == 'theme': self.theme_changed.emit(value)
        elif key == 'editor_font': self.font_changed.emit(value, self.get_setting('editor_font_size'))
        elif key == 'editor_font_size': self.font_changed.emit(self.get_setting('editor_font'), value)
        elif key == 'syntax_highlighting_style': self.syntax_style_changed.emit(value)
        elif key in ['provider', 'model', 'api_key', 'temperature', 'top_k', 'context_limit']: self.llm_config_changed.emit()
        # Emit rag_config_changed for *any* RAG-related setting change
        elif key.startswith('rag_'): self.rag_config_changed.emit()
        # Specific signal for local sources list itself
        if key == 'rag_local_sources': self.local_rag_sources_changed.emit(self.get_local_rag_sources())


    # --- Local RAG Source Management (remains the same logic) ---
    def get_local_rag_sources(self) -> List[Dict[str, Any]]:
        return [s.copy() for s in self._settings.get('rag_local_sources', [])]
    @Slot(str)
    def add_local_rag_source(self, path_str: str):
        # ... (implementation unchanged) ...
        path_str = str(Path(path_str).resolve()); current_sources = self._settings.get('rag_local_sources', []);
        if not any(s['path'] == path_str for s in current_sources): logger.info(f"SS: Adding local RAG: {path_str}"); current_sources.append({'path': path_str, 'enabled': True}); self._settings['rag_local_sources'] = current_sources; self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources()); self.local_rag_sources_changed.emit(self.get_local_rag_sources()); self.rag_config_changed.emit()
        else: logger.debug(f"SS: Local RAG source already exists: {path_str}")
    @Slot(str)
    def remove_local_rag_source(self, path_str: str):
        # ... (implementation unchanged) ...
        path_str = str(Path(path_str).resolve()); current_sources = self._settings.get('rag_local_sources', []); original_length = len(current_sources); updated_sources = [s for s in current_sources if s.get('path') != path_str];
        if len(updated_sources) < original_length: logger.info(f"SS: Removing local RAG: {path_str}"); self._settings['rag_local_sources'] = updated_sources; self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources()); self.local_rag_sources_changed.emit(self.get_local_rag_sources()); self.rag_config_changed.emit()
        else: logger.warning(f"SS: Could not find local RAG to remove: {path_str}")
    @Slot(str, bool)
    def set_local_rag_source_enabled(self, path_str: str, enabled: bool):
        # ... (implementation unchanged) ...
        path_str = str(Path(path_str).resolve()); current_sources = self._settings.get('rag_local_sources', []); updated = False;
        for source in current_sources:
            if source.get('path') == path_str:
                if source.get('enabled') != enabled: source['enabled'] = enabled; logger.info(f"SS: Set local RAG '{path_str}' enabled={enabled}"); updated = True; break
        if updated: self._settings['rag_local_sources'] = current_sources; self.settings_changed.emit('rag_local_sources', self.get_local_rag_sources()); self.local_rag_sources_changed.emit(self.get_local_rag_sources()); self.rag_config_changed.emit()
        else: logger.warning(f"SS: Could not find local RAG to set enabled: {path_str}")

