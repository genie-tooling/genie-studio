# pm/ui/config_dock.py
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLabel, QListWidget,
    QPushButton, QSizePolicy, QSpacerItem, QListWidgetItem, QMessageBox,
    QMainWindow, QListView # Import QListView
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QIcon
import qtawesome as qta
from loguru import logger
from typing import List, Dict, Optional, Any
from pathlib import Path

from .change_queue_widget import ChangeQueueWidget
# --- Import RAM estimation and psutil ---
from ..core.model_registry import estimate_ollama_ram
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil library not found. RAM usage warnings will be disabled. pip install psutil")
# ---------------------------------------

class ConfigDock(QDockWidget):
    """Dock widget for managing PROJECT-SPECIFIC settings and Change Queue."""
    provider_changed = pyqtSignal(str)
    model_changed = pyqtSignal(str)
    llm_params_changed = pyqtSignal()
    request_model_list_refresh = pyqtSignal(str)
    rag_toggle_changed = pyqtSignal(str, bool)
    selected_prompts_changed = pyqtSignal(list)
    request_prompt_new = pyqtSignal()
    request_prompt_edit = pyqtSignal(str)
    request_prompt_delete = pyqtSignal(list)

    def __init__(self, settings: dict, parent: QMainWindow):
        super().__init__("Project Configuration", parent)
        self._parent_main_window = parent
        self._all_prompts_cache: List[Dict] = []
        self.change_queue_widget: ChangeQueueWidget = None
        self._ram_warning_timer = QTimer(self); self._ram_warning_timer.setSingleShot(True); self._ram_warning_timer.setInterval(500) # Debounce timer for RAM check
        self._ram_warning_timer.timeout.connect(self._check_model_ram)
        self._current_selected_model_for_ram_check: Optional[str] = None # Store model being checked

        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        try:
            self._build_ui()
            # Populate controls is now called AFTER pyqtSignals are connected by MainWindow
            # self.populate_controls(settings) # <-- REMOVED from here
        except Exception as e:
            logger.exception("CRITICAL ERROR during ConfigDock UI construction!")
            error_label = QLabel(f"Error building Config Dock:\n{e}\n\nCheck logs."); error_label.setStyleSheet("color: red; padding: 10px;"); error_label.setWordWrap(True)
            self.setWidget(error_label)

    def _build_ui(self):
        container_widget = QWidget()
        # --- SET SIZE POLICY on container ---
        # Allow shrinking horizontally, prefer expanding vertically
        container_widget.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        # --- SET MINIMUM WIDTH on container ---
        container_widget.setMinimumWidth(150) # Set a reasonable minimum *here*
        logger.debug(f"ConfigDock: Set container minimumWidth to {container_widget.minimumWidth()}")
        # ------------------------------------

        main_layout = QVBoxLayout(container_widget)
        main_layout.setSpacing(10) # Main vertical spacing between groups

        # --- LLM Group ---
        llm_group = QGroupBox("LLM Selection & Parameters (Project)")
        llm_group.setCheckable(True)
        llm_group.setChecked(True)
        # --- SET VERTICAL POLICY (Optional but good practice) ---
        llm_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        # -----------------------------------------------------
        llm_content_widget = QWidget() # Widget inside groupbox for layout
        llm_form_layout = QFormLayout(llm_content_widget)
        llm_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        llm_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight) # Align labels right

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Ollama", "Gemini"])
        llm_form_layout.addRow("Provider:", self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_list_view = QListView(self.model_combo) # Custom view for width
        self.model_combo.setView(model_list_view)
        self.model_combo.view().setMinimumWidth(200) # Ensure dropdown list is wide enough
        llm_form_layout.addRow("Model:", self.model_combo)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0); self.temp_spin.setSingleStep(0.1); self.temp_spin.setDecimals(1)
        llm_form_layout.addRow("Temperature:", self.temp_spin)

        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(0, 200)
        llm_form_layout.addRow("Top-K:", self.topk_spin)

        self.ctx_display_label = QLabel("...")
        llm_form_layout.addRow("Max Context:", self.ctx_display_label)

        llm_layout = QVBoxLayout(llm_group) # Layout *for the QGroupBox*
        llm_layout.addWidget(llm_content_widget) # Add content widget to groupbox layout
        main_layout.addWidget(llm_group) # Add the LLM groupbox to the main dock layout

        # --- RAG Group ---
        rag_group = QGroupBox("RAG Source Enablement (Project)")
        rag_group.setCheckable(True)
        rag_group.setChecked(True)
        # --- SET VERTICAL POLICY ---
        rag_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        # ---------------------------
        self.rag_content_widget = QWidget() # Content widget for RAG checkboxes
        self.rag_content_widget.setObjectName("rag_content_widget")
        self.rag_layout = QVBoxLayout(self.rag_content_widget) # Layout for RAG checkboxes
        self.rag_layout.setContentsMargins(5, 5, 5, 5)
        self.rag_layout.setSpacing(5)
        self.rag_checkboxes: Dict[str, QCheckBox] = {} # Store checkboxes for later population

        rag_outer_layout = QVBoxLayout(rag_group) # Layout *for the QGroupBox*
        rag_outer_layout.addWidget(self.rag_content_widget) # Add content widget to groupbox
        main_layout.addWidget(rag_group) # Add RAG groupbox to main dock layout

        # --- Prompt Group ---
        prompt_group = QGroupBox("System Prompts (Project)")
        prompt_group.setCheckable(True)
        prompt_group.setChecked(True)
        # --- SET VERTICAL POLICY ---
        prompt_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        # ---------------------------
        prompt_content_widget = QWidget() # Holds the available/selected lists and buttons
        prompt_main_layout = QHBoxLayout(prompt_content_widget) # Horizontal layout for lists/buttons

        # Available Prompts Section
        available_layout = QVBoxLayout()
        available_layout.addWidget(QLabel("Available:"))
        self.available_prompts_list = QListWidget()
        self.available_prompts_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        available_layout.addWidget(self.available_prompts_list)
        prompt_main_layout.addLayout(available_layout)

        # Add/Remove Buttons Section
        add_remove_layout = QVBoxLayout()
        add_remove_layout.addStretch()
        self.add_prompt_button = QPushButton(">")
        self.add_prompt_button.setToolTip("Add selected to active")
        self.add_prompt_button.setFixedWidth(30)
        self.remove_prompt_button = QPushButton("<")
        self.remove_prompt_button.setToolTip("Remove selected from active")
        self.remove_prompt_button.setFixedWidth(30)
        add_remove_layout.addWidget(self.add_prompt_button)
        add_remove_layout.addWidget(self.remove_prompt_button)
        add_remove_layout.addStretch()
        prompt_main_layout.addLayout(add_remove_layout)

        # Selected Prompts Section
        selected_layout = QVBoxLayout()
        selected_layout.addWidget(QLabel("Active (Order Matters):"))
        self.selected_prompts_list = QListWidget()
        self.selected_prompts_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        selected_layout.addWidget(self.selected_prompts_list)
        selected_actions_layout = QHBoxLayout() # For Up/Down buttons

        # Move Up/Down Buttons
        try: self.move_up_button = QPushButton(qta.icon('fa5s.arrow-up', color='gray', color_disabled='dimgray'), "")
        except Exception as e: logger.error(f"Icon err: {e}"); self.move_up_button = QPushButton("Up")
        self.move_up_button.setToolTip("Move selected up")
        self.move_up_button.setFixedWidth(30) # Match add/remove width

        try: self.move_down_button = QPushButton(qta.icon('fa5s.arrow-down', color='gray', color_disabled='dimgray'), "")
        except Exception as e: logger.error(f"Icon err: {e}"); self.move_down_button = QPushButton("Dn")
        self.move_down_button.setToolTip("Move selected down")
        self.move_down_button.setFixedWidth(30) # Match add/remove width

        selected_actions_layout.addStretch() # Push buttons right
        selected_actions_layout.addWidget(self.move_up_button)
        selected_actions_layout.addWidget(self.move_down_button)
        selected_layout.addLayout(selected_actions_layout)
        prompt_main_layout.addLayout(selected_layout)

        # Prompt Management Buttons (New/Edit/Delete)
        self.prompt_management_widget = QWidget() # Separate widget for these buttons
        prompt_management_layout = QHBoxLayout(self.prompt_management_widget)
        prompt_management_layout.setContentsMargins(0, 5, 0, 0) # Top margin
        prompt_management_layout.setSpacing(5)

        try: self.new_prompt_button = QPushButton(qta.icon('fa5s.plus-circle', color='#4CAF50'), " New")
        except Exception as e: logger.error(f"Icon err: {e}"); self.new_prompt_button = QPushButton("New Prompt")
        try: self.edit_prompt_button = QPushButton(qta.icon('fa5s.edit', color='#2196F3'), " Edit")
        except Exception as e: logger.error(f"Icon err: {e}"); self.edit_prompt_button = QPushButton("Edit Prompt")
        try: self.delete_prompt_button = QPushButton(qta.icon('fa5s.trash-alt', color='#f44336'), " Delete")
        except Exception as e: logger.error(f"Icon err: {e}"); self.delete_prompt_button = QPushButton("Delete Prompt")

        prompt_management_layout.addWidget(self.new_prompt_button)
        prompt_management_layout.addWidget(self.edit_prompt_button)
        prompt_management_layout.addStretch() # Push delete button right
        prompt_management_layout.addWidget(self.delete_prompt_button)

        prompt_outer_layout = QVBoxLayout(prompt_group) # Layout *for the QGroupBox*
        prompt_outer_layout.addWidget(prompt_content_widget) # Add lists/buttons widget
        prompt_outer_layout.addWidget(self.prompt_management_widget) # Add management buttons below
        main_layout.addWidget(prompt_group) # Add Prompt groupbox to main dock layout

        # --- Change Queue Group ---
        change_queue_group = QGroupBox("Pending File Changes")
        change_queue_group.setCheckable(False) # Not checkable
        # --- SET VERTICAL POLICY ---
        # Let this expand more readily vertically if needed
        change_queue_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        # ---------------------------
        change_queue_layout = QVBoxLayout(change_queue_group) # Layout *for the QGroupBox*
        self.change_queue_widget = ChangeQueueWidget() # Create the queue widget
        change_queue_layout.addWidget(self.change_queue_widget) # Add queue widget to groupbox
        main_layout.addWidget(change_queue_group, 1) # Add Change Queue groupbox, give vertical stretch

        # --- Finalize ---
        container_widget.setLayout(main_layout)
        self.setWidget(container_widget)

        # --- Connect Internal pyqtSignals ---
        # Group toggles
        llm_group.toggled.connect(llm_content_widget.setVisible)
        rag_group.toggled.connect(self.rag_content_widget.setVisible)
        prompt_group.toggled.connect(prompt_content_widget.setVisible)
        prompt_group.toggled.connect(self.prompt_management_widget.setVisible)

        # LLM Parameters
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.temp_spin.valueChanged.connect(self._on_llm_params_changed)
        self.topk_spin.valueChanged.connect(self._on_llm_params_changed)

        # Prompt List Management
        self.add_prompt_button.clicked.connect(self._on_add_prompt)
        self.remove_prompt_button.clicked.connect(self._on_remove_prompt)
        self.move_up_button.clicked.connect(self._on_move_up)
        self.move_down_button.clicked.connect(self._on_move_down)
        self.selected_prompts_list.itemSelectionChanged.connect(self._emit_selected_prompts_changed)
        self.selected_prompts_list.model().rowsMoved.connect(self._emit_selected_prompts_changed) # When items dragged
        self.available_prompts_list.itemDoubleClicked.connect(self._on_add_prompt)
        self.selected_prompts_list.itemDoubleClicked.connect(self._on_edit_selected_prompt) # Allow editing selected via double-click

        # Prompt New/Edit/Delete Buttons (Emit pyqtSignals to handler)
        self.new_prompt_button.clicked.connect(self.request_prompt_new.emit)
        self.edit_prompt_button.clicked.connect(self._on_edit_prompt_clicked)
        self.delete_prompt_button.clicked.connect(self._on_delete_prompt_clicked)

        # RAG checkboxes are connected dynamically in populate_controls

        logger.debug("ConfigDock UI built and internal pyqtSignals connected.")

    # --- Internal pyqtSlots ---
    @pyqtSlot(str)
    def _on_provider_changed(self, provider: str):
        logger.debug(f"ConfigDock: Provider changed to {provider}")
        self.provider_changed.emit(provider)
        # Let MainWindow handle the refresh request based on settings change
        # self.request_model_list_refresh.emit(provider)
        self._ram_warning_timer.stop() # Stop any pending RAM check if provider changes

    @pyqtSlot(str)
    def _on_model_changed(self, model: str):
        if model and 'loading' not in model and 'No models' not in model and 'Error' not in model:
            logger.debug(f"ConfigDock: Model changed to {model}")
            self.model_changed.emit(model)
            # --- Trigger RAM Check Timer ---
            provider = self.provider_combo.currentText()
            if provider.lower() == 'ollama':
                 self._current_selected_model_for_ram_check = model
                 self._ram_warning_timer.start() # Start/restart the debounce timer
            # -----------------------------
        else:
            logger.debug(f"ConfigDock: Model changed to placeholder '{model}', not emitting pyqtSignal.")
            self._ram_warning_timer.stop() # Stop timer if model is invalid

    # --- RAM Check ---
    @pyqtSlot()
    def _check_model_ram(self):
        model_to_check = self._current_selected_model_for_ram_check
        if not model_to_check or not HAS_PSUTIL:
            logger.trace("RAM check skipped (no model or psutil missing).")
            return

        logger.debug(f"Performing RAM check for Ollama model: {model_to_check}")
        estimated_gb = estimate_ollama_ram(model_to_check)
        if estimated_gb is None:
            logger.warning(f"Could not estimate RAM for {model_to_check}.")
            return

        try:
            system_ram_bytes = psutil.virtual_memory().total
            system_ram_gb = system_ram_bytes / (1024**3)
            threshold = 0.80 # Warn if estimated RAM > 80% of total system RAM

            logger.debug(f"System RAM: {system_ram_gb:.2f} GB. Estimated for model: {estimated_gb:.2f} GB.")

            if estimated_gb > (system_ram_gb * threshold):
                warning_msg = (f"""
Warning: Model '{model_to_check}' potentially requires ~{estimated_gb:.1f} GB RAM.
Your system has {system_ram_gb:.1f} GB total RAM.
Running this model may lead to slow performance or system instability.
                """)
                logger.warning(f"RAM Warning Triggered: {warning_msg}")
                QMessageBox.warning(self, "Potential High RAM Usage", warning_msg) # Removed title duplication
        except Exception as e:
             logger.error(f"Error during RAM check: {e}")
    # --- END RAM Check ---

    @pyqtSlot()
    def _on_llm_params_changed(self): self.llm_params_changed.emit()
    @pyqtSlot(str, bool)
    def _on_rag_toggled(self, key: str, is_checked: bool): self.rag_toggle_changed.emit(key, is_checked)
    @pyqtSlot()
    def _on_add_prompt(self):
        items = self.available_prompts_list.selectedItems();
        current_ids = {self.selected_prompts_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.selected_prompts_list.count())}; added = False
        for item in items:
            id = item.data(Qt.ItemDataRole.UserRole)
            if id not in current_ids:
                new_item = QListWidgetItem(item.text()); new_item.setData(Qt.ItemDataRole.UserRole, id); self.selected_prompts_list.addItem(new_item); added = True
        if added: self._emit_selected_prompts_changed()
    @pyqtSlot()
    def _on_remove_prompt(self):
        items = self.selected_prompts_list.selectedItems();
        if not items: return
        for item in reversed(items): self.selected_prompts_list.takeItem(self.selected_prompts_list.row(item))
        self._emit_selected_prompts_changed()
    @pyqtSlot()
    def _on_move_up(self):
        row = self.selected_prompts_list.currentRow();
        if row > 0: item = self.selected_prompts_list.takeItem(row); self.selected_prompts_list.insertItem(row - 1, item); self.selected_prompts_list.setCurrentRow(row - 1); self._emit_selected_prompts_changed()
    @pyqtSlot()
    def _on_move_down(self):
        row = self.selected_prompts_list.currentRow();
        if 0 <= row < self.selected_prompts_list.count() - 1: item = self.selected_prompts_list.takeItem(row); self.selected_prompts_list.insertItem(row + 1, item); self.selected_prompts_list.setCurrentRow(row + 1); self._emit_selected_prompts_changed()
    @pyqtSlot()
    def _emit_selected_prompts_changed(self):
        ids = [self.selected_prompts_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.selected_prompts_list.count())]; logger.debug(f"Selected prompts changed: {ids}"); self.selected_prompts_changed.emit(ids)
    # @pyqtSlot() # No longer needed, directly emitted
    # def _on_new_prompt_clicked(self): self.request_prompt_new.emit()
    @pyqtSlot()
    def _on_edit_prompt_clicked(self):
        avail = self.available_prompts_list.selectedItems(); sel = self.selected_prompts_list.selectedItems(); item = None
        if len(avail) == 1 and len(sel) == 0: item = avail[0]
        elif len(sel) == 1 and len(avail) == 0: item = sel[0]
        elif len(avail) + len(sel) > 1: QMessageBox.warning(self, "Edit Prompt", "Select only one prompt."); return
        else: QMessageBox.warning(self, "Edit Prompt", "Select a prompt to edit."); return
        if item: id = item.data(Qt.ItemDataRole.UserRole); logger.debug(f"Edit prompt clicked for {id}"); self.request_prompt_edit.emit(id)
    @pyqtSlot(QListWidgetItem)
    def _on_edit_selected_prompt(self, item: QListWidgetItem):
        if item: id = item.data(Qt.ItemDataRole.UserRole); logger.debug(f"Double-click edit for {id}."); self.request_prompt_edit.emit(id)
    @pyqtSlot()
    def _on_delete_prompt_clicked(self):
        # Delete is safer from available list
        items = self.available_prompts_list.selectedItems();
        if not items: QMessageBox.warning(self, "Delete Prompt", "Select prompt(s) from 'Available' list to delete."); return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in items];
        names = [item.text() for item in items] # Get names for confirmation
        reply = QMessageBox.warning(self, "Confirm Delete", f"Permanently delete {len(ids)} prompt(s)?\n- {chr(10).join(names)}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes: logger.debug(f"Delete confirmed for {ids}"); self.request_prompt_delete.emit(ids)

    # --- Public Methods ---
    @pyqtSlot(dict)
    def populate_controls(self, settings: dict):
        logger.debug("ConfigDock: Populating controls...")
        self.provider_combo.blockSignals(True); self.model_combo.blockSignals(True); self.temp_spin.blockSignals(True); self.topk_spin.blockSignals(True)

        # Safely clear RAG checkboxes
        self.rag_checkboxes.clear()
        # Clear the layout of the intermediate widget
        rag_layout = self.rag_content_widget.layout()
        if rag_layout:
            while rag_layout.count():
                item = rag_layout.takeAt(0)
                widget_item = item.widget() # Get widget safely
                if widget_item:
                    widget_item.deleteLater()
        else:
            logger.error("ConfigDock: Cannot find RAG content widget layout to clear checkboxes.")

        try:
            self.provider_combo.setCurrentText(settings.get('provider', 'Ollama'));
            self.temp_spin.setValue(float(settings.get('temperature', 0.3)));
            self.topk_spin.setValue(int(settings.get('top_k', 40)))

            rag_map = {
                'rag_local_enabled': "Local Files Context",
                'rag_external_enabled': "Enable External Search",
                'rag_stackexchange_enabled': "Stack Exchange",
                'rag_github_enabled': "GitHub",
                'rag_arxiv_enabled': "ArXiv",
                'rag_google_enabled': "Google (Web)",
                'rag_bing_enabled': "Bing (Web)",
            }
            if rag_layout: # Check layout exists before adding
                for key, name in rag_map.items():
                    if key in settings:
                        checkbox = QCheckBox(name);
                        checkbox.setChecked(settings.get(key, False));
                        rag_layout.addWidget(checkbox);
                        self.rag_checkboxes[key] = checkbox;
                        checkbox.toggled.connect(lambda checked, k=key: self._on_rag_toggled(k, checked));
                        logger.trace(f"  + Recreated RAG cb '{key}', Checked: {checkbox.isChecked()}")
                    else:
                        logger.warning(f"  - Skipping RAG cb '{key}', not in effective settings.")
            else:
                 logger.error("Cannot recreate RAG checkboxes, container layout missing.")

            # Prompts are handled by PromptActionHandler via pyqtSignals
            # all_prompts = settings.get('user_prompts', []);
            # selected_ids = settings.get('selected_prompt_ids', [])
            # self.populate_available_prompts(all_prompts);
            # self.populate_selected_prompts(selected_ids, all_prompts)

        except Exception as e:
            logger.exception(f"Error populating controls: {e}")
        finally:
            self.provider_combo.blockSignals(False); self.model_combo.blockSignals(False); self.temp_spin.blockSignals(False); self.topk_spin.blockSignals(False)

    # <<< MODIFIED update_model_list >>>
    @pyqtSlot(list, str)
    def update_model_list(self, models: list, current_model: str):
        logger.debug(f"ConfigDock: Updating model list. Found {len(models)} models. Current: '{current_model}'")
        # --- BLOCK pyqtSignalS ---
        self.model_combo.blockSignals(True)
        # --------------------
        self.model_combo.clear()
        self.model_combo.setEnabled(False) # Keep disabled until populated

        newly_selected_model = None # Track if we change the selection

        if models:
            self.model_combo.addItems(models)
            idx = self.model_combo.findText(current_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
                logger.debug(f"  Restored selection: {current_model}")
                newly_selected_model = current_model # Keep track
            elif models:
                 # Default to first model if current_model not found or empty
                 self.model_combo.setCurrentIndex(0)
                 newly_selected_model = self.model_combo.currentText()
                 logger.warning(f"  Current model '{current_model}' not found or invalid. Set selection to first: {newly_selected_model}")
                 # NOTE: We don't emit the model_changed pyqtSignal here directly.
                 # MainWindow._handle_setting_change_for_dock initiated this,
                 # and SettingsService already has the *intended* model.
                 # We rely on the SettingsService state being the source of truth.
            self.model_combo.setEnabled(True) # Enable after populating
        else:
            self.model_combo.addItem("No models found") # Keep disabled if no models

        # --- UNBLOCK pyqtSignalS ---
        self.model_combo.blockSignals(False)
        # ----------------------

        # Trigger RAM check for the newly selected/defaulted model if Ollama
        # This check should happen AFTER pyqtSignals are unblocked, using the final selected model
        if self.provider_combo.currentText().lower() == 'ollama':
            final_selected_model = self.model_combo.currentText() # Get the actual text after population
            if final_selected_model and 'loading' not in final_selected_model and 'No models' not in final_selected_model:
                self._current_selected_model_for_ram_check = final_selected_model
                self._ram_warning_timer.start()
            else:
                self._ram_warning_timer.stop() # Stop timer if model is invalid
    # <<< END MODIFIED update_model_list >>>

    @pyqtSlot(int)
    def update_context_limit_display(self, limit: int):
        display = f"{limit:,} tokens" if limit > 0 else "N/A"; self.ctx_display_label.setText(display)
        logger.debug(f"ConfigDock: Set ctx_display_label to '{display}'")

    # --- Prompt list population remains the same ---
    def populate_available_prompts(self, all_prompts_data: List[Dict]):
        self.available_prompts_list.blockSignals(True); self.available_prompts_list.clear()
        self._all_prompts_cache = sorted(all_prompts_data, key=lambda p: p.get('name', ''))
        logger.debug(f"Populating available prompts: {len(self._all_prompts_cache)} items.")
        for p_data in self._all_prompts_cache:
            id = p_data.get('id');
            if not id: logger.warning(f"Skip prompt missing ID: {p_data.get('name', 'Unnamed')}"); continue
            item = QListWidgetItem(p_data.get('name', 'Unnamed Prompt')); item.setData(Qt.ItemDataRole.UserRole, id); item.setToolTip(p_data.get('content', '')[:100] + "..."); self.available_prompts_list.addItem(item)
        self.available_prompts_list.blockSignals(False)

    def populate_selected_prompts(self, selected_ids: List[str], all_prompts_data: List[Dict]):
        self.selected_prompts_list.blockSignals(True); self.selected_prompts_list.clear()
        logger.debug(f"Populating selected prompts: {selected_ids}")
        prompts_by_id = {p['id']: p for p in all_prompts_data if 'id' in p}
        for pid in selected_ids:
            p_data = prompts_by_id.get(pid)
            if p_data: item = QListWidgetItem(p_data.get('name', 'Unknown')); item.setData(Qt.ItemDataRole.UserRole, p_data.get('id')); item.setToolTip(p_data.get('content', '')[:100] + "..."); self.selected_prompts_list.addItem(item)
            else: logger.warning(f"Could not find prompt data for selected ID: {pid}")
        self.selected_prompts_list.blockSignals(False)
