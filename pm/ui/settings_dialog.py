# pm/ui/settings_dialog.py
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
    QDialogButtonBox, QPushButton, QHBoxLayout, QLabel, QVBoxLayout,
    QCheckBox, QFontComboBox, QTabWidget, QWidget, QGroupBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont
from pathlib import Path
from loguru import logger
import qtawesome as qta
from typing import List, Dict, Optional, Any
import re

# --- Local Imports ---
from ..core.settings_service import SettingsService
from ..core.project_config import (AVAILABLE_RAG_MODELS, DEFAULT_CONFIG,
                                   DEFAULT_PROMPT_TEMPLATE, AVAILABLE_PYGMENTS_STYLES,
                                   DEFAULT_STYLE)

# ==========================================================================
# Settings Dialog Class (Refactored)
# ==========================================================================
class SettingsDialog(QDialog):
    """
    Manages global application settings: API Keys, Appearance, Global RAG Defaults, Features.
    Does NOT manage project-specific RAG source enablement (handled by ConfigDock).
    """
    # Signals for requesting model refresh (handled externally)
    request_llm_refresh = Signal(str, str)
    request_summarizer_refresh = Signal(str, str)

    def __init__(self,
                 settings_service: SettingsService,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Global Application Settings')
        # Adjusted size to accommodate RAG defaults
        self.setMinimumSize(650, 500)

        self._settings_service = settings_service

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Create Widgets ---
        self._create_widgets()

        # --- Create Tabs ---
        self.tab_widget.addTab(self._create_api_keys_tab(), "API Keys")
        # Restore RAG Defaults tab
        self.tab_widget.addTab(self._create_rag_defaults_tab(), "RAG Defaults")
        self.tab_widget.addTab(self._create_features_tab(), "Features")
        self.tab_widget.addTab(self._create_appearance_tab(), "Appearance")
        # Prompts tab removed as it's read-only and less critical here

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # --- Connect Signals ---
        self._connect_internal_signals()

        # --- Populate Fields & Initial Refresh ---
        self._populate_all_fields()
        # Request initial refreshes for potential validation (connection is external)
        QTimer.singleShot(50, self._emit_llm_refresh_request)
        QTimer.singleShot(50, self._emit_summarizer_refresh_request)

        logger.debug("SettingsDialog initialized (Global RAG controls restored).")

    def _create_widgets(self):
        """Creates the input widgets relevant to this dialog."""
        logger.debug("SettingsDialog: Creating widgets...")
        # --- API Keys ---
        self.llm_api_key_input = QLineEdit(); self.llm_api_key_input.setObjectName("llm_api_key_input"); self.llm_api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.llm_api_key_label = QLabel('Gemini API Key:'); self.llm_api_key_label.setObjectName("llm_api_key_label")
        self.bing_api_key_input = QLineEdit(); self.bing_api_key_input.setObjectName("bing_api_key_input"); self.bing_api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.bing_api_key_label = QLabel('Bing Search API Key:'); self.bing_api_key_label.setObjectName("bing_api_key_label")
        self.google_api_key_input = QLineEdit(); self.google_api_key_input.setObjectName("google_api_key_input"); self.google_api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.google_api_key_label = QLabel('Google Search API Key:'); self.google_api_key_label.setObjectName("google_api_key_label")
        self.google_cse_id_input = QLineEdit(); self.google_cse_id_input.setObjectName("google_cse_id_input")
        self.google_cse_id_label = QLabel('Google CSE ID:'); self.google_cse_id_label.setObjectName("google_cse_id_label")

        # --- RAG Defaults (RESTORED) ---
        self.rag_rank_model_select = QComboBox(); self.rag_rank_model_select.setObjectName("rag_rank_model_select")
        self.rag_rank_model_select.addItems(AVAILABLE_RAG_MODELS) # Populate with available models
        self.rag_rank_threshold_spin = QDoubleSpinBox(); self.rag_rank_threshold_spin.setObjectName("rag_rank_threshold_spin")
        self.rag_rank_threshold_spin.setRange(0.0, 1.0); self.rag_rank_threshold_spin.setSingleStep(0.05); self.rag_rank_threshold_spin.setDecimals(2)
        self.rag_rank_threshold_spin.setToolTip("Default similarity threshold for ranking RAG results (0.0-1.0)")

        # --- Features ---
        self.feature_patch_cb = QCheckBox("Enable Patch Mode (Apply diffs)"); self.feature_patch_cb.setObjectName("feature_patch_cb")
        self.feature_whole_diff_cb = QCheckBox("Generate Whole-file Diffs (if patch disabled)"); self.feature_whole_diff_cb.setObjectName("feature_whole_diff_cb")

        # --- Appearance ---
        self.appearance_font_combo = QFontComboBox(); self.appearance_font_combo.setObjectName("appearance_font_combo")
        self.appearance_font_size_spin = QSpinBox(); self.appearance_font_size_spin.setObjectName("appearance_font_size_spin")
        self.appearance_theme_combo = QComboBox(); self.appearance_theme_combo.setObjectName("appearance_theme_combo")
        self.appearance_style_combo = QComboBox(); self.appearance_style_combo.setObjectName("appearance_style_combo")
        logger.debug("SettingsDialog: Widgets created.")

    # --- Tab Creation Methods ---
    def _create_api_keys_tab(self) -> QWidget:
        """Creates the tab for managing API keys."""
        tab = QWidget(); layout = QFormLayout(tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addRow(self.llm_api_key_label, self.llm_api_key_input)
        layout.addRow(self.bing_api_key_label, self.bing_api_key_input)
        layout.addRow(self.google_api_key_label, self.google_api_key_input)
        layout.addRow(self.google_cse_id_label, self.google_cse_id_input)
        layout.addRow(QLabel("<i>Note: LLM provider/model selection is in the main Config dock.</i>"))
        return tab

    # --- NEW: RAG Defaults Tab ---
    def _create_rag_defaults_tab(self) -> QWidget:
        """Creates the tab for configuring global RAG default behavior."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Configure global RAG settings (API Keys are in the 'API Keys' tab)."))
        layout.addWidget(QLabel("<i>Project-specific source enablement is handled in the main Config dock.</i>"))
        layout.addSpacing(10)

        group = QGroupBox("Ranking & Filtering Defaults")
        form_layout = QFormLayout(group)
        form_layout.addRow("Embedding Model:", self.rag_rank_model_select)
        form_layout.addRow("Similarity Threshold:", self.rag_rank_threshold_spin)
        layout.addWidget(group)
        layout.addStretch(1)
        return tab

    def _create_features_tab(self) -> QWidget:
        """Creates the tab for enabling/disabling features."""
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        patch_group = QGroupBox("Patch/Diff Features"); patch_layout = QVBoxLayout(patch_group)
        patch_layout.addWidget(self.feature_patch_cb)
        patch_layout.addWidget(self.feature_whole_diff_cb)
        layout.addWidget(patch_group)
        layout.addStretch(1)
        return tab

    def _create_appearance_tab(self) -> QWidget:
        """Creates the tab for appearance settings."""
        tab = QWidget(); layout = QFormLayout(tab)
        self.appearance_font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts); layout.addRow("Editor Font:", self.appearance_font_combo)
        self.appearance_font_size_spin.setRange(8, 32); layout.addRow("Editor Font Size:", self.appearance_font_size_spin)
        self.appearance_theme_combo.addItems(["Dark", "Light"]); layout.addRow("UI Theme:", self.appearance_theme_combo)
        if AVAILABLE_PYGMENTS_STYLES: self.appearance_style_combo.addItems(AVAILABLE_PYGMENTS_STYLES)
        else: self.appearance_style_combo.addItem("Pygments not found"); self.appearance_style_combo.setEnabled(False)
        layout.addRow("Syntax Style:", self.appearance_style_combo)
        return tab

    # --- Signal Connections ---
    def _connect_internal_signals(self):
        """Connect signals for widgets *within* this dialog."""
        logger.debug("SettingsDialog: Connecting internal signals...")
        self.feature_patch_cb.toggled.connect(self.feature_whole_diff_cb.setEnabled)
        logger.debug("SettingsDialog: Internal signals connected.")

    # --- Data Population & UI State ---
    def _populate_all_fields(self):
        """Populates all widgets with values from SettingsService."""
        logger.debug("SettingsDialog: Populating relevant fields from SettingsService...")
        s = self._settings_service

        # API Keys
        self.llm_api_key_input.setText(s.get_setting('api_key', ''))
        self.bing_api_key_input.setText(s.get_setting('rag_bing_api_key', ''))
        self.google_api_key_input.setText(s.get_setting('rag_google_api_key', ''))
        self.google_cse_id_input.setText(s.get_setting('rag_google_cse_id', ''))

        # RAG Defaults
        self.rag_rank_model_select.setCurrentText(s.get_setting('rag_ranking_model_name', AVAILABLE_RAG_MODELS[0]))
        self.rag_rank_threshold_spin.setValue(float(s.get_setting('rag_similarity_threshold', 0.30)))

        # Features
        self.feature_patch_cb.setChecked(s.get_setting('patch_mode', True))
        self.feature_whole_diff_cb.setChecked(s.get_setting('whole_file', True))
        self.feature_whole_diff_cb.setEnabled(self.feature_patch_cb.isChecked())

        # Appearance
        try: self.appearance_font_combo.setCurrentFont(QFont(s.get_setting('editor_font', 'Fira Code')))
        except Exception as e: logger.warning(f"Failed to set font: {e}"); self.appearance_font_combo.setCurrentFont(QFont("Monospace"))
        self.appearance_font_size_spin.setValue(int(s.get_setting('editor_font_size', 11)))
        self.appearance_theme_combo.setCurrentText(s.get_setting('theme', 'Dark'))
        current_style = s.get_setting('syntax_highlighting_style', DEFAULT_STYLE)
        if self.appearance_style_combo.isEnabled():
            style_index = self.appearance_style_combo.findText(current_style)
            if style_index >= 0: self.appearance_style_combo.setCurrentIndex(style_index)
            else: logger.warning(f"Populate: Style '{current_style}' not in combo, using default."); self.appearance_style_combo.setCurrentText(DEFAULT_STYLE)

        logger.debug("SettingsDialog: Fields populated.")

    # --- Model Refresh Slots (remain, used externally if needed) ---
    @Slot(list)
    def _populate_llm_model_select(self, models: list):
         pass # No LLM combo here

    @Slot(list)
    def _populate_summarizer_model_select(self, models: list):
         pass # No summarizer combo here

    @Slot(str, str)
    def _handle_refresh_error(self, provider_type: str, error_message: str):
        logger.error(f"SettingsDialog: Received model refresh error for {provider_type}: {error_message}")
        # Optionally show non-modal feedback

    # --- Emit Refresh Requests (remain) ---
    @Slot()
    def _emit_llm_refresh_request(self):
        provider = self._settings_service.get_setting('provider', 'Ollama')
        api_key = self.llm_api_key_input.text() if provider.lower() == 'gemini' else None
        self.request_llm_refresh.emit(provider, api_key)

    @Slot()
    def _emit_summarizer_refresh_request(self):
        provider = self._settings_service.get_setting('rag_summarizer_provider', 'Ollama')
        api_key = self.llm_api_key_input.text() if provider.lower() == 'gemini' else None
        self.request_summarizer_refresh.emit(provider, api_key)

    # --- Dialog Acceptance (Save Settings) ---
    @Slot()
    def _on_accept(self):
        """Gathers settings ONLY from this dialog's widgets and saves them."""
        logger.info("SettingsDialog: OK clicked. Saving global settings via SettingsService...")
        s = self._settings_service

        try:
            # Define ONLY the settings managed by this dialog
            dialog_settings_map = {
                # API Keys
                self.llm_api_key_input: 'api_key',
                self.bing_api_key_input: 'rag_bing_api_key',
                self.google_api_key_input: 'rag_google_api_key',
                self.google_cse_id_input: 'rag_google_cse_id',
                # RAG Defaults
                self.rag_rank_model_select: 'rag_ranking_model_name', # RESTORED
                self.rag_rank_threshold_spin: 'rag_similarity_threshold', # RESTORED
                # Features
                self.feature_patch_cb: 'patch_mode',
                self.feature_whole_diff_cb: 'whole_file',
                # Appearance
                self.appearance_font_combo: 'editor_font',
                self.appearance_font_size_spin: 'editor_font_size',
                self.appearance_theme_combo: 'theme',
                self.appearance_style_combo: 'syntax_highlighting_style'
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

                if widget is self.appearance_style_combo and not widget.isEnabled(): continue

                if value is not None: s.set_setting(key, value)
                else: logger.warning(f"Could not determine value for setting '{key}' from widget {widget.objectName()}")

            # Trigger save in the service. Note: SettingsService.save_settings() might
            # need enhancement later if we want separate global/project persistent files.
            # For now, it saves everything merged to the project file.
            if s.save_settings():
                self.accept()
            else:
                QMessageBox.critical(self, "Error Saving Settings", "Failed to save settings. Please check logs.")

        except Exception as e:
             logger.exception("Error gathering settings from dialog widgets:")
             QMessageBox.critical(self, "Error Saving Settings", f"An unexpected error occurred gathering settings:\n{e}")

    def closeEvent(self, event):
        logger.debug("SettingsDialog closeEvent.")
        super().closeEvent(event)
