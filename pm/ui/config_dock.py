# pm/ui/config_dock.py
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLabel, QListWidget,
    QPushButton, QSizePolicy, QSpacerItem, QListWidgetItem, QMessageBox,
    QMainWindow # For type hinting parent
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIcon
import qtawesome as qta
from loguru import logger
from typing import List, Dict, Optional, Any

# --- Import Change Queue Widget ---
from .change_queue_widget import ChangeQueueWidget


class ConfigDock(QDockWidget):
    """
    Dock widget for managing PROJECT-SPECIFIC LLM/RAG/Prompt settings
    and the new Change Queue.
    Reads merged settings but primarily signals changes for project config.
    """
    # --- LLM Signals ---
    provider_changed = Signal(str)
    model_changed = Signal(str)
    llm_params_changed = Signal()
    request_model_list_refresh = Signal(str)

    # --- RAG Signals ---
    rag_toggle_changed = Signal(str, bool) # Signals enablement changes for THIS project

    # --- Prompt Signals ---
    selected_prompts_changed = Signal(list)
    request_prompt_new = Signal()
    request_prompt_edit = Signal(str)
    request_prompt_delete = Signal(list)

    def __init__(self, settings: dict, parent: QMainWindow):
        super().__init__("Project Configuration", parent) # Renamed title
        self._parent_main_window = parent
        self._all_prompts_cache: List[Dict] = []
        # --- Add reference for Change Queue ---
        self.change_queue_widget: ChangeQueueWidget = None

        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

        try:
            self._build_ui()
            # Populate controls using the effective settings for the current project
            self.populate_controls(settings)
        except Exception as e:
            logger.exception("CRITICAL ERROR during ConfigDock UI construction or initial population!")
            error_label = QLabel(f"Error building Config Dock:\n{e}\n\nCheck logs.")
            error_label.setStyleSheet("color: red; padding: 10px;")
            error_label.setWordWrap(True)
            self.setWidget(error_label)


    def _build_ui(self):
        """Constructs the UI elements within the dock."""
        container_widget = QWidget()
        main_layout = QVBoxLayout(container_widget)
        main_layout.setSpacing(10)

        # --- LLM Selection & Params Group (Project Specific Overrides) ---
        llm_group = QGroupBox("LLM Selection & Parameters (Project)")
        llm_group.setCheckable(True)
        llm_group.setChecked(True)
        llm_content_widget = QWidget()
        llm_form_layout = QFormLayout(llm_content_widget)
        llm_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Ollama", "Gemini"])
        llm_form_layout.addRow("Provider:", self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        llm_form_layout.addRow("Model:", self.model_combo)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(1)
        llm_form_layout.addRow("Temperature:", self.temp_spin)

        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(0, 200)
        llm_form_layout.addRow("Top-K:", self.topk_spin)

        self.ctx_display_label = QLabel("...")
        llm_form_layout.addRow("Max Context:", self.ctx_display_label)

        llm_layout = QVBoxLayout(llm_group)
        llm_layout.addWidget(llm_content_widget)
        main_layout.addWidget(llm_group)


        # --- RAG Sources Group (Project Specific Enablement) ---
        rag_group = QGroupBox("RAG Source Enablement (Project)")
        rag_group.setCheckable(True)
        rag_group.setChecked(True)
        rag_content_widget = QWidget()
        rag_content_widget.setObjectName("rag_content_widget") # Ensure name is set
        rag_layout = QVBoxLayout(rag_content_widget)
        self.rag_checkboxes: Dict[str, QCheckBox] = {}
        # Checkboxes created dynamically in populate_controls

        rag_outer_layout = QVBoxLayout(rag_group)
        rag_outer_layout.addWidget(rag_content_widget)
        main_layout.addWidget(rag_group)


        # --- Prompt Selection Group (Project Specific) ---
        prompt_group = QGroupBox("System Prompts (Project)")
        prompt_group.setCheckable(True)
        prompt_group.setChecked(True)

        prompt_content_widget = QWidget() # Container for the main lists/buttons HBox
        prompt_main_layout = QHBoxLayout(prompt_content_widget) # Main HBox for lists/buttons

        available_layout = QVBoxLayout()
        available_layout.addWidget(QLabel("Available:"))
        self.available_prompts_list = QListWidget()
        self.available_prompts_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        available_layout.addWidget(self.available_prompts_list)
        prompt_main_layout.addLayout(available_layout)

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

        selected_layout = QVBoxLayout()
        selected_layout.addWidget(QLabel("Active (Order Matters):"))
        self.selected_prompts_list = QListWidget()
        self.selected_prompts_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        selected_layout.addWidget(self.selected_prompts_list)

        selected_actions_layout = QHBoxLayout()
        try:
            self.move_up_button = QPushButton(qta.icon('fa5s.arrow-up', color='gray', color_disabled='dimgray'), "")
            self.move_up_button.setToolTip("Move selected up")
        except Exception as e:
            logger.error(f"Failed to load move_up icon: {e}")
            self.move_up_button = QPushButton("Up")
            self.move_up_button.setToolTip("Move selected up")
        try:
            self.move_down_button = QPushButton(qta.icon('fa5s.arrow-down', color='gray', color_disabled='dimgray'), "")
            self.move_down_button.setToolTip("Move selected down")
        except Exception as e:
            logger.error(f"Failed to load move_down icon: {e}")
            self.move_down_button = QPushButton("Dn")
            self.move_down_button.setToolTip("Move selected down")

        selected_actions_layout.addWidget(self.move_up_button)
        selected_actions_layout.addWidget(self.move_down_button)
        selected_actions_layout.addStretch()
        selected_layout.addLayout(selected_actions_layout)
        prompt_main_layout.addLayout(selected_layout)

        self.prompt_management_widget = QWidget()
        prompt_management_layout = QHBoxLayout(self.prompt_management_widget)
        prompt_management_layout.setContentsMargins(0, 5, 0, 0)
        try:
            self.new_prompt_button = QPushButton(qta.icon('fa5s.plus-circle', color='#4CAF50'), " New")
        except Exception as e:
            logger.error(f"Failed to load new_prompt icon: {e}")
            self.new_prompt_button = QPushButton("New Prompt")
        try:
            self.edit_prompt_button = QPushButton(qta.icon('fa5s.edit', color='#2196F3'), " Edit")
        except Exception as e:
            logger.error(f"Failed to load edit_prompt icon: {e}")
            self.edit_prompt_button = QPushButton("Edit Prompt")
        try:
            self.delete_prompt_button = QPushButton(qta.icon('fa5s.trash-alt', color='#f44336'), " Delete")
        except Exception as e:
            logger.error(f"Failed to load delete_prompt icon: {e}")
            self.delete_prompt_button = QPushButton("Delete Prompt")

        prompt_management_layout.addWidget(self.new_prompt_button)
        prompt_management_layout.addWidget(self.edit_prompt_button)
        prompt_management_layout.addStretch()
        prompt_management_layout.addWidget(self.delete_prompt_button)

        prompt_outer_layout = QVBoxLayout(prompt_group)
        prompt_outer_layout.addWidget(prompt_content_widget)
        prompt_outer_layout.addWidget(self.prompt_management_widget)
        main_layout.addWidget(prompt_group) # No stretch factor here
        # --- End Prompt Group Setup ---

        # --- ADD Change Queue Group ---
        change_queue_group = QGroupBox("Pending File Changes")
        change_queue_group.setCheckable(False) # Not checkable itself
        change_queue_layout = QVBoxLayout(change_queue_group)
        self.change_queue_widget = ChangeQueueWidget() # Instantiate the new widget
        change_queue_layout.addWidget(self.change_queue_widget)
        main_layout.addWidget(change_queue_group, 1) # Give it stretch factor 1
        # ------------------------------

        # main_layout.addStretch(1) # Remove/Reduce stretch if queue is at bottom
        container_widget.setLayout(main_layout)
        self.setWidget(container_widget)

        # --- Connect Internal Signals ---
        llm_group.toggled.connect(llm_content_widget.setVisible)
        rag_group.toggled.connect(rag_content_widget.setVisible)
        prompt_group.toggled.connect(prompt_content_widget.setVisible)
        prompt_group.toggled.connect(self.prompt_management_widget.setVisible)

        # LLM Controls
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.temp_spin.valueChanged.connect(self._on_llm_params_changed)
        self.topk_spin.valueChanged.connect(self._on_llm_params_changed)
        # RAG Checkboxes connected dynamically in populate_controls
        # Prompt List Buttons
        self.add_prompt_button.clicked.connect(self._on_add_prompt)
        self.remove_prompt_button.clicked.connect(self._on_remove_prompt)
        self.move_up_button.clicked.connect(self._on_move_up)
        self.move_down_button.clicked.connect(self._on_move_down)
        self.selected_prompts_list.itemSelectionChanged.connect(self._emit_selected_prompts_changed)
        # Prompt Management Buttons
        self.new_prompt_button.clicked.connect(self._on_new_prompt_clicked)
        self.edit_prompt_button.clicked.connect(self._on_edit_prompt_clicked)
        self.delete_prompt_button.clicked.connect(self._on_delete_prompt_clicked)
        # List Double Clicks
        self.available_prompts_list.itemDoubleClicked.connect(self._on_add_prompt)
        self.selected_prompts_list.itemDoubleClicked.connect(self._on_edit_selected_prompt)
        # Change Queue signals connected externally by handler


    # --- Internal Slots (Emit Public Signals) ---
    @Slot(str)
    def _on_provider_changed(self, provider: str):
        logger.debug(f"ConfigDock: Provider changed to {provider}")
        self.provider_changed.emit(provider)
        self.request_model_list_refresh.emit(provider)


    @Slot(str)
    def _on_model_changed(self, model: str):
        if model and 'loading' not in model and 'No models' not in model and 'Error' not in model:
            logger.debug(f"ConfigDock: Model changed to {model}")
            self.model_changed.emit(model)
        else:
            logger.debug(f"ConfigDock: Model changed to placeholder '{model}', not emitting signal.")


    @Slot()
    def _on_llm_params_changed(self):
        logger.debug("ConfigDock: LLM params changed (temp/topk)")
        self.llm_params_changed.emit()


    @Slot(str, bool)
    def _on_rag_toggled(self, key: str, is_checked: bool):
        logger.debug(f"ConfigDock: RAG toggle changed: {key} = {is_checked}")
        self.rag_toggle_changed.emit(key, is_checked)


    @Slot()
    def _on_add_prompt(self):
        selected_items = self.available_prompts_list.selectedItems()
        if not selected_items:
             return
        current_selected_ids = {self.selected_prompts_list.item(i).data(Qt.UserRole) for i in range(self.selected_prompts_list.count())}
        items_added = False
        for item in selected_items:
            prompt_id = item.data(Qt.UserRole)
            if prompt_id not in current_selected_ids:
                new_item = QListWidgetItem(item.text())
                new_item.setData(Qt.UserRole, prompt_id)
                self.selected_prompts_list.addItem(new_item)
                items_added = True
        if items_added:
             self._emit_selected_prompts_changed()


    @Slot()
    def _on_remove_prompt(self):
        selected_items = self.selected_prompts_list.selectedItems()
        if not selected_items:
             return
        for item in reversed(selected_items):
            self.selected_prompts_list.takeItem(self.selected_prompts_list.row(item))
        self._emit_selected_prompts_changed()


    @Slot()
    def _on_move_up(self):
        current_row = self.selected_prompts_list.currentRow()
        if current_row > 0:
            item = self.selected_prompts_list.takeItem(current_row)
            self.selected_prompts_list.insertItem(current_row - 1, item)
            self.selected_prompts_list.setCurrentRow(current_row - 1)
            self._emit_selected_prompts_changed()


    @Slot()
    def _on_move_down(self):
        current_row = self.selected_prompts_list.currentRow()
        if 0 <= current_row < self.selected_prompts_list.count() - 1:
            item = self.selected_prompts_list.takeItem(current_row)
            self.selected_prompts_list.insertItem(current_row + 1, item)
            self.selected_prompts_list.setCurrentRow(current_row + 1)
            self._emit_selected_prompts_changed()


    @Slot()
    def _emit_selected_prompts_changed(self):
        selected_ids = [self.selected_prompts_list.item(i).data(Qt.UserRole) for i in range(self.selected_prompts_list.count())]
        logger.debug(f"ConfigDock: Selected prompts changed: {selected_ids}")
        self.selected_prompts_changed.emit(selected_ids)


    @Slot()
    def _on_new_prompt_clicked(self):
        logger.debug("ConfigDock: 'New Prompt' clicked, emitting request.")
        self.request_prompt_new.emit()


    @Slot()
    def _on_edit_prompt_clicked(self):
        avail_sel = self.available_prompts_list.selectedItems()
        sel_sel = self.selected_prompts_list.selectedItems()
        item_to_edit = None
        if len(avail_sel) == 1 and len(sel_sel) == 0:
             item_to_edit = avail_sel[0]
        elif len(sel_sel) == 1 and len(avail_sel) == 0:
             item_to_edit = sel_sel[0]
        elif len(avail_sel) + len(sel_sel) > 1:
             QMessageBox.warning(self, "Edit Prompt", "Please select only one prompt to edit.")
             return
        else:
             QMessageBox.warning(self, "Edit Prompt", "Please select a prompt from either list to edit.")
             return

        if item_to_edit:
            prompt_id = item_to_edit.data(Qt.UserRole)
            logger.debug(f"ConfigDock: 'Edit Prompt' clicked for ID {prompt_id}, emitting request.")
            self.request_prompt_edit.emit(prompt_id)


    @Slot(QListWidgetItem)
    def _on_edit_selected_prompt(self, item: QListWidgetItem):
        if item:
             prompt_id = item.data(Qt.UserRole)
             logger.debug(f"ConfigDock: Double-click edit requested for ID {prompt_id}.")
             self.request_prompt_edit.emit(prompt_id)


    @Slot()
    def _on_delete_prompt_clicked(self):
        selected_to_delete = self.available_prompts_list.selectedItems()
        if not selected_to_delete:
             QMessageBox.warning(self, "Delete Prompt", "Select prompt(s) from 'Available' list to delete.")
             return
        ids_to_delete = [item.data(Qt.UserRole) for item in selected_to_delete]
        reply = QMessageBox.warning(self, "Confirm Delete", f"Permanently delete {len(ids_to_delete)} prompt(s)?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
             logger.debug(f"ConfigDock: Delete confirmed for IDs {ids_to_delete}, emitting.")
             self.request_prompt_delete.emit(ids_to_delete)


    # --- Public Methods (Called by MainWindow) ---
    def populate_controls(self, settings: dict):
        """Populates the dock's controls based on the effective project settings."""
        logger.debug("ConfigDock: Populating controls from effective project settings.")
        self.provider_combo.blockSignals(True)
        self.model_combo.blockSignals(True)
        self.temp_spin.blockSignals(True)
        self.topk_spin.blockSignals(True)

        # --- RAG Checkbox Handling ---
        for checkbox in self.rag_checkboxes.values():
             try:
                 checkbox.toggled.disconnect()
             except RuntimeError:
                 pass # Ignore if already disconnected
        self.rag_checkboxes.clear()

        rag_content_widget = self.findChild(QWidget, "rag_content_widget")
        if rag_content_widget and rag_content_widget.layout():
             layout = rag_content_widget.layout()
             # Clear previous widgets safely
             while layout.count():
                  item = layout.takeAt(0)
                  widget = item.widget()
                  if widget:
                      widget.deleteLater() # Delete the old checkbox widget
             logger.debug("ConfigDock: Cleared previous RAG checkboxes.")
        else:
             logger.error("ConfigDock: Could not find RAG content widget/layout to clear checkboxes.")

        try:
            # LLM Settings
            self.provider_combo.setCurrentText(settings.get('provider', 'Ollama'))
            self.temp_spin.setValue(float(settings.get('temperature', 0.3)))
            self.topk_spin.setValue(int(settings.get('top_k', 40)))

            # RAG Settings (Recreate checkboxes) - ONLY handles enablement state
            rag_key_map = { # Keys corresponding to boolean flags in project config
                'rag_local_enabled': "Local Files", 'rag_external_enabled': "Enable external RAG sources",
                'rag_stackexchange_enabled': "Stack Exchange", 'rag_github_enabled': "GitHub",
                'rag_arxiv_enabled': "ArXiv", 'rag_google_enabled': "Google", 'rag_bing_enabled': "Bing",
            }
            if rag_content_widget and rag_content_widget.layout():
                rag_layout = rag_content_widget.layout() # Use the existing layout
                for key, display_name in rag_key_map.items():
                    if key in settings: # Check if key exists in *effective* settings
                        checkbox = QCheckBox(display_name)
                        checkbox.setChecked(settings.get(key, False)) # Set based on project settings
                        rag_layout.addWidget(checkbox)
                        self.rag_checkboxes[key] = checkbox
                        # Use lambda to capture the key correctly for the slot
                        checkbox.toggled.connect(lambda checked, k=key: self._on_rag_toggled(k, checked))
                        logger.trace(f"  + Recreated RAG checkbox '{key}', Checked: {checkbox.isChecked()}")
                    else:
                        logger.warning(f"  - Skipping RAG checkbox '{key}', not found in effective settings.")
            else:
                logger.error("ConfigDock: Cannot recreate RAG checkboxes, container missing.")

            # Prompt Lists
            all_prompts = settings.get('prompts', [])
            selected_ids = settings.get('selected_prompt_ids', [])
            self.populate_available_prompts(all_prompts)
            self.populate_selected_prompts(selected_ids, all_prompts)

        except Exception as e:
            logger.exception(f"ConfigDock: Error populating controls: {e}")
        finally:
            self.provider_combo.blockSignals(False)
            self.model_combo.blockSignals(False)
            self.temp_spin.blockSignals(False)
            self.topk_spin.blockSignals(False)


    @Slot(list, str)
    def update_model_list(self, models: list, current_model: str):
        logger.debug(f"ConfigDock: Updating model list. Found {len(models)} models. Current selection: '{current_model}'")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.setEnabled(False)
        if models:
            self.model_combo.addItems(models)
            model_index = self.model_combo.findText(current_model)
            if model_index >= 0:
                self.model_combo.setCurrentIndex(model_index)
                logger.debug(f"  Restored selection: {current_model}")
            elif models:
                self.model_combo.setCurrentIndex(0)
                logger.debug(f"  Set selection to first model: {self.model_combo.currentText()}")
                if current_model and current_model != self.model_combo.currentText():
                     QTimer.singleShot(0, lambda: self._on_model_changed(self.model_combo.currentText()))
            self.model_combo.setEnabled(True)
        else:
            self.model_combo.addItem("No models found")
        self.model_combo.blockSignals(False)


    @Slot(int)
    def update_context_limit_display(self, limit: int):
        """Updates the context limit display label."""
        logger.debug(f"ConfigDock: Slot update_context_limit_display received limit={limit}")
        display_text = f"{limit:,} tokens" if limit > 0 else "N/A"
        self.ctx_display_label.setText(display_text)
        logger.debug(f"ConfigDock: Set ctx_display_label text to '{display_text}'")


    def populate_available_prompts(self, all_prompts_data: List[Dict]):
        self.available_prompts_list.blockSignals(True)
        self.available_prompts_list.clear()
        self._all_prompts_cache = sorted(all_prompts_data, key=lambda p: p.get('name', ''))
        logger.debug(f"ConfigDock: Populating available prompts list with {len(self._all_prompts_cache)} items.")
        for prompt_data in self._all_prompts_cache:
            prompt_id = prompt_data.get('id')
            if not prompt_id:
                 logger.warning(f"Skipping prompt with missing ID: {prompt_data.get('name', 'Unnamed')}")
                 continue
            item = QListWidgetItem(prompt_data.get('name', 'Unnamed Prompt'))
            item.setData(Qt.UserRole, prompt_id)
            item.setToolTip(prompt_data.get('content', '')[:100] + "...")
            self.available_prompts_list.addItem(item)
        self.available_prompts_list.blockSignals(False)


    def populate_selected_prompts(self, selected_ids: List[str], all_prompts_data: List[Dict]):
        self.selected_prompts_list.blockSignals(True)
        self.selected_prompts_list.clear()
        logger.debug(f"ConfigDock: Populating selected prompts list with IDs: {selected_ids}")
        prompts_by_id = {p['id']: p for p in all_prompts_data if 'id' in p}
        for prompt_id in selected_ids:
            prompt_data = prompts_by_id.get(prompt_id)
            if prompt_data:
                 item = QListWidgetItem(prompt_data.get('name', 'Unknown Prompt'))
                 item.setData(Qt.UserRole, prompt_data.get('id'))
                 item.setToolTip(prompt_data.get('content', '')[:100] + "...")
                 self.selected_prompts_list.addItem(item)
            else:
                 logger.warning(f"ConfigDock: Could not find prompt data for selected ID: {prompt_id}")
        self.selected_prompts_list.blockSignals(False)

