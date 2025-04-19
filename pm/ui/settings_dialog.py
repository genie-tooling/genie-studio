# --- START OF FILE pm/ui/settings_dialog.py ---
# pm/ui/settings_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
    QDialogButtonBox, QPushButton, QHBoxLayout, QLabel, QVBoxLayout,
    QCheckBox, QFontComboBox, QTabWidget, QWidget, QGroupBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QFont
from pathlib import Path
from loguru import logger
import qtawesome as qta
from typing import List, Dict, Optional, Any
import re
import json

# --- Local Imports ---
from ..core.settings_service import SettingsService
from ..core.project_config import (AVAILABLE_RAG_MODELS, DEFAULT_CONFIG,
                                   DEFAULT_RAG_INCLUDE_PATTERNS, DEFAULT_RAG_EXCLUDE_PATTERNS) # Import RAG defaults
from ..core.constants import AVAILABLE_SCINTILLA_THEMES
class SettingsDialog(QDialog):
    """
    Manages global application settings: API Keys, Appearance, Global RAG Defaults, Features.
    Does NOT manage project-specific RAG source enablement (handled by ConfigDock).
    """
    # No longer need these signals emitted from the dialog itself
    # request_llm_refresh = pyqtSignal(str, str)
    # request_summarizer_refresh = pyqtSignal(str, str)

    def __init__(self,
                 settings_service: SettingsService,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Global Application Settings')
        self.setMinimumSize(650, 550) # Increased height slightly

        self._settings_service = settings_service

        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self._create_widgets()

        self.tab_widget.addTab(self._create_api_keys_tab(), "API Keys")
        self.tab_widget.addTab(self._create_rag_defaults_tab(), "RAG Defaults")
        self.tab_widget.addTab(self._create_features_tab(), "Features")
        self.tab_widget.addTab(self._create_appearance_tab(), "Appearance")
        # Prompts tab handled differently now, using PromptEditorDialog
        # self.tab_widget.addTab(self._create_prompts_tab(), "User Prompts")

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        self._connect_internal_pyqtSignals()
        self._populate_all_fields()

        # No longer need to refresh models from this dialog
        # QTimer.singleShot(50, self._emit_llm_refresh_request)
        # QTimer.singleShot(50, self._emit_summarizer_refresh_request)

        logger.debug("SettingsDialog initialized.")

    def _create_widgets(self):
        """Creates the input widgets relevant to this dialog."""
        logger.debug("SettingsDialog: Creating widgets...")
        # API Keys
        self.llm_api_key_input = QLineEdit(); self.llm_api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.llm_api_key_label = QLabel('Gemini API Key:')
        self.bing_api_key_input = QLineEdit(); self.bing_api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.bing_api_key_label = QLabel('Bing Search API Key:')
        self.google_api_key_input = QLineEdit(); self.google_api_key_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.google_api_key_label = QLabel('Google Search API Key:')
        self.google_cse_id_input = QLineEdit()
        self.google_cse_id_label = QLabel('Google CSE ID:')

        # RAG Defaults
        self.rag_rank_model_select = QComboBox(); self.rag_rank_model_select.addItems(AVAILABLE_RAG_MODELS)
        self.rag_rank_threshold_spin = QDoubleSpinBox(); self.rag_rank_threshold_spin.setRange(0.0, 1.0); self.rag_rank_threshold_spin.setSingleStep(0.05); self.rag_rank_threshold_spin.setDecimals(2)
        self.rag_rank_threshold_spin.setToolTip("Default similarity threshold for ranking RAG results (0.0-1.0)")
        # --- NEW RAG DIR WIDGETS ---
        self.rag_dir_depth_spin = QSpinBox(); self.rag_dir_depth_spin.setRange(0, 10); self.rag_dir_depth_spin.setToolTip("Max directory depth to crawl for RAG (0=current only)")
        self.rag_include_edit = QLineEdit(); self.rag_include_edit.setPlaceholderText("e.g., *.py, *.js") ; self.rag_include_edit.setToolTip("Comma-separated include glob patterns (filename/relative path)")
        self.rag_exclude_edit = QLineEdit(); self.rag_exclude_edit.setPlaceholderText("e.g., *.log, node_modules/*") ; self.rag_exclude_edit.setToolTip("Comma-separated exclude glob patterns (filename/relative path)")
        # --- END NEW RAG DIR WIDGETS ---

        # Features
        self.feature_patch_cb = QCheckBox("Enable Patch Mode (Apply diffs)")
        self.feature_whole_diff_cb = QCheckBox("Generate Whole-file Diffs (if patch disabled)"); self.feature_whole_diff_cb.setToolTip("If Patch Mode is disabled, generate diffs covering the whole file instead of just the changed block.")
        self.feature_disable_critic_cb = QCheckBox("Disable Critic Workflow (Direct Execution)"); self.feature_disable_critic_cb.setToolTip("Bypass Plan/Critic steps, go directly to Executor model.")

        # Appearance
        self.appearance_font_combo = QFontComboBox()
        self.appearance_font_size_spin = QSpinBox()
        self.appearance_theme_combo = QComboBox(); self.appearance_theme_combo.addItems(["Dark", "Light"])
        # --- RENAMED/NEW: Editor Theme Combo ---
        self.appearance_editor_theme_combo = QComboBox()
        # Populate with themes from constants
        if AVAILABLE_SCINTILLA_THEMES:
             self.appearance_editor_theme_combo.addItems(AVAILABLE_SCINTILLA_THEMES)
        else:
             self.appearance_editor_theme_combo.addItem("No themes available")
             self.appearance_editor_theme_combo.setEnabled(False)
             logger.warning("SettingsDialog: AVAILABLE_SCINTILLA_THEMES list is empty.")
        # --- REMOVED: Old syntax_style_combo ---
        # self.appearance_style_combo = QComboBox()

        logger.debug("SettingsDialog: Widgets created.")

    def _create_api_keys_tab(self) -> QWidget:
        tab = QWidget(); layout = QFormLayout(tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addRow(self.llm_api_key_label, self.llm_api_key_input)
        layout.addRow(self.bing_api_key_label, self.bing_api_key_input)
        layout.addRow(self.google_api_key_label, self.google_api_key_input)
        layout.addRow(self.google_cse_id_label, self.google_cse_id_input)
        layout.addRow(QLabel("<i>Note: LLM provider/model selection is in the main Config dock.</i>"))
        return tab

    def _create_rag_defaults_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Configure global RAG settings."))
        layout.addWidget(QLabel("<i>Project-specific source enablement is handled in the main Config dock.</i>"))
        layout.addSpacing(10)

        rank_group = QGroupBox("Ranking & Filtering Defaults")
        rank_layout = QFormLayout(rank_group)
        rank_layout.addRow("Embedding Model:", self.rag_rank_model_select)
        rank_layout.addRow("Similarity Threshold:", self.rag_rank_threshold_spin)
        layout.addWidget(rank_group)

        # --- NEW RAG DIR GROUP ---
        dir_group = QGroupBox("Directory Crawling Defaults")
        dir_layout = QFormLayout(dir_group)
        dir_layout.addRow("Max Crawl Depth:", self.rag_dir_depth_spin)
        dir_layout.addRow("Include Patterns:", self.rag_include_edit)
        dir_layout.addRow("Exclude Patterns:", self.rag_exclude_edit)
        layout.addWidget(dir_group)
        # --- END NEW RAG DIR GROUP ---

        layout.addStretch(1)
        return tab

    def _create_features_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        patch_group = QGroupBox("Patch/Diff Features"); patch_layout = QVBoxLayout(patch_group)
        patch_layout.addWidget(self.feature_patch_cb); patch_layout.addWidget(self.feature_whole_diff_cb)
        layout.addWidget(patch_group)
        workflow_group = QGroupBox("LLM Workflow"); workflow_layout = QVBoxLayout(workflow_group)
        workflow_layout.addWidget(self.feature_disable_critic_cb)
        layout.addWidget(workflow_group)
        layout.addStretch(1)
        return tab

    def _create_appearance_tab(self) -> QWidget:
        tab = QWidget(); layout = QFormLayout(tab)
        self.appearance_font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts); layout.addRow("Editor Font:", self.appearance_font_combo)
        self.appearance_font_size_spin.setRange(8, 32); layout.addRow("Editor Font Size:", self.appearance_font_size_spin)
        layout.addRow("UI Theme:", self.appearance_theme_combo)
        # --- RENAMED/NEW: Editor Theme Row ---
        layout.addRow("Editor Theme:", self.appearance_editor_theme_combo)
        # --- REMOVED: Old syntax_style_combo row ---
        # layout.addRow("Syntax Style:", self.appearance_style_combo)
        return tab

    # Prompts Tab REMOVED

    def _connect_internal_pyqtSignals(self):
        # Connect only pyqtSignals relevant to widgets in *this* dialog
        self.feature_patch_cb.toggled.connect(self.feature_whole_diff_cb.setEnabled)

    def _populate_all_fields(self):
        """Populates all widgets with values from SettingsService."""
        logger.debug("SettingsDialog: Populating fields from SettingsService...")
        s = self._settings_service

        # API Keys
        self.llm_api_key_input.setText(s.get_setting('api_key', ''))
        self.bing_api_key_input.setText(s.get_setting('rag_bing_api_key', ''))
        self.google_api_key_input.setText(s.get_setting('rag_google_api_key', ''))
        self.google_cse_id_input.setText(s.get_setting('rag_google_cse_id', ''))

        # RAG Defaults
        # Ensure AVAILABLE_RAG_MODELS is not empty before setting current text
        default_rag_model = AVAILABLE_RAG_MODELS[0] if AVAILABLE_RAG_MODELS else ""
        self.rag_rank_model_select.setCurrentText(s.get_setting('rag_ranking_model_name', default_rag_model))
        self.rag_rank_threshold_spin.setValue(float(s.get_setting('rag_similarity_threshold', 0.30)))
        # --- POPULATE NEW RAG FIELDS ---
        self.rag_dir_depth_spin.setValue(int(s.get_setting('rag_dir_max_depth', DEFAULT_CONFIG['rag_dir_max_depth'])))
        # Join list items with ", " for display in QLineEdit
        self.rag_include_edit.setText(", ".join(s.get_setting('rag_dir_include_patterns', DEFAULT_RAG_INCLUDE_PATTERNS)))
        self.rag_exclude_edit.setText(", ".join(s.get_setting('rag_dir_exclude_patterns', DEFAULT_RAG_EXCLUDE_PATTERNS)))
        # --- END POPULATE NEW RAG FIELDS ---

        # Features
        self.feature_patch_cb.setChecked(s.get_setting('patch_mode', True))
        self.feature_whole_diff_cb.setChecked(s.get_setting('whole_file', True))
        # Ensure whole_diff_cb is disabled if patch_mode is unchecked initially
        self.feature_whole_diff_cb.setEnabled(self.feature_patch_cb.isChecked())
        self.feature_disable_critic_cb.setChecked(s.get_setting('disable_critic_workflow', False))

        # Appearance
        try: self.appearance_font_combo.setCurrentFont(QFont(s.get_setting('editor_font', 'Fira Code')))
        except Exception as e: logger.warning(f"Failed set font: {e}"); self.appearance_font_combo.setCurrentFont(QFont("Monospace")) # Fallback font
        self.appearance_font_size_spin.setValue(int(s.get_setting('editor_font_size', 11)))
        self.appearance_theme_combo.setCurrentText(s.get_setting('theme', 'Dark'))

        # --- RENAMED/NEW: Editor Theme Combo Population ---
        self.appearance_editor_theme_combo.blockSignals(True) # Block signals during population
        # The items are already added in _create_widgets
        # Set the current value from settings
        current_editor_theme = s.get_setting('editor_theme', DEFAULT_CONFIG.get('editor_theme', AVAILABLE_SCINTILLA_THEMES[0] if AVAILABLE_SCINTILLA_THEMES else "Native Dark"))
        idx = self.appearance_editor_theme_combo.findText(current_editor_theme)
        if idx >= 0:
             self.appearance_editor_theme_combo.setCurrentIndex(idx)
        else:
             logger.warning(f"SettingsDialog: Current editor theme '{current_editor_theme}' not found in combo box items. Defaulting to first available.")
             if AVAILABLE_SCINTILLA_THEMES:
                 self.appearance_editor_theme_combo.setCurrentIndex(0)
             # If no themes available, it remains disabled with "No themes available" text
        self.appearance_editor_theme_combo.blockSignals(False) # Unblock signals
        # --- REMOVED: Old syntax_style_combo population ---
        # self.appearance_style_combo.blockSignals(True) # Block signals during population
        # self.appearance_style_combo.clear() # Clear existing items
        # # Check if AVAILABLE_PYGMENTS_STYLES is available
        # if AVAILABLE_PYGMENTS_STYLES:
        #      self.appearance_style_combo.addItems(AVAILABLE_PYGMENTS_STYLES)
        #      # Set the current value from settings
        #      current_syntax_style = s.get_setting('syntax_highlighting_style', DEFAULT_CONFIG['syntax_highlighting_style'])
        #      idx = self.appearance_style_combo.findText(current_syntax_style)
        #      if idx >= 0:
        #           self.appearance_style_combo.setCurrentIndex(idx)
        #      else:
        #           logger.warning(f"SettingsDialog: Current syntax style '{current_syntax_style}' not found in combo box items. Defaulting to first.")
        #           self.appearance_style_combo.setCurrentIndex(0)
        # else:
        #      # Handle case where styles list is empty
        #      self.appearance_style_combo.addItem("No styles available")
        #      self.appearance_style_combo.setEnabled(False)
        #      logger.error("SettingsDialog: AVAILABLE_PYGMENTS_STYLES list is empty!")
        # self.appearance_style_combo.blockSignals(False) # Unblock signals


        logger.debug("SettingsDialog: Fields populated.")


    @pyqtSlot()
    def _on_accept(self):
        """Gathers settings from this dialog and saves them via SettingsService."""
        logger.info("SettingsDialog: OK clicked. Saving global settings...")
        s = self._settings_service

        # Prompts are no longer managed here, remove validation/setting logic
        # --- User Prompts JSON validation REMOVED ---

        # --- Parse RAG patterns ---
        # Split the text by comma, strip whitespace, filter out empty strings
        include_patterns = [p.strip() for p in self.rag_include_edit.text().split(',') if p.strip()]
        exclude_patterns = [p.strip() for p in self.rag_exclude_edit.text().split(',') if p.strip()]
        # If the user clears the field, revert to default patterns
        if not include_patterns: include_patterns = DEFAULT_RAG_INCLUDE_PATTERNS
        if not exclude_patterns: exclude_patterns = DEFAULT_RAG_EXCLUDE_PATTERNS
        # --- End Parse RAG patterns ---

        try:
            # Map widgets to setting keys
            dialog_settings_map = {
                # API Keys
                self.llm_api_key_input: 'api_key',
                self.bing_api_key_input: 'rag_bing_api_key',
                self.google_api_key_input: 'rag_google_api_key',
                self.google_cse_id_input: 'rag_google_cse_id',
                # RAG Defaults (Simple types)
                self.rag_rank_model_select: 'rag_ranking_model_name',
                self.rag_rank_threshold_spin: 'rag_similarity_threshold',
                self.rag_dir_depth_spin: 'rag_dir_max_depth',
                # Features
                self.feature_patch_cb: 'patch_mode',
                self.feature_whole_diff_cb: 'whole_file',
                self.feature_disable_critic_cb: 'disable_critic_workflow',
                # Appearance
                self.appearance_font_combo: 'editor_font',
                self.appearance_font_size_spin: 'editor_font_size',
                self.appearance_theme_combo: 'theme',
                # --- RENAMED/NEW: Editor Theme ---
                self.appearance_editor_theme_combo: 'editor_theme',
                # --- REMOVED: Old syntax_style_combo ---
                # self.appearance_style_combo: 'syntax_highlighting_style'
            }

            for widget, key in dialog_settings_map.items():
                value = None
                try:
                    if isinstance(widget, QLineEdit): value = widget.text()
                    elif isinstance(widget, QComboBox): value = widget.currentText()
                    elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): value = widget.value()
                    elif isinstance(widget, QCheckBox): value = widget.isChecked()
                    elif isinstance(widget, QFontComboBox): value = widget.currentFont().family()
                except Exception as e: logger.error(f"Error reading widget {widget.objectName()} for setting '{key}': {e}"); continue

                # Skip disabled editor theme combo if no themes are available
                if widget is self.appearance_editor_theme_combo and not widget.isEnabled():
                    logger.warning("Skipping disabled editor theme combo box.")
                    continue

                # Skip disabled old syntax style combo if pygments missing
                # if widget is self.appearance_style_combo and not widget.isEnabled():
                #     logger.warning("Skipping disabled syntax style combo box.")
                #     continue

                if value is not None:
                    # Use the service to set the value (triggers validation & pyqtSignals)
                    s.set_setting(key, value)
                else:
                    logger.warning(f"Could not determine value for setting '{key}' from widget {widget.objectName()}")

            # Set parsed list values using the service
            s.set_setting('rag_dir_include_patterns', include_patterns)
            s.set_setting('rag_dir_exclude_patterns', exclude_patterns)
            # --- user_prompts setting REMOVED ---

            # Save settings triggers persistence
            if s.save_settings():
                self.accept()
            else:
                # SettingsService.save_settings already shows a QMessageBox on failure
                pass # Do nothing here, let save_settings handle the error message

        except Exception as e:
             logger.exception("Error gathering settings from dialog widgets:")
             # Use QApplication.activeWindow() for parent if self.parent() is None
             parent_widget = self.parent() if self.parent() else QApplication.activeWindow()
             QMessageBox.critical(parent_widget, "Error Saving Settings", f"An unexpected error occurred gathering settings:\n{e}")

    def closeEvent(self, event):
        logger.debug("SettingsDialog closeEvent.")
        super().closeEvent(event)
# --- END OF FILE pm/ui/settings_dialog.py ---