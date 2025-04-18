from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
    QDialogButtonBox, QPushButton, QHBoxLayout, QLabel, QVBoxLayout,
    QCheckBox, QFontComboBox, QTabWidget, QWidget, QGroupBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QSizePolicy, QSpacerItem
)
# *** Import QObject, QThread ***
from PySide6.QtCore import Qt, Signal, QRunnable, QThreadPool, Slot, QObject, QThread, QTimer
from PySide6.QtGui import QFont
from pathlib import Path
from loguru import logger
import qtawesome as qta
from typing import List, Dict, Optional, Any
import re

# Import project specific info
from ..core.model_registry import list_models, list_ollama_models, resolve_context_limit
from ..core.project_config import AVAILABLE_RAG_MODELS, DEFAULT_CONFIG, DEFAULT_PROMPT_TEMPLATE, AVAILABLE_PYGMENTS_STYLES, DEFAULT_STYLE

# ==========================================================================
# Background Task for Refreshing Model Lists
# ==========================================================================
class ModelRefreshWorker(QObject):
    """Worker object to fetch models in a background thread."""
    # Signals to emit results
    llm_models_ready = Signal(list)
    summarizer_models_ready = Signal(list)
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, provider: str, api_key: Optional[str], target: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.target = target # 'llm' or 'summarizer'
        self._is_interrupted = False

    @Slot()
    def run(self):
        """Fetch the models."""
        logger.debug(f"ModelRefreshWorker ({self.target}): Starting run for provider '{self.provider}'.")
        models = []
        try:
            provider_lower = self.provider.lower() if self.provider else ''
            if provider_lower == 'gemini':
                models = list_models('gemini', api_key=self.api_key, force_no_cache=True)
            elif provider_lower == 'ollama':
                models = list_ollama_models(force_no_cache=True)
            else:
                logger.warning(f"ModelRefreshWorker ({self.target}): Unknown provider '{self.provider}'.")

            if self._is_interrupted:
                logger.info(f"ModelRefreshWorker ({self.target}): Interrupted during fetch.")
                self.finished.emit()
                return

            # Emit the correct signal based on target
            if self.target == 'llm':
                self.llm_models_ready.emit(models)
                logger.debug(f"ModelRefreshWorker ({self.target}): Emitted llm_models_ready ({len(models)}).")
            elif self.target == 'summarizer':
                self.summarizer_models_ready.emit(models)
                logger.debug(f"ModelRefreshWorker ({self.target}): Emitted summarizer_models_ready ({len(models)}).")

        except Exception as e:
            error_msg = f"Error fetching models for {self.provider} ({self.target}): {e}"
            logger.error(error_msg)
            if not self._is_interrupted:
                self.error_occurred.emit(error_msg)
        finally:
            # Optional: Signal completion if needed, but signals above cover results
            self.finished.emit()
            pass

    def request_interruption(self):
        self._is_interrupted = True


# ==========================================================================
# Settings Dialog Class
# ==========================================================================
class SettingsDialog(QDialog):
    # Remove old signals if they were defined here
    # llm_models_loaded = Signal(list)
    # summarizer_models_loaded = Signal(list)

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Application Settings')
        self.setMinimumSize(700, 650)
        self.settings = current_settings.copy()
        self.settings['rag_local_sources'] = [s.copy() for s in self.settings.get('rag_local_sources', [])]

        # --- Thread/Worker Management ---
        self.llm_refresh_thread: Optional[QThread] = None
        self.llm_refresh_worker: Optional[ModelRefreshWorker] = None
        self.summarizer_refresh_thread: Optional[QThread] = None
        self.summarizer_refresh_worker: Optional[ModelRefreshWorker] = None

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Create Tabs ---
        self._create_widgets()
        self.tab_widget.addTab(self._create_llm_tab(), "LLM")
        self.tab_widget.addTab(self._create_prompts_tab(), "Prompts")
        self.tab_widget.addTab(self._create_rag_tab(), "RAG")
        self.tab_widget.addTab(self._create_features_tab(), "Features")
        self.tab_widget.addTab(self._create_appearance_tab(), "Appearance")

        # --- Dialog Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        # Connect accepted/rejected BEFORE populating/refreshing
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self._on_reject) # Handle reject for cleanup
        main_layout.addWidget(button_box)

        # --- Connect Internal Signals & Populate ---
        self._connect_signals()
        self._populate_all_fields()

        # --- Initial Model Refresh ---
        # Trigger refresh *after* UI is built and populated
        QTimer.singleShot(0, self._refresh_llm_models)
        QTimer.singleShot(0, self._refresh_summarizer_models)

    def _cleanup_thread(self, thread_ref: str, worker_ref: str):
        """Safely requests stop and cleans up a worker/thread pair."""
        thread: Optional[QThread] = getattr(self, thread_ref, None)
        worker: Optional[ModelRefreshWorker] = getattr(self, worker_ref, None)

        if thread and thread.isRunning():
             logger.debug(f"SettingsDialog: Requesting stop for thread '{thread_ref}'...")
             if worker:
                 worker.request_interruption() # Ask worker to stop nicely
             thread.quit()
             if not thread.wait(1000): # Wait briefly
                 logger.warning(f"SettingsDialog: Thread '{thread_ref}' did not finish quitting gracefully. Terminating.")
                 thread.terminate()
                 thread.wait() # Wait after terminate
             else:
                 logger.debug(f"SettingsDialog: Thread '{thread_ref}' finished.")
        elif thread:
             logger.debug(f"SettingsDialog: Thread '{thread_ref}' already finished or not started.")

        # Clear references
        setattr(self, thread_ref, None)
        setattr(self, worker_ref, None)


    def closeEvent(self, event):
        """Ensure threads are cleaned up when dialog is closed."""
        logger.debug("SettingsDialog: Close event triggered, cleaning up threads.")
        self._cleanup_thread('llm_refresh_thread', 'llm_refresh_worker')
        self._cleanup_thread('summarizer_refresh_thread', 'summarizer_refresh_worker')
        super().closeEvent(event)

    def _on_reject(self):
         """Handle dialog rejection (cleanup)."""
         logger.debug("SettingsDialog: Rejected.")
         # Cleanup is handled by closeEvent now
         self.reject()

    @Slot(list)
    def _populate_summarizer_model_select(self, models: list):
        """Populates the Summarizer model combo box."""
        logger.info(f"SettingsDialog: Populating Summarizer models ({len(models)})")

        # Check if the widget still exists (dialog might have closed)
        if not hasattr(self, 'rag_summarizer_model_select') or not self.rag_summarizer_model_select:
             logger.warning("SettingsDialog: Summarizer populate slot called, but rag_summarizer_model_select widget no longer exists.")
             return

        combo = self.rag_summarizer_model_select
        combo.blockSignals(True)
        combo.clear()

        if models:
            combo.addItems(models)
            combo.setEnabled(True)
            # Restore previous selection if possible
            stored_model = self.settings.get('rag_summarizer_model_name', '')
            logger.debug(f"SettingsDialog: Restoring Summarizer model selection. Target: '{stored_model}'")
            if stored_model in models:
                combo.setCurrentText(stored_model)
            elif models: # If previous selection invalid, select the first one
                combo.setCurrentIndex(0)
            logger.debug(f"SettingsDialog: Summarizer combobox populated. Current: '{combo.currentText()}'")
        else:
            combo.addItem('No models found')
            combo.setEnabled(False)
            logger.warning("SettingsDialog: No models found for Summarizer dropdown.")

        combo.blockSignals(False)
    # --- Methods to start background tasks ---
    def _start_model_refresh(self, target: str):
        """Starts the background refresh for either LLM or Summarizer models."""
        if target == 'llm':
             provider = self.llm_provider_select.currentText()
             api_key = self.llm_api_key_input.text() if provider.lower() == 'gemini' else None
             combo = self.llm_model_select
             thread_ref = 'llm_refresh_thread'
             worker_ref = 'llm_refresh_worker'
             finished_slot = self._populate_llm_model_select
             error_slot = self._handle_refresh_error_llm
        elif target == 'summarizer':
             provider = self.rag_summarizer_provider_select.currentText()
             # Gemini API key is usually the same for summarization, but we don't pass it
             # to the worker here as the LLM worker handles Gemini key. Ollama needs no key.
             api_key = None
             combo = self.rag_summarizer_model_select
             thread_ref = 'summarizer_refresh_thread'
             worker_ref = 'summarizer_refresh_worker'
             # --- THIS LINE MUST NOW BE CORRECT ---
             finished_slot = self._populate_summarizer_model_select
             # ------------------------------------
             error_slot = self._handle_refresh_error_summarizer
        else:
             logger.error(f"SettingsDialog: Invalid target for _start_model_refresh: {target}")
             return

        # Cleanup previous thread/worker first
        self._cleanup_thread(thread_ref, worker_ref) # Cleanup previous first
        logger.info(f"SettingsDialog: Starting {target} model refresh for provider '{provider}'...")
        combo.clear(); combo.addItem('⏳ loading...'); combo.setEnabled(False)

        thread = QThread(self)
        worker = ModelRefreshWorker(provider, api_key, target)
        setattr(self, thread_ref, thread)
        setattr(self, worker_ref, worker)
        worker.moveToThread(thread)


        if target == 'llm': 
            worker.llm_models_ready.connect(finished_slot)
        elif target == 'summarizer': 
            worker.summarizer_models_ready.connect(finished_slot)
        worker.error_occurred.connect(error_slot)
        # *** Connect the worker's NEW finished signal to thread.quit ***
        worker.finished.connect(thread.quit)

        # Connect thread signals for lifecycle management
        thread.started.connect(worker.run)
        # *** These connections ensure cleanup happens *after* thread finishes ***
        worker.finished.connect(worker.deleteLater) # Schedule worker cleanup when it's done
        thread.finished.connect(thread.deleteLater) # Schedule thread cleanup when it finishes

        thread.start()
        logger.debug(f"SettingsDialog: Started background thread for {target} refresh.")
        
    @Slot(str)
    def _handle_refresh_error(self, target_combo: QComboBox, error_message: str):
        """Handles errors reported by the refresh worker."""
        logger.error(f"SettingsDialog: Received model refresh error: {error_message}")
        if hasattr(self, target_combo.objectName()) and target_combo: # Check widget exists
             target_combo.blockSignals(True)
             target_combo.clear()
             target_combo.addItem("Error loading models")
             target_combo.setEnabled(False)
             target_combo.blockSignals(False)
             # Optionally show a message box? Depends on how critical it is.
             # QMessageBox.warning(self, "Model Load Error", f"Could not load models:\n{error_message}")
        else:
             logger.error(f"SettingsDialog: Target combo for error message no longer exists.")


    @Slot(str)
    def _handle_refresh_error_llm(self, error_message: str):
        self._handle_refresh_error(self.llm_model_select, error_message)

    @Slot(str)
    def _handle_refresh_error_summarizer(self, error_message: str):
         self._handle_refresh_error(self.rag_summarizer_model_select, error_message)
         
    # ------------------------------------------
    # Widget Creation (Called from __init__)
    # ------------------------------------------
    def _create_widgets(self):
        """Creates all the input widgets for the dialog."""
        # --- LLM Tab Widgets ---
        self.llm_provider_select = QComboBox()
        self.llm_model_select = QComboBox()
        self.llm_api_key_input = QLineEdit()
        self.llm_api_key_label = QLabel('API Key (Gemini):') # Store label ref
        self.llm_temp_spin = QDoubleSpinBox()
        self.llm_topk_spin = QSpinBox()
        self.llm_ctx_limit_label = QLabel("...")

        # --- Prompts Tab Widgets ---
        self.system_prompt_input = QTextEdit()
        self.main_prompt_template_input = QTextEdit()
        self.summarizer_prompt_input = QTextEdit() # Moved here

        # --- RAG Tab Widgets ---
        # Local
        self.rag_local_enable_cb = QCheckBox("Enable Local RAG")
        self.rag_local_list_widget = QListWidget()
        self.rag_local_add_dir_btn = QPushButton(qta.icon('fa5s.folder-plus'), " Add Dir...")
        self.rag_local_add_file_btn = QPushButton(qta.icon('fa5s.file-medical'), " Add File...")
        self.rag_local_remove_btn = QPushButton(qta.icon('fa5s.trash-alt'), " Remove")
        # External Master
        self.rag_external_enable_cb = QCheckBox("Enable External RAG")
        # Summarizer
        self.rag_summarizer_enable_cb = QCheckBox("Enable Query Summarization")
        self.rag_summarizer_provider_select = QComboBox()
        self.rag_summarizer_model_select = QComboBox()
        self.rag_summarizer_refresh_btn = QPushButton(qta.icon('fa5s.sync-alt'), "")
        # Ranking
        self.rag_rank_model_select = QComboBox()
        self.rag_rank_threshold_spin = QDoubleSpinBox()
        # Sources
        self.rag_source_google_cb = QCheckBox("Google Search")
        self.rag_source_google_api_input = QLineEdit()
        self.rag_source_google_cse_input = QLineEdit()
        self.rag_source_bing_cb = QCheckBox("Bing Search")
        self.rag_source_bing_api_input = QLineEdit()
        self.rag_source_stackexchange_cb = QCheckBox("Stack Exchange")
        self.rag_source_github_cb = QCheckBox("GitHub")
        self.rag_source_arxiv_cb = QCheckBox("ArXiv")
        # Store references to config widgets for enable/disable
        self.google_config_widget = QWidget()
        self.bing_config_widget = QWidget()


        # --- Features Tab Widgets ---
        self.feature_patch_cb = QCheckBox("Enable Patch Mode")
        self.feature_whole_diff_cb = QCheckBox("Generate Whole-file Diffs")

        # --- Appearance Tab Widgets ---
        self.appearance_font_combo = QFontComboBox()
        self.appearance_font_size_spin = QSpinBox()
        self.appearance_theme_combo = QComboBox()
        # *** ADD SYNTAX STYLE COMBO ***
        self.appearance_style_combo = QComboBox()
    # ------------------------------------------
    # Tab Creation Methods (Use created widgets)
    # ------------------------------------------
    def _create_llm_tab(self) -> QWidget:
        tab = QWidget(); self.llm_form_layout = QFormLayout(tab)
        self.llm_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.llm_provider_select.addItems(['Ollama', 'Gemini']) # Consistent order
        self.llm_form_layout.addRow('Provider:', self.llm_provider_select)
        refresh_btn = QPushButton(qta.icon('fa5s.sync-alt'), ""); refresh_btn.setFixedWidth(35); refresh_btn.setToolTip("Refresh model list")
        model_row = QHBoxLayout(); model_row.addWidget(self.llm_model_select, 1); model_row.addWidget(refresh_btn)
        self.llm_form_layout.addRow('Model:', model_row)
        self.llm_api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.llm_form_layout.addRow(self.llm_api_key_label, self.llm_api_key_input)
        self.llm_temp_spin.setRange(0.0, 2.0); self.llm_temp_spin.setSingleStep(0.1); self.llm_temp_spin.setDecimals(1); self.llm_temp_spin.setToolTip("Controls randomness.")
        self.llm_form_layout.addRow('Temperature:', self.llm_temp_spin)
        self.llm_topk_spin.setRange(0, 200); self.llm_topk_spin.setToolTip("Consider top K tokens (0=disabled).")
        self.llm_form_layout.addRow('Top‑K:', self.llm_topk_spin)
        self.llm_form_layout.addRow("Max Context:", self.llm_ctx_limit_label)
        # Connect signals specific to this tab's widgets
        refresh_btn.clicked.connect(lambda: self._refresh_llm_models(force=True))
        return tab

    def _create_prompts_tab(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10) # Reduced spacing

        # --- System Prompt ---
        sys_group = QGroupBox("System Prompt")
        sys_layout = QVBoxLayout(sys_group)
        sys_layout.setContentsMargins(5, 5, 5, 5)
        self.system_prompt_input.setAcceptRichText(False); self.system_prompt_input.setMinimumHeight(80); self.system_prompt_input.setPlaceholderText("e.g., You are a helpful expert Python programmer...")
        sys_layout.addWidget(self.system_prompt_input)
        layout.addWidget(sys_group)

        # --- Main Prompt Template ---
        main_tmpl_group = QGroupBox("Main Prompt Template")
        main_tmpl_layout = QVBoxLayout(main_tmpl_group)
        main_tmpl_layout.setContentsMargins(5, 5, 5, 5)
        main_tmpl_layout.addWidget(QLabel("Variables: {system_prompt}, {chat_history}, {code_context}, {local_context}, {remote_context}, {user_query}"))
        self.main_prompt_template_input.setAcceptRichText(False); self.main_prompt_template_input.setMinimumHeight(150); self.main_prompt_template_input.setPlaceholderText(DEFAULT_PROMPT_TEMPLATE) # Show default as placeholder
        self.main_prompt_template_input.setFont(QFont("Monospace", 10)) # Use mono for templates
        main_tmpl_layout.addWidget(self.main_prompt_template_input)
        layout.addWidget(main_tmpl_group, 1) # Allow template box to stretch

        # --- Summarizer Prompt ---
        summ_group = QGroupBox("RAG Query Summarizer Prompt Template")
        summ_layout = QVBoxLayout(summ_group)
        summ_layout.setContentsMargins(5, 5, 5, 5)
        self.summarizer_prompt_input.setAcceptRichText(False); self.summarizer_prompt_input.setFixedHeight(80); self.summarizer_prompt_input.setPlaceholderText("e.g., Condense the following into a search query:\n{original_query}\nSearch Query:")
        summ_layout.addWidget(self.summarizer_prompt_input)
        layout.addWidget(summ_group)

        # layout.addStretch(1) # Removed stretch to let template expand
        return tab


    def _create_rag_tab(self) -> QWidget:
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setSpacing(10)

        # --- Local RAG Group ---
        lg = QGroupBox("Local Sources")
        ll = QVBoxLayout(lg)
        ll.addWidget(self.rag_local_enable_cb)
        ll.addWidget(self.rag_local_list_widget, 1) # Allow list to stretch
        lb = QHBoxLayout()
        lb.addWidget(self.rag_local_add_dir_btn)
        lb.addWidget(self.rag_local_add_file_btn)
        lb.addStretch(1)
        lb.addWidget(self.rag_local_remove_btn)
        ll.addLayout(lb)
        main_layout.addWidget(lg) # Add local group to main layout

        # --- External RAG Group (Main Container) ---
        eg = QGroupBox("External Sources (Web)")
        el = QVBoxLayout(eg) # Layout for the external sources group
        el.addWidget(self.rag_external_enable_cb) # Master enable checkbox

        # --- Summarizer Group (Inside External) ---
        # *** Assign to self.summarizer_group ***
        self.summarizer_group = QGroupBox("Query Summarization")
        # *** Use self.summarizer_group for layout ***
        sl = QFormLayout(self.summarizer_group)
        sl.addRow(self.rag_summarizer_enable_cb)
        self.rag_summarizer_provider_select.addItems(["Ollama", "Gemini"])
        sl.addRow("Provider:", self.rag_summarizer_provider_select)
        smr = QHBoxLayout()
        smr.addWidget(self.rag_summarizer_model_select, 1)
        self.rag_summarizer_refresh_btn.setFixedWidth(35)
        self.rag_summarizer_refresh_btn.setToolTip("Refresh model list")
        smr.addWidget(self.rag_summarizer_refresh_btn)
        sl.addRow("Model:", smr)
        # *** Add self.summarizer_group to the external layout ***
        el.addWidget(self.summarizer_group)

        # --- Ranking Group (Inside External) ---
        # *** Assign to self.ranking_group ***
        self.ranking_group = QGroupBox("Ranking")
        # *** Use self.ranking_group for layout ***
        rl = QFormLayout(self.ranking_group)
        self.rag_rank_model_select.addItems(AVAILABLE_RAG_MODELS)
        rl.addRow("Model:", self.rag_rank_model_select)
        self.rag_rank_threshold_spin.setRange(0.0, 1.0)
        self.rag_rank_threshold_spin.setSingleStep(0.05)
        self.rag_rank_threshold_spin.setDecimals(2)
        rl.addRow("Threshold:", self.rag_rank_threshold_spin)
        # *** Add self.ranking_group to the external layout ***
        el.addWidget(self.ranking_group)

        # --- Sources Config Group (Inside External) ---
        # *** Assign to self.sources_group ***
        self.sources_group = QGroupBox("Sources & Configuration")
        # *** Use self.sources_group for layout ***
        ssl = QFormLayout(self.sources_group)
        ssl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # Google config
        gcl = QFormLayout(self.google_config_widget)
        gcl.setContentsMargins(0, 0, 0, 0)
        self.rag_source_google_api_input.setPlaceholderText("API Key")
        self.rag_source_google_api_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.rag_source_google_cse_input.setPlaceholderText("CSE ID")
        gcl.addRow("API Key:", self.rag_source_google_api_input)
        gcl.addRow("CSE ID:", self.rag_source_google_cse_input)
        ssl.addRow(self.rag_source_google_cb, self.google_config_widget)
        # Bing config
        bcl = QFormLayout(self.bing_config_widget)
        bcl.setContentsMargins(0, 0, 0, 0)
        self.rag_source_bing_api_input.setPlaceholderText("Enter Bing API Key")
        self.rag_source_bing_api_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        bcl.addRow("API Key:", self.rag_source_bing_api_input)
        ssl.addRow(self.rag_source_bing_cb, self.bing_config_widget)
        # Other sources
        ssl.addRow(self.rag_source_stackexchange_cb, QLabel("<i>(Uses DDG/Bing)</i>"))
        ssl.addRow(self.rag_source_github_cb, QLabel("<i>(Uses DDG/Bing)</i>"))
        ssl.addRow(self.rag_source_arxiv_cb, QLabel("<i>(Uses API)</i>"))
        # *** Add self.sources_group to the external layout ***
        el.addWidget(self.sources_group)

        # Add the main external group box to the tab's main layout
        main_layout.addWidget(eg)
        main_layout.addStretch(1) # Add stretch at the end of the tab layout
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

        # *** POPULATE AND ADD STYLE COMBO ***
        self.appearance_style_combo.setToolTip("Select syntax highlighting style (requires Pygments)")
        if AVAILABLE_PYGMENTS_STYLES:
            self.appearance_style_combo.addItems(AVAILABLE_PYGMENTS_STYLES)
        else:
            self.appearance_style_combo.addItem("Pygments not found")
            self.appearance_style_combo.setEnabled(False)
        layout.addRow("Syntax Style:", self.appearance_style_combo)
        # *** END ADD STYLE COMBO ***

        return tab

    # ------------------------------------------
    # Signal Connections
    # ------------------------------------------
    def _connect_signals(self):
        """Connect signals for widgets created in _create_widgets."""
        # LLM Tab
        self.llm_provider_select.currentTextChanged.connect(self._provider_changed)
        self.llm_model_select.currentTextChanged.connect(self._update_context_limit_display)

        # RAG Tab - Local
        self.rag_local_add_dir_btn.clicked.connect(self._add_local_rag_directory)
        self.rag_local_add_file_btn.clicked.connect(self._add_local_rag_file)
        self.rag_local_remove_btn.clicked.connect(self._remove_selected_local_rag_source)
        self.rag_local_enable_cb.toggled.connect(self._toggle_local_rag_widgets)

        # RAG Tab - External
        self.rag_external_enable_cb.toggled.connect(self._toggle_external_rag_widgets)
        self.rag_summarizer_enable_cb.toggled.connect(self._toggle_summarizer_widgets)
        self.rag_summarizer_provider_select.currentTextChanged.connect(lambda: self._refresh_summarizer_models())
        self.rag_summarizer_refresh_btn.clicked.connect(lambda: self._refresh_summarizer_models(force=True))
        self.rag_source_google_cb.toggled.connect(lambda checked: self.google_config_widget.setEnabled(self.rag_external_enable_cb.isChecked() and checked))
        self.rag_source_bing_cb.toggled.connect(lambda checked: self.bing_config_widget.setEnabled(self.rag_external_enable_cb.isChecked() and checked))

        # Features Tab
        self.feature_patch_cb.toggled.connect(self.feature_whole_diff_cb.setEnabled)

    # ------------------------------------------
    # Helper Methods (Populate, Refresh, RAG List, Toggle State)
    # ------------------------------------------
    def _populate_all_fields(self):
        """Populates all widgets with values from self.settings."""
        s = self.settings
        # LLM
        self.llm_provider_select.setCurrentText(s.get('provider', 'Ollama'))
        self.llm_api_key_input.setText(s.get('api_key', ''))
        self.llm_temp_spin.setValue(float(s.get('temperature', 0.3)))
        self.llm_topk_spin.setValue(int(s.get('top_k', 40)))
        # Prompts
        self.main_prompt_template_input.setPlainText(s.get('main_prompt_template', DEFAULT_CONFIG['main_prompt_template'])) # <<< ADDED
        self.system_prompt_input.setPlainText(s.get('system_prompt', DEFAULT_CONFIG['system_prompt']))
        self.summarizer_prompt_input.setPlainText(s.get('rag_summarizer_prompt_template', DEFAULT_CONFIG['rag_summarizer_prompt_template']))
        # RAG - Local
        self.rag_local_enable_cb.setChecked(s.get('rag_local_enabled', False))
        self._populate_local_rag_list()
        # RAG - External
        self.rag_external_enable_cb.setChecked(s.get('rag_external_enabled', True))
        self.rag_summarizer_enable_cb.setChecked(s.get('rag_summarizer_enabled', True))
        self.rag_summarizer_provider_select.setCurrentText(s.get('rag_summarizer_provider', 'Ollama'))
        self.rag_rank_model_select.setCurrentText(s.get('rag_ranking_model_name', AVAILABLE_RAG_MODELS[0]))
        self.rag_rank_threshold_spin.setValue(float(s.get('rag_similarity_threshold', 0.30)))
        self.rag_source_google_cb.setChecked(s.get('rag_google_enabled', False)); self.rag_source_google_api_input.setText(s.get('rag_google_api_key', '')); self.rag_source_google_cse_input.setText(s.get('rag_google_cse_id', ''))
        self.rag_source_bing_cb.setChecked(s.get('rag_bing_enabled', True)); self.rag_source_bing_api_input.setText(s.get('rag_bing_api_key', ''))
        self.rag_source_stackexchange_cb.setChecked(s.get('rag_stackexchange_enabled', True))
        self.rag_source_github_cb.setChecked(s.get('rag_github_enabled', True))
        self.rag_source_arxiv_cb.setChecked(s.get('rag_arxiv_enabled', False))
        # Features
        self.feature_patch_cb.setChecked(s.get('patch_mode', True))
        self.feature_whole_diff_cb.setChecked(s.get('whole_file', True))
        # Appearance
        try: self.appearance_font_combo.setCurrentFont(QFont(s.get('editor_font', 'Fira Code')))
        except: self.appearance_font_combo.setCurrentFont(QFont("Monospace"))
        self.appearance_font_size_spin.setValue(int(s.get('editor_font_size', 11)))
        self.appearance_theme_combo.setCurrentText(s.get('theme', 'Dark'))
        # *** POPULATE STYLE COMBO ***
        current_style = s.get('syntax_highlighting_style', DEFAULT_STYLE)
        if current_style in AVAILABLE_PYGMENTS_STYLES:
            self.appearance_style_combo.setCurrentText(current_style)
        elif AVAILABLE_PYGMENTS_STYLES: # If style invalid but list exists, select default
             self.appearance_style_combo.setCurrentText(DEFAULT_STYLE)
        # *** END POPULATE STYLE ***
        # Initial UI states
        self._provider_changed(self.llm_provider_select.currentText())
        self._toggle_local_rag_widgets(self.rag_local_enable_cb.isChecked())
        self._toggle_external_rag_widgets(self.rag_external_enable_cb.isChecked())


    @Slot()
    def _refresh_llm_models(self, force=False): # force arg might not be needed now
        """Triggers the background LLM model list refresh using Worker/Thread."""
        self._start_model_refresh('llm')


    @Slot(list)
    def _populate_llm_model_select(self, models: list):
        logger.info(f"SettingsDialog: Populating LLM models ({len(models)})")
        # --- IMPORTANT: Check if the widget still exists ---
        # It's possible the dialog was closed *just* as the signal arrived
        if not hasattr(self, 'llm_model_select') or not self.llm_model_select:
             logger.warning("SettingsDialog: LLM populate slot called, but llm_model_select widget no longer exists.")
             return
        # (Rest of the population logic from previous answer - addItems, enable, restore selection)
        self.llm_model_select.blockSignals(True)
        self.llm_model_select.clear()
        if models:
            self.llm_model_select.addItems(models)
            self.llm_model_select.setEnabled(True)
            prev = self.settings.pop('_prev_llm_model', None)
            stored = self.settings.get('model', '')
            target = prev if prev in models else stored
            logger.debug(f"SettingsDialog: Restoring LLM model selection. Target: '{target}'")
            if target in models: self.llm_model_select.setCurrentText(target)
            elif models: self.llm_model_select.setCurrentIndex(0)
            logger.debug(f"SettingsDialog: LLM combobox populated. Current: '{self.llm_model_select.currentText()}'")
        else:
            self.llm_model_select.addItem('No models found')
            self.llm_model_select.setEnabled(False)
            logger.warning("SettingsDialog: No models found for LLM dropdown.")
        self.llm_model_select.blockSignals(False)
        self._update_context_limit_display()

    @Slot()
    def _refresh_summarizer_models(self, force=False):
        """Triggers the background Summarizer model list refresh using Worker/Thread."""
        self._start_model_refresh('summarizer')



    @Slot(list)
    def _populate_llm_model_select(self, models: list):
        logger.info(f"SettingsDialog: Populating LLM models ({len(models)})")
        # --- IMPORTANT: Check if the widget still exists ---
        # It's possible the dialog was closed *just* as the signal arrived
        if not hasattr(self, 'llm_model_select') or not self.llm_model_select:
             logger.warning("SettingsDialog: LLM populate slot called, but llm_model_select widget no longer exists.")
             return
        # (Rest of the population logic from previous answer - addItems, enable, restore selection)
        self.llm_model_select.blockSignals(True)
        self.llm_model_select.clear()
        if models:
            self.llm_model_select.addItems(models)
            self.llm_model_select.setEnabled(True)
            prev = self.settings.pop('_prev_llm_model', None)
            stored = self.settings.get('model', '')
            target = prev if prev in models else stored
            logger.debug(f"SettingsDialog: Restoring LLM model selection. Target: '{target}'")
            if target in models: self.llm_model_select.setCurrentText(target)
            elif models: self.llm_model_select.setCurrentIndex(0)
            logger.debug(f"SettingsDialog: LLM combobox populated. Current: '{self.llm_model_select.currentText()}'")
        else:
            self.llm_model_select.addItem('No models found')
            self.llm_model_select.setEnabled(False)
            logger.warning("SettingsDialog: No models found for LLM dropdown.")
        self.llm_model_select.blockSignals(False)
        self._update_context_limit_display()

    @Slot(str)
    def _provider_changed(self, provider_text: str):
        """Handles LLM provider selection change."""
        is_gemini = provider_text.lower() == 'gemini'
        self.llm_api_key_label.setVisible(is_gemini)
        self.llm_api_key_input.setVisible(is_gemini)
        self._refresh_llm_models() # Refresh models for the new provider
        self._update_context_limit_display() # Update context limit display

    @Slot()
    def _update_context_limit_display(self):
        """Updates the LLM context limit label."""
        provider = self.llm_provider_select.currentText(); model = self.llm_model_select.currentText()
        limit_text = "N/A"; limit_val = 0
        if model and 'loading' not in model and 'No models' not in model:
            try: limit_val = resolve_context_limit(provider, model); limit_text = f"{limit_val:,} tokens"
            except Exception as e: logger.error(f"Ctx limit failed {provider}/{model}: {e}"); limit_text = "Error"
        self.llm_ctx_limit_label.setText(limit_text)

    # --- Toggle Widget Enabled States ---
    @Slot(bool)
    def _toggle_local_rag_widgets(self, enabled: bool):
        self.rag_local_list_widget.setEnabled(enabled)
        self.rag_local_add_dir_btn.setEnabled(enabled)
        self.rag_local_add_file_btn.setEnabled(enabled)
        self.rag_local_remove_btn.setEnabled(enabled)

    @Slot(bool)
    def _toggle_external_rag_widgets(self, enabled: bool):
        # Enable/disable all groups within external RAG
        self.summarizer_group.setEnabled(enabled)
        self.ranking_group.setEnabled(enabled)
        self.sources_group.setEnabled(enabled) # Enable/disable the sources groupbox itself
        # Also re-evaluate individual toggles based on master switch
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
        # Only enable sub-widgets if master external switch is also checked
        is_enabled = enabled and self.rag_external_enable_cb.isChecked()
        self.rag_summarizer_provider_select.setEnabled(is_enabled)
        self.rag_summarizer_model_select.setEnabled(is_enabled)
        self.rag_summarizer_refresh_btn.setEnabled(is_enabled)
        self.summarizer_prompt_input.setEnabled(is_enabled) # Use correct var name

    # --- Local RAG List Management ---
    def _populate_local_rag_list(self): # ... (implementation unchanged) ...
        self.rag_local_list_widget.clear(); sources=self.settings.get('rag_local_sources',[]); logger.debug(f"Populate Local RAG list: {sources}"); [self._add_local_rag_item(s.get('path'), s.get('enabled', True)) for s in sources if s.get('path')]
    def _add_local_rag_item(self, p: str, en: bool = True): # ... (implementation unchanged) ...
        [logger.warning(f"Dup RAG src: {p}") for i in range(self.rag_local_list_widget.count()) if self.rag_local_list_widget.item(i).data(Qt.UserRole)==p] or (lambda i=QListWidgetItem(Path(p).name): [i.setToolTip(p), i.setData(Qt.UserRole, p), i.setFlags(i.flags() | Qt.ItemIsUserCheckable), i.setCheckState(Qt.Checked if en else Qt.Unchecked), self.rag_local_list_widget.addItem(i)])()
    def _add_local_rag_directory(self): d=QFileDialog.getExistingDirectory(self,"Select Local Dir","."); d and self._add_local_rag_item(d)
    def _add_local_rag_file(self): f,_=QFileDialog.getOpenFileName(self,"Select Local File","."); f and self._add_local_rag_item(f)
    # Replace the _remove_selected_local_rag_source method
    # inside the SettingsDialog class in pm/ui/settings_dialog.py

    def _remove_selected_local_rag_source(self):
        """Removes the currently selected item(s) from the Local RAG list."""
        selected_items = self.rag_local_list_widget.selectedItems()

        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a local RAG source from the list to remove.")
            return # Exit if nothing is selected

        # Optional: Confirm removal
        reply = QMessageBox.question(self, 'Confirm Removal',
                                     f"Remove {len(selected_items)} selected local RAG source(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) # Default to No
        if reply == QMessageBox.StandardButton.No:
            return

        # Use a standard for loop
        for item in selected_items:
            path_str = item.data(Qt.UserRole)
            row = self.rag_local_list_widget.row(item)
            removed_item = self.rag_local_list_widget.takeItem(row)
            if removed_item:
                logger.info(f"Removed local RAG source from settings UI: {path_str}")
            else:
                 logger.warning(f"Failed to remove item for path {path_str} at row {row}")
    # ------------------------------------------
    # Dialog Acceptance (Save Settings)
    # ------------------------------------------
# Place this method definition inside the SettingsDialog class
# in pm/ui/settings_dialog.py, replacing the previous version.

    @Slot() # Explicitly mark as a slot
    def _on_accept(self):
        """Gathers all settings from UI widgets, updates the internal
           settings dictionary, and accepts the dialog."""

        s = self.settings # Use a shortcut for clarity
        logger.info("Gathering settings from dialog widgets...")

        try:
            # --- LLM Tab ---
            s['provider'] = self.llm_provider_select.currentText()
            llm_model = self.llm_model_select.currentText()
            # Save model only if it's not a placeholder/error message
            if llm_model and 'loading' not in llm_model and 'No models' not in llm_model:
                s['model'] = llm_model
            else:
                # Keep previous value if selection is invalid
                logger.warning(f"Invalid LLM model selection '{llm_model}', keeping previous '{s.get('model','N/A')}'.")
                if 'model' not in s: s['model'] = "" # Ensure key exists if never set
            s['api_key'] = self.llm_api_key_input.text()
            s['temperature'] = self.llm_temp_spin.value()
            s['top_k'] = self.llm_topk_spin.value()
            # Context limit is resolved dynamically, not set here, but ensure it's recalculated on settings change
            # We can recalculate it here based on the selected model for consistency
            try:
                 s['context_limit'] = resolve_context_limit(s['provider'], s.get('model', ''))
            except Exception as e:
                 logger.error(f"Failed to resolve context limit on save for {s['provider']}/{s.get('model','')}: {e}")
                 s['context_limit'] = DEFAULT_CONFIG['context_limit'] # Fallback

            # --- Prompts Tab ---
            s['system_prompt'] = self.system_prompt_input.toPlainText()
            s['main_prompt_template'] = self.main_prompt_template_input.toPlainText()
            s['rag_summarizer_prompt_template'] = self.summarizer_prompt_input.toPlainText()

            # --- RAG Tab ---
            # Local RAG
            s['rag_local_enabled'] = self.rag_local_enable_cb.isChecked()
            local_sources_data = []
            for i in range(self.rag_local_list_widget.count()):
                item = self.rag_local_list_widget.item(i)
                path_str = item.data(Qt.UserRole)
                enabled = item.checkState() == Qt.CheckState.Checked # Use enum
                if path_str: # Ensure path exists
                    local_sources_data.append({'path': path_str, 'enabled': enabled})
            s['rag_local_sources'] = local_sources_data

            # External RAG Master Switch
            s['rag_external_enabled'] = self.rag_external_enable_cb.isChecked()

            # Summarizer
            s['rag_summarizer_enabled'] = self.rag_summarizer_enable_cb.isChecked()
            s['rag_summarizer_provider'] = self.rag_summarizer_provider_select.currentText()
            summ_model = self.rag_summarizer_model_select.currentText()
            if summ_model and 'loading' not in summ_model and 'No models' not in summ_model:
                 s['rag_summarizer_model_name'] = summ_model
            else:
                 logger.warning(f"Invalid Summarizer model selection '{summ_model}', keeping previous '{s.get('rag_summarizer_model_name','N/A')}'.")
                 if 'rag_summarizer_model_name' not in s: s['rag_summarizer_model_name'] = ""

            # Ranking
            s['rag_ranking_model_name'] = self.rag_rank_model_select.currentText()
            s['rag_similarity_threshold'] = self.rag_rank_threshold_spin.value()

            # Individual External Sources & Config
            s['rag_google_enabled'] = self.rag_source_google_cb.isChecked()
            s['rag_google_api_key'] = self.rag_source_google_api_input.text()
            s['rag_google_cse_id'] = self.rag_source_google_cse_input.text()
            s['rag_bing_enabled'] = self.rag_source_bing_cb.isChecked()
            s['rag_bing_api_key'] = self.rag_source_bing_api_input.text()
            s['rag_stackexchange_enabled'] = self.rag_source_stackexchange_cb.isChecked()
            s['rag_github_enabled'] = self.rag_source_github_cb.isChecked()
            s['rag_arxiv_enabled'] = self.rag_source_arxiv_cb.isChecked()

            # --- Features Tab ---
            s['patch_mode'] = self.feature_patch_cb.isChecked()
            s['whole_file'] = self.feature_whole_diff_cb.isChecked()

            # --- Appearance Tab ---
            s['editor_font'] = self.appearance_font_combo.currentFont().family()
            s['editor_font_size'] = self.appearance_font_size_spin.value()
            s['theme'] = self.appearance_theme_combo.currentText()
            # *** SAVE SELECTED STYLE ***
            if self.appearance_style_combo.isEnabled(): # Only save if pygments was found
                s['syntax_highlighting_style'] = self.appearance_style_combo.currentText()
            else: # If pygments wasn't found, keep the default
                s['syntax_highlighting_style'] = DEFAULT_STYLE

            if not s['main_prompt_template'].strip():
                logger.warning("Main prompt template cannot be empty. Restoring default.")
                s['main_prompt_template'] = DEFAULT_CONFIG['main_prompt_template']
                # Optionally inform user: QMessageBox.warning(...)
            # Basic check for essential placeholders (optional but recommended)
            required_placeholders = {'{user_query}'} # Must have at least the query
            missing = required_placeholders - set(re.findall(r"{\w+}", s['main_prompt_template']))
            if missing:
                 logger.warning(f"Main prompt template might be missing required placeholders: {missing}. Check template syntax.")
                 # Optionally: QMessageBox.warning(self, "Template Warning", f"Template might miss placeholders: {missing}")


            logger.info("Settings gathered successfully from UI.")
            self.accept() # Close the dialog and return Accepted status

        except Exception as e:
             # Catch any unexpected error during value gathering
             logger.exception("Error gathering settings from dialog widgets:")
             QMessageBox.critical(self, "Error Saving Settings", f"An unexpected error occurred while gathering settings:\n{e}")
             # Optionally, self.reject() here, or allow user to try again

