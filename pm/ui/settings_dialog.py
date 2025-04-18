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
from ..core.model_list_service import ModelListService
from ..core.project_config import (AVAILABLE_RAG_MODELS, DEFAULT_CONFIG,
                                   DEFAULT_PROMPT_TEMPLATE, AVAILABLE_PYGMENTS_STYLES,
                                   DEFAULT_STYLE)
# Model registry no longer needed here, handled by ModelListService/SettingsService

# ==========================================================================
# Settings Dialog Class (Refactored)
# ==========================================================================
class SettingsDialog(QDialog):
    """
    Application settings dialog. Reads from and writes to SettingsService.
    Uses ModelListService for populating model dropdowns.
    """
    def __init__(self,
                 settings_service: SettingsService,
                 model_list_service: ModelListService,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Application Settings')
        self.setMinimumSize(700, 650)

        self._settings_service = settings_service
        self._model_list_service = model_list_service

        # --- Local state for RAG list (mirroring settings service) ---
        # This is temporary until full sync via signals is robust
        self._local_rag_sources_cache: List[Dict] = []

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Create Widgets (Internal references stored) ---
        self._create_widgets()

        # --- Create Tabs (Populate with created widgets) ---
        self.tab_widget.addTab(self._create_llm_tab(), "LLM")
        self.tab_widget.addTab(self._create_prompts_tab(), "Prompts")
        self.tab_widget.addTab(self._create_rag_tab(), "RAG")
        self.tab_widget.addTab(self._create_features_tab(), "Features")
        self.tab_widget.addTab(self._create_appearance_tab(), "Appearance")

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._on_accept) # Connect before populate
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # --- Connect Signals ---
        self._connect_internal_signals() # Connections between widgets within the dialog
        self._connect_service_signals()  # Connections to external services

        # --- Populate Fields & Initial Refresh ---
        self._populate_all_fields() # Populate from SettingsService
        # Trigger initial model refreshes (delay slightly to ensure UI is stable)
        QTimer.singleShot(10, self._refresh_llm_models)
        QTimer.singleShot(10, self._refresh_summarizer_models)

        logger.debug("SettingsDialog initialized.")

    # --- Widget Creation ---
    def _create_widgets(self):
        """Creates all the input widgets for the dialog. Stored as self attributes."""
        logger.debug("SettingsDialog: Creating widgets...")
        # LLM
        self.llm_provider_select = QComboBox(); self.llm_provider_select.setObjectName("llm_provider_select")
        self.llm_model_select = QComboBox(); self.llm_model_select.setObjectName("llm_model_select")
        self.llm_api_key_input = QLineEdit(); self.llm_api_key_input.setObjectName("llm_api_key_input")
        self.llm_api_key_label = QLabel('API Key (Gemini):'); self.llm_api_key_label.setObjectName("llm_api_key_label")
        self.llm_temp_spin = QDoubleSpinBox(); self.llm_temp_spin.setObjectName("llm_temp_spin")
        self.llm_topk_spin = QSpinBox(); self.llm_topk_spin.setObjectName("llm_topk_spin")
        self.llm_ctx_limit_label = QLabel("..."); self.llm_ctx_limit_label.setObjectName("llm_ctx_limit_label")
        self.llm_refresh_btn = QPushButton(qta.icon('fa5s.sync-alt'), ""); self.llm_refresh_btn.setObjectName("llm_refresh_btn")

        # Prompts
        self.system_prompt_input = QTextEdit(); self.system_prompt_input.setObjectName("system_prompt_input")
        self.main_prompt_template_input = QTextEdit(); self.main_prompt_template_input.setObjectName("main_prompt_template_input")
        self.summarizer_prompt_input = QTextEdit(); self.summarizer_prompt_input.setObjectName("summarizer_prompt_input")

        # RAG - Local
        self.rag_local_enable_cb = QCheckBox("Enable Local RAG"); self.rag_local_enable_cb.setObjectName("rag_local_enable_cb")
        self.rag_local_list_widget = QListWidget(); self.rag_local_list_widget.setObjectName("rag_local_list_widget")
        self.rag_local_add_dir_btn = QPushButton(qta.icon('fa5s.folder-plus'), " Add Dir..."); self.rag_local_add_dir_btn.setObjectName("rag_local_add_dir_btn")
        self.rag_local_add_file_btn = QPushButton(qta.icon('fa5s.file-medical'), " Add File..."); self.rag_local_add_file_btn.setObjectName("rag_local_add_file_btn")
        self.rag_local_remove_btn = QPushButton(qta.icon('fa5s.trash-alt'), " Remove"); self.rag_local_remove_btn.setObjectName("rag_local_remove_btn")

        # RAG - External Master & Groups
        self.rag_external_enable_cb = QCheckBox("Enable External RAG"); self.rag_external_enable_cb.setObjectName("rag_external_enable_cb")
        self.summarizer_group = QGroupBox("Query Summarization"); self.summarizer_group.setObjectName("summarizer_group")
        self.ranking_group = QGroupBox("Ranking"); self.ranking_group.setObjectName("ranking_group")
        self.sources_group = QGroupBox("Sources & Configuration"); self.sources_group.setObjectName("sources_group")

        # RAG - Summarizer
        self.rag_summarizer_enable_cb = QCheckBox("Enable"); self.rag_summarizer_enable_cb.setObjectName("rag_summarizer_enable_cb") # Simpler label
        self.rag_summarizer_provider_select = QComboBox(); self.rag_summarizer_provider_select.setObjectName("rag_summarizer_provider_select")
        self.rag_summarizer_model_select = QComboBox(); self.rag_summarizer_model_select.setObjectName("rag_summarizer_model_select")
        self.rag_summarizer_refresh_btn = QPushButton(qta.icon('fa5s.sync-alt'), ""); self.rag_summarizer_refresh_btn.setObjectName("rag_summarizer_refresh_btn")

        # RAG - Ranking
        self.rag_rank_model_select = QComboBox(); self.rag_rank_model_select.setObjectName("rag_rank_model_select")
        self.rag_rank_threshold_spin = QDoubleSpinBox(); self.rag_rank_threshold_spin.setObjectName("rag_rank_threshold_spin")

        # RAG - Sources
        self.rag_source_google_cb = QCheckBox("Google Search"); self.rag_source_google_cb.setObjectName("rag_source_google_cb")
        self.rag_source_google_api_input = QLineEdit(); self.rag_source_google_api_input.setObjectName("rag_source_google_api_input")
        self.rag_source_google_cse_input = QLineEdit(); self.rag_source_google_cse_input.setObjectName("rag_source_google_cse_input")
        self.google_config_widget = QWidget(); self.google_config_widget.setObjectName("google_config_widget") # Container
        self.rag_source_bing_cb = QCheckBox("Bing Search"); self.rag_source_bing_cb.setObjectName("rag_source_bing_cb")
        self.rag_source_bing_api_input = QLineEdit(); self.rag_source_bing_api_input.setObjectName("rag_source_bing_api_input")
        self.bing_config_widget = QWidget(); self.bing_config_widget.setObjectName("bing_config_widget") # Container
        self.rag_source_stackexchange_cb = QCheckBox("Stack Exchange"); self.rag_source_stackexchange_cb.setObjectName("rag_source_stackexchange_cb")
        self.rag_source_github_cb = QCheckBox("GitHub"); self.rag_source_github_cb.setObjectName("rag_source_github_cb")
        self.rag_source_arxiv_cb = QCheckBox("ArXiv"); self.rag_source_arxiv_cb.setObjectName("rag_source_arxiv_cb")

        # Features
        self.feature_patch_cb = QCheckBox("Enable Patch Mode"); self.feature_patch_cb.setObjectName("feature_patch_cb")
        self.feature_whole_diff_cb = QCheckBox("Generate Whole-file Diffs"); self.feature_whole_diff_cb.setObjectName("feature_whole_diff_cb")

        # Appearance
        self.appearance_font_combo = QFontComboBox(); self.appearance_font_combo.setObjectName("appearance_font_combo")
        self.appearance_font_size_spin = QSpinBox(); self.appearance_font_size_spin.setObjectName("appearance_font_size_spin")
        self.appearance_theme_combo = QComboBox(); self.appearance_theme_combo.setObjectName("appearance_theme_combo")
        self.appearance_style_combo = QComboBox(); self.appearance_style_combo.setObjectName("appearance_style_combo")
        logger.debug("SettingsDialog: Widgets created.")

    # --- Tab Creation Methods ---
    # (These methods now just assemble the pre-created widgets into layouts)
    def _create_llm_tab(self) -> QWidget:
        tab = QWidget(); layout = QFormLayout(tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.llm_provider_select.addItems(['Ollama', 'Gemini'])
        layout.addRow('Provider:', self.llm_provider_select)
        self.llm_refresh_btn.setFixedWidth(35); self.llm_refresh_btn.setToolTip("Refresh model list")
        model_row = QHBoxLayout(); model_row.addWidget(self.llm_model_select, 1); model_row.addWidget(self.llm_refresh_btn)
        layout.addRow('Model:', model_row)
        self.llm_api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        layout.addRow(self.llm_api_key_label, self.llm_api_key_input)
        self.llm_temp_spin.setRange(0.0, 2.0); self.llm_temp_spin.setSingleStep(0.1); self.llm_temp_spin.setDecimals(1); self.llm_temp_spin.setToolTip("Controls randomness.")
        layout.addRow('Temperature:', self.llm_temp_spin)
        self.llm_topk_spin.setRange(0, 200); self.llm_topk_spin.setToolTip("Consider top K tokens (0=disabled).")
        layout.addRow('Top‑K:', self.llm_topk_spin)
        layout.addRow("Max Context:", self.llm_ctx_limit_label)
        return tab

    def _create_prompts_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)
        sys_group = QGroupBox("System Prompt")
        sys_layout = QVBoxLayout(sys_group); sys_layout.setContentsMargins(5, 5, 5, 5)
        self.system_prompt_input.setAcceptRichText(False); self.system_prompt_input.setMinimumHeight(80); self.system_prompt_input.setPlaceholderText("e.g., You are a helpful expert Python programmer...")
        sys_layout.addWidget(self.system_prompt_input)
        layout.addWidget(sys_group)
        main_tmpl_group = QGroupBox("Main Prompt Template")
        main_tmpl_layout = QVBoxLayout(main_tmpl_group); main_tmpl_layout.setContentsMargins(5, 5, 5, 5)
        main_tmpl_layout.addWidget(QLabel("Variables: {system_prompt}, {chat_history}, {code_context}, {local_context}, {remote_context}, {user_query}"))
        self.main_prompt_template_input.setAcceptRichText(False); self.main_prompt_template_input.setMinimumHeight(150); self.main_prompt_template_input.setPlaceholderText(DEFAULT_PROMPT_TEMPLATE)
        self.main_prompt_template_input.setFont(QFont("Monospace", 10))
        main_tmpl_layout.addWidget(self.main_prompt_template_input)
        layout.addWidget(main_tmpl_group, 1)
        summ_group = QGroupBox("RAG Query Summarizer Prompt Template")
        summ_layout = QVBoxLayout(summ_group); summ_layout.setContentsMargins(5, 5, 5, 5)
        self.summarizer_prompt_input.setAcceptRichText(False); self.summarizer_prompt_input.setFixedHeight(80); self.summarizer_prompt_input.setPlaceholderText("e.g., Condense the following into a search query:\n{original_query}\nSearch Query:")
        summ_layout.addWidget(self.summarizer_prompt_input)
        layout.addWidget(summ_group)
        return tab

    def _create_rag_tab(self) -> QWidget:
        tab = QWidget(); main_layout = QVBoxLayout(tab); main_layout.setSpacing(10)
        # Local RAG Group
        lg = QGroupBox("Local Sources"); ll = QVBoxLayout(lg)
        ll.addWidget(self.rag_local_enable_cb)
        ll.addWidget(self.rag_local_list_widget, 1)
        lb = QHBoxLayout(); lb.addWidget(self.rag_local_add_dir_btn); lb.addWidget(self.rag_local_add_file_btn); lb.addStretch(1); lb.addWidget(self.rag_local_remove_btn)
        ll.addLayout(lb); main_layout.addWidget(lg)
        # External RAG Group
        eg = QGroupBox("External Sources (Web)"); el = QVBoxLayout(eg)
        el.addWidget(self.rag_external_enable_cb)
        # Summarizer Group (Inside External)
        sl = QFormLayout(self.summarizer_group); sl.setContentsMargins(5, 5, 5, 5)
        sl.addRow(self.rag_summarizer_enable_cb) # Checkbox now first
        self.rag_summarizer_provider_select.addItems(["Ollama", "Gemini"])
        sl.addRow("Provider:", self.rag_summarizer_provider_select)
        smr = QHBoxLayout(); smr.addWidget(self.rag_summarizer_model_select, 1)
        self.rag_summarizer_refresh_btn.setFixedWidth(35); self.rag_summarizer_refresh_btn.setToolTip("Refresh model list")
        smr.addWidget(self.rag_summarizer_refresh_btn); sl.addRow("Model:", smr)
        el.addWidget(self.summarizer_group)
        # Ranking Group (Inside External)
        rl = QFormLayout(self.ranking_group); rl.setContentsMargins(5, 5, 5, 5)
        self.rag_rank_model_select.addItems(AVAILABLE_RAG_MODELS)
        rl.addRow("Model:", self.rag_rank_model_select)
        self.rag_rank_threshold_spin.setRange(0.0, 1.0); self.rag_rank_threshold_spin.setSingleStep(0.05); self.rag_rank_threshold_spin.setDecimals(2)
        rl.addRow("Threshold:", self.rag_rank_threshold_spin)
        el.addWidget(self.ranking_group)
        # Sources Config Group (Inside External)
        ssl = QFormLayout(self.sources_group); ssl.setContentsMargins(5, 5, 5, 5)
        ssl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # Google config
        gcl = QFormLayout(self.google_config_widget); gcl.setContentsMargins(0, 0, 0, 0)
        self.rag_source_google_api_input.setPlaceholderText("API Key"); self.rag_source_google_api_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.rag_source_google_cse_input.setPlaceholderText("CSE ID")
        gcl.addRow("API Key:", self.rag_source_google_api_input); gcl.addRow("CSE ID:", self.rag_source_google_cse_input)
        ssl.addRow(self.rag_source_google_cb, self.google_config_widget)
        # Bing config
        bcl = QFormLayout(self.bing_config_widget); bcl.setContentsMargins(0, 0, 0, 0)
        self.rag_source_bing_api_input.setPlaceholderText("Enter Bing API Key"); self.rag_source_bing_api_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        bcl.addRow("API Key:", self.rag_source_bing_api_input)
        ssl.addRow(self.rag_source_bing_cb, self.bing_config_widget)
        # Other sources
        ssl.addRow(self.rag_source_stackexchange_cb, QLabel("<i>(Uses DDG/Bing)</i>"))
        ssl.addRow(self.rag_source_github_cb, QLabel("<i>(Uses DDG/Bing)</i>"))
        ssl.addRow(self.rag_source_arxiv_cb, QLabel("<i>(Uses API)</i>"))
        el.addWidget(self.sources_group)
        main_layout.addWidget(eg); main_layout.addStretch(1)
        return tab

    def _create_features_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        pg = QGroupBox("Patch/Diff Features"); pl = QVBoxLayout(pg); pl.addWidget(self.feature_patch_cb); pl.addWidget(self.feature_whole_diff_cb); layout.addWidget(pg)
        layout.addStretch(1)
        return tab

    def _create_appearance_tab(self) -> QWidget:
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
        """Connect signals for widgets *within* the dialog."""
        logger.debug("SettingsDialog: Connecting internal signals...")
        # LLM Tab
        self.llm_provider_select.currentTextChanged.connect(self._llm_provider_changed)
        self.llm_model_select.currentTextChanged.connect(self._update_context_limit_display)
        self.llm_refresh_btn.clicked.connect(self._refresh_llm_models)

        # RAG Tab - Local
        self.rag_local_add_dir_btn.clicked.connect(self._add_local_rag_directory)
        self.rag_local_add_file_btn.clicked.connect(self._add_local_rag_file)
        self.rag_local_remove_btn.clicked.connect(self._remove_selected_local_rag_source)
        self.rag_local_enable_cb.toggled.connect(self._toggle_local_rag_widgets)
        self.rag_local_list_widget.itemChanged.connect(self._local_rag_item_changed) # Handle checkbox changes

        # RAG Tab - External
        self.rag_external_enable_cb.toggled.connect(self._toggle_external_rag_widgets)
        self.rag_summarizer_enable_cb.toggled.connect(self._toggle_summarizer_widgets)
        self.rag_summarizer_provider_select.currentTextChanged.connect(self._summarizer_provider_changed)
        self.rag_summarizer_refresh_btn.clicked.connect(self._refresh_summarizer_models)
        self.rag_source_google_cb.toggled.connect(lambda checked: self.google_config_widget.setEnabled(self.rag_external_enable_cb.isChecked() and checked))
        self.rag_source_bing_cb.toggled.connect(lambda checked: self.bing_config_widget.setEnabled(self.rag_external_enable_cb.isChecked() and checked))

        # Features Tab
        self.feature_patch_cb.toggled.connect(self.feature_whole_diff_cb.setEnabled)
        logger.debug("SettingsDialog: Internal signals connected.")

    def _connect_service_signals(self):
        """Connect signals from external services (ModelListService)."""
        logger.debug("SettingsDialog: Connecting service signals...")
        # Connect to ModelListService signals
        self._model_list_service.llm_models_updated.connect(self._populate_llm_model_select)
        self._model_list_service.summarizer_models_updated.connect(self._populate_summarizer_model_select)
        self._model_list_service.model_refresh_error.connect(self._handle_refresh_error)

        # Connect to SettingsService for RAG list updates (if implemented with signals)
        self._settings_service.local_rag_sources_changed.connect(self._populate_local_rag_list)

        logger.debug("SettingsDialog: Service signals connected.")


    # --- Data Population & UI State ---
    def _populate_all_fields(self):
        """Populates all widgets with values from SettingsService."""
        logger.debug("SettingsDialog: Populating all fields from SettingsService...")
        s = self._settings_service # Shortcut

        # LLM
        self.llm_provider_select.setCurrentText(s.get_setting('provider', 'Ollama'))
        # Model combo is populated by _populate_llm_model_select slot
        self.llm_api_key_input.setText(s.get_setting('api_key', ''))
        self.llm_temp_spin.setValue(float(s.get_setting('temperature', 0.3)))
        self.llm_topk_spin.setValue(int(s.get_setting('top_k', 40)))
        # Context limit label is updated by _update_context_limit_display slot

        # Prompts
        self.main_prompt_template_input.setPlainText(s.get_setting('main_prompt_template', DEFAULT_PROMPT_TEMPLATE))
        self.system_prompt_input.setPlainText(s.get_setting('system_prompt', DEFAULT_CONFIG['system_prompt']))
        self.summarizer_prompt_input.setPlainText(s.get_setting('rag_summarizer_prompt_template', DEFAULT_CONFIG['rag_summarizer_prompt_template']))

        # RAG - Local
        self.rag_local_enable_cb.setChecked(s.get_setting('rag_local_enabled', False))
        self._populate_local_rag_list() # Populate list from service

        # RAG - External
        self.rag_external_enable_cb.setChecked(s.get_setting('rag_external_enabled', True))
        self.rag_summarizer_enable_cb.setChecked(s.get_setting('rag_summarizer_enabled', True))
        self.rag_summarizer_provider_select.setCurrentText(s.get_setting('rag_summarizer_provider', 'Ollama'))
        # Summarizer model combo populated by _populate_summarizer_model_select slot
        self.rag_rank_model_select.setCurrentText(s.get_setting('rag_ranking_model_name', AVAILABLE_RAG_MODELS[0]))
        self.rag_rank_threshold_spin.setValue(float(s.get_setting('rag_similarity_threshold', 0.30)))
        self.rag_source_google_cb.setChecked(s.get_setting('rag_google_enabled', False)); self.rag_source_google_api_input.setText(s.get_setting('rag_google_api_key', '')); self.rag_source_google_cse_input.setText(s.get_setting('rag_google_cse_id', ''))
        self.rag_source_bing_cb.setChecked(s.get_setting('rag_bing_enabled', True)); self.rag_source_bing_api_input.setText(s.get_setting('rag_bing_api_key', ''))
        self.rag_source_stackexchange_cb.setChecked(s.get_setting('rag_stackexchange_enabled', True))
        self.rag_source_github_cb.setChecked(s.get_setting('rag_github_enabled', True))
        self.rag_source_arxiv_cb.setChecked(s.get_setting('rag_arxiv_enabled', False))

        # Features
        self.feature_patch_cb.setChecked(s.get_setting('patch_mode', True))
        self.feature_whole_diff_cb.setChecked(s.get_setting('whole_file', True))

        # Appearance
        try: self.appearance_font_combo.setCurrentFont(QFont(s.get_setting('editor_font', 'Fira Code')))
        except Exception as e: logger.warning(f"Failed to set font: {e}"); self.appearance_font_combo.setCurrentFont(QFont("Monospace"))
        self.appearance_font_size_spin.setValue(int(s.get_setting('editor_font_size', 11)))
        self.appearance_theme_combo.setCurrentText(s.get_setting('theme', 'Dark'))
        current_style = s.get_setting('syntax_highlighting_style', DEFAULT_STYLE)
        if self.appearance_style_combo.isEnabled(): # Check if combo is enabled (Pygments found)
            style_index = self.appearance_style_combo.findText(current_style)
            if style_index >= 0: self.appearance_style_combo.setCurrentIndex(style_index)
            else: logger.warning(f"Populate: Style '{current_style}' not in combo, using default."); self.appearance_style_combo.setCurrentText(DEFAULT_STYLE)

        # --- Trigger initial UI state updates based on populated values ---
        self._llm_provider_changed(self.llm_provider_select.currentText())
        self._toggle_local_rag_widgets(self.rag_local_enable_cb.isChecked())
        self._toggle_external_rag_widgets(self.rag_external_enable_cb.isChecked())

        logger.debug("SettingsDialog: Fields populated.")

    # --- Model Refresh Slots ---
    @Slot()
    def _refresh_llm_models(self):
        """Triggers the background LLM model list refresh via ModelListService."""
        provider = self.llm_provider_select.currentText()
        api_key = self.llm_api_key_input.text() if provider.lower() == 'gemini' else None
        self.llm_model_select.blockSignals(True) # Prevent triggering changes while loading
        self.llm_model_select.clear(); self.llm_model_select.addItem('⏳ loading...'); self.llm_model_select.setEnabled(False)
        self.llm_model_select.blockSignals(False)
        self._model_list_service.refresh_models('llm', provider, api_key)

    @Slot()
    def _refresh_summarizer_models(self):
        """Triggers the background Summarizer model list refresh via ModelListService."""
        provider = self.rag_summarizer_provider_select.currentText()
        # Summarizer doesn't usually need a separate API key if it's Gemini
        api_key = self._settings_service.get_setting('api_key') if provider.lower() == 'gemini' else None
        self.rag_summarizer_model_select.blockSignals(True)
        self.rag_summarizer_model_select.clear(); self.rag_summarizer_model_select.addItem('⏳ loading...'); self.rag_summarizer_model_select.setEnabled(False)
        self.rag_summarizer_model_select.blockSignals(False)
        self._model_list_service.refresh_models('summarizer', provider, api_key)

    @Slot(list)
    def _populate_llm_model_select(self, models: list):
        """Populates the LLM model combo box (Slot connected to ModelListService)."""
        logger.info(f"SettingsDialog: Populating LLM models ({len(models)})")
        combo = self.llm_model_select
        combo.blockSignals(True)
        combo.clear()
        stored_model = self._settings_service.get_setting('model', '') # Get intended model

        if models:
            combo.addItems(models)
            combo.setEnabled(True)
            model_index = combo.findText(stored_model)
            if model_index >= 0:
                combo.setCurrentIndex(model_index)
            elif models: # If previous selection invalid, select the first one
                combo.setCurrentIndex(0)
                # Important: Update the setting if we fallback to the first model
                QTimer.singleShot(0, lambda: self._settings_service.set_setting('model', combo.currentText()))
            logger.debug(f"LLM combobox populated. Current: '{combo.currentText()}'")
        else:
            combo.addItem('No models found')
            combo.setEnabled(False)
            logger.warning("No models found for LLM dropdown.")

        combo.blockSignals(False)
        self._update_context_limit_display() # Update limit after populating

    @Slot(list)
    def _populate_summarizer_model_select(self, models: list):
        """Populates the Summarizer model combo box (Slot connected to ModelListService)."""
        logger.info(f"SettingsDialog: Populating Summarizer models ({len(models)})")
        combo = self.rag_summarizer_model_select
        combo.blockSignals(True)
        combo.clear()
        stored_model = self._settings_service.get_setting('rag_summarizer_model_name', '')

        if models:
            combo.addItems(models)
            combo.setEnabled(True)
            model_index = combo.findText(stored_model)
            if model_index >= 0:
                combo.setCurrentIndex(model_index)
            elif models: # Fallback to first model
                combo.setCurrentIndex(0)
                QTimer.singleShot(0, lambda: self._settings_service.set_setting('rag_summarizer_model_name', combo.currentText()))
            logger.debug(f"Summarizer combobox populated. Current: '{combo.currentText()}'")
        else:
            combo.addItem('No models found')
            combo.setEnabled(False)
            logger.warning("No models found for Summarizer dropdown.")

        combo.blockSignals(False)

    @Slot(str, str)
    def _handle_refresh_error(self, provider_type: str, error_message: str):
        """Handles errors reported by the ModelListService."""
        logger.error(f"SettingsDialog: Received model refresh error for {provider_type}: {error_message}")
        combo = None
        if provider_type == 'llm': combo = self.llm_model_select
        elif provider_type == 'summarizer': combo = self.rag_summarizer_model_select

        if combo:
             combo.blockSignals(True)
             combo.clear()
             combo.addItem("Error loading models")
             combo.setEnabled(False)
             combo.blockSignals(False)
        # Optionally show a message box?
        # QMessageBox.warning(self, f"{provider_type.upper()} Model Load Error", f"Could not load models:\n{error_message}")


    # --- Internal UI Logic Slots ---
    @Slot(str)
    def _llm_provider_changed(self, provider_text: str):
        """Handles LLM provider selection change."""
        is_gemini = provider_text.lower() == 'gemini'
        self.llm_api_key_label.setVisible(is_gemini)
        self.llm_api_key_input.setVisible(is_gemini)
        self._refresh_llm_models() # Refresh models for the new provider

    @Slot(str)
    def _summarizer_provider_changed(self, provider_text: str):
        """Handles Summarizer provider selection change."""
        self._refresh_summarizer_models()

    @Slot()
    def _update_context_limit_display(self):
        """Updates the LLM context limit label based on current selection."""
        # Use SettingsService to get the *resolved* limit for the currently selected model
        limit = self._settings_service.get_setting('context_limit', 0) # Relies on service resolving it
        # Alternatively, resolve it here based on UI selection (but duplicates logic)
        # provider = self.llm_provider_select.currentText(); model = self.llm_model_select.currentText()
        # limit = resolve_context_limit(provider, model) if model and 'loading' not in model else 0
        limit_text = f"{limit:,} tokens" if limit > 0 else "N/A"
        self.llm_ctx_limit_label.setText(limit_text)

    @Slot(bool)
    def _toggle_local_rag_widgets(self, enabled: bool):
        self.rag_local_list_widget.setEnabled(enabled)
        self.rag_local_add_dir_btn.setEnabled(enabled)
        self.rag_local_add_file_btn.setEnabled(enabled)
        self.rag_local_remove_btn.setEnabled(enabled)

    @Slot(bool)
    def _toggle_external_rag_widgets(self, enabled: bool):
        self.summarizer_group.setEnabled(enabled)
        self.ranking_group.setEnabled(enabled)
        self.sources_group.setEnabled(enabled)
        self._toggle_summarizer_widgets(enabled and self.rag_summarizer_enable_cb.isChecked())
        self.google_config_widget.setEnabled(enabled and self.rag_source_google_cb.isChecked())
        self.bing_config_widget.setEnabled(enabled and self.rag_source_bing_cb.isChecked())
        self.rag_source_google_cb.setEnabled(enabled)
        self.rag_source_bing_cb.setEnabled(enabled)
        self.rag_source_stackexchange_cb.setEnabled(enabled)
        self.rag_source_github_cb.setEnabled(enabled)
        self.rag_source_arxiv_cb.setEnabled(enabled)

    @Slot(bool)
    def _toggle_summarizer_widgets(self, enabled: bool):
        is_enabled = enabled and self.rag_external_enable_cb.isChecked()
        # Enable/disable provider/model/refresh, but NOT the main enable checkbox itself
        self.rag_summarizer_provider_select.setEnabled(is_enabled)
        self.rag_summarizer_model_select.setEnabled(is_enabled)
        self.rag_summarizer_refresh_btn.setEnabled(is_enabled)
        self.summarizer_prompt_input.setEnabled(is_enabled) # Enable prompt editing too

    # --- Local RAG List Management ---
    @Slot(list) # Connected to SettingsService.local_rag_sources_changed
    def _populate_local_rag_list(self, sources: Optional[List[Dict]] = None):
        """Populates the local RAG list widget from SettingsService data."""
        if sources is None: # If called without signal data, fetch from service
            sources = self._settings_service.get_local_rag_sources()
        logger.debug(f"Populating Local RAG list with {len(sources)} sources.")
        self._local_rag_sources_cache = sources # Update local cache
        self.rag_local_list_widget.blockSignals(True)
        self.rag_local_list_widget.clear()
        for source_info in sources:
             path_str = source_info.get('path')
             enabled = source_info.get('enabled', True)
             if path_str:
                  self._add_local_rag_item_widget(path_str, enabled)
        self.rag_local_list_widget.blockSignals(False)

    def _add_local_rag_item_widget(self, path_str: str, enabled: bool = True):
        """Helper to add a single item widget to the RAG list."""
        try:
            path_obj = Path(path_str)
            display_name = path_obj.name
            item = QListWidgetItem(display_name)
            item.setToolTip(path_str)
            item.setData(Qt.ItemDataRole.UserRole, path_str) # Store full path
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.rag_local_list_widget.addItem(item)
        except Exception as e:
            logger.error(f"Failed to create list item for RAG source '{path_str}': {e}")

    @Slot(QListWidgetItem)
    def _local_rag_item_changed(self, item: QListWidgetItem):
         """Handles check state changes in the local RAG list."""
         path_str = item.data(Qt.ItemDataRole.UserRole)
         is_checked = item.checkState() == Qt.CheckState.Checked
         if path_str:
              logger.debug(f"Local RAG item '{path_str}' check state changed to: {is_checked}")
              # Update the setting via the service
              self._settings_service.set_local_rag_source_enabled(path_str, is_checked)
         else:
              logger.warning("Local RAG item changed, but path data is missing.")

    @Slot()
    def _add_local_rag_directory(self):
        start_dir = str(self._settings_service.get_project_path() or Path.home())
        dir_path = QFileDialog.getExistingDirectory(self, "Select Local Directory", start_dir)
        if dir_path:
            self._settings_service.add_local_rag_source(dir_path)
            # List will repopulate via signal connection

    @Slot()
    def _add_local_rag_file(self):
        start_dir = str(self._settings_service.get_project_path() or Path.home())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Local File", start_dir)
        if file_path:
            self._settings_service.add_local_rag_source(file_path)
            # List will repopulate via signal connection

    @Slot()
    def _remove_selected_local_rag_source(self):
        """Removes selected items from the Local RAG list via SettingsService."""
        selected_items = self.rag_local_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Select source(s) to remove.")
            return
        reply = QMessageBox.question(self, 'Confirm Removal', f"Remove {len(selected_items)} selected source(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            paths_to_remove = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole)]
            for path_str in paths_to_remove:
                 self._settings_service.remove_local_rag_source(path_str)
            # List will repopulate via signal connection


    # --- Dialog Acceptance (Save Settings) ---
    @Slot()
    def _on_accept(self):
        """Gathers all settings from UI widgets and saves them via SettingsService."""
        logger.info("SettingsDialog: OK clicked. Saving settings via SettingsService...")
        s = self._settings_service # Shortcut

        try:
            # Use a mapping for simpler setting updates
            widget_to_setting_map = {
                # LLM
                self.llm_provider_select: 'provider',
                self.llm_model_select: 'model', # Save currently selected text
                self.llm_api_key_input: 'api_key',
                self.llm_temp_spin: 'temperature',
                self.llm_topk_spin: 'top_k',
                # Prompts
                self.system_prompt_input: 'system_prompt',
                self.main_prompt_template_input: 'main_prompt_template',
                self.summarizer_prompt_input: 'rag_summarizer_prompt_template',
                # RAG Local
                self.rag_local_enable_cb: 'rag_local_enabled',
                # RAG External
                self.rag_external_enable_cb: 'rag_external_enabled',
                self.rag_summarizer_enable_cb: 'rag_summarizer_enabled',
                self.rag_summarizer_provider_select: 'rag_summarizer_provider',
                self.rag_summarizer_model_select: 'rag_summarizer_model_name', # Save selected text
                self.rag_rank_model_select: 'rag_ranking_model_name',
                self.rag_rank_threshold_spin: 'rag_similarity_threshold',
                self.rag_source_google_cb: 'rag_google_enabled',
                self.rag_source_google_api_input: 'rag_google_api_key',
                self.rag_source_google_cse_input: 'rag_google_cse_id',
                self.rag_source_bing_cb: 'rag_bing_enabled',
                self.rag_source_bing_api_input: 'rag_bing_api_key',
                self.rag_source_stackexchange_cb: 'rag_stackexchange_enabled',
                self.rag_source_github_cb: 'rag_github_enabled',
                self.rag_source_arxiv_cb: 'rag_arxiv_enabled',
                # Features
                self.feature_patch_cb: 'patch_mode',
                self.feature_whole_diff_cb: 'whole_file',
                # Appearance
                self.appearance_font_combo: 'editor_font', # Read .currentFont().family()
                self.appearance_font_size_spin: 'editor_font_size',
                self.appearance_theme_combo: 'theme',
                self.appearance_style_combo: 'syntax_highlighting_style' # Read .currentText()
            }

            for widget, key in widget_to_setting_map.items():
                value = None
                if isinstance(widget, (QLineEdit, QTextEdit)): value = widget.toPlainText() if isinstance(widget, QTextEdit) else widget.text()
                elif isinstance(widget, QComboBox): value = widget.currentText()
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): value = widget.value()
                elif isinstance(widget, QCheckBox): value = widget.isChecked()
                elif isinstance(widget, QFontComboBox): value = widget.currentFont().family()

                # Skip saving models if placeholder text is selected
                if widget is self.llm_model_select and ('loading' in value or 'No models' in value or 'Error' in value):
                    logger.warning(f"Skipping save for LLM model due to placeholder value: '{value}'")
                    continue
                if widget is self.rag_summarizer_model_select and ('loading' in value or 'No models' in value or 'Error' in value):
                    logger.warning(f"Skipping save for Summarizer model due to placeholder value: '{value}'")
                    continue

                # Skip style if combo disabled (Pygments missing)
                if widget is self.appearance_style_combo and not widget.isEnabled():
                    logger.debug("Skipping save for syntax style as Pygments is not available.")
                    continue

                if value is not None:
                    s.set_setting(key, value)
                else:
                     logger.warning(f"Could not determine value for setting '{key}' from widget {widget.objectName()}")

            # RAG local sources are updated via itemChanged signal, no need to gather here

            # Trigger save in the service
            if s.save_settings():
                self.accept() # Close the dialog if save was successful
            else:
                # Show error if save failed (service should log details)
                QMessageBox.critical(self, "Error Saving Settings",
                                     "Failed to save settings to the project configuration file. Please check logs.")

        except Exception as e:
             logger.exception("Error gathering settings from dialog widgets:")
             QMessageBox.critical(self, "Error Saving Settings", f"An unexpected error occurred gathering settings:\n{e}")

    # --- Cleanup ---
    def closeEvent(self, event):
        """Ensure any running model refreshes are stopped."""
        logger.debug("SettingsDialog closeEvent: Stopping model refreshes...")
        # Ask the service to stop any active refreshes it might be running
        self._model_list_service.stop_all_refreshes()
        super().closeEvent(event)

