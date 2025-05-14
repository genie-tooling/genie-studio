# pm/ui/change_queue_widget.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QListWidgetItem,
    QSizePolicy
)
# <<< Import QIcon >>>
from PySide6.QtGui import QIcon
# <<< Import QtCore elements >>>
from PySide6.QtCore import Qt, Signal, Slot
from loguru import logger
from pathlib import Path
from typing import List, Dict, Optional # Keep Optional for Python hints
import uuid
import qtawesome as qta # Import qtawesome

class ChangeQueueWidget(QWidget):
    """UI widget to display and manage pending file changes."""

    view_requested = Signal(dict)       # Emits the full change_data_dict
    apply_requested = Signal(list)      # list[change_data_dict] (for batch apply button)
    reject_requested = Signal(list)     # list[change_data_dict] (for batch reject button)
    queue_status_changed = Signal(bool) # True if empty, False otherwise

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("change_queue_widget")
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        main_layout = QVBoxLayout(self); main_layout.setContentsMargins(0, 0, 0, 0); main_layout.setSpacing(5)
        self.change_list = QListWidget(); self.change_list.setObjectName("change_list")
        self.change_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.change_list.setToolTip("Double-click to view/apply/reject the change.")
        main_layout.addWidget(self.change_list, 1) # Give it stretch
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply Selected"); self.apply_button.setObjectName("apply_button")
        self.apply_button.setToolTip("Apply the selected changes (where possible)."); self.apply_button.setEnabled(False)
        self.reject_button = QPushButton("Reject Selected"); self.reject_button.setObjectName("reject_button")
        self.reject_button.setToolTip("Discard the selected pending changes."); self.reject_button.setEnabled(False)
        button_layout.addWidget(self.reject_button); button_layout.addStretch(1); button_layout.addWidget(self.apply_button)
        main_layout.addLayout(button_layout); self.setLayout(main_layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)

    def _connect_signals(self):
        self.change_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.change_list.itemSelectionChanged.connect(self._update_button_states)
        self.apply_button.clicked.connect(self._on_apply_clicked)
        self.reject_button.clicked.connect(self._on_reject_clicked)

    def is_empty(self) -> bool: return self.change_list.count() == 0

    # <<< CORRECTED @Slot DECORATOR SIGNATURE >>>
    @Slot(Path, str, str, str, int, int, str) # Use 'str' for Optional args here
    def add_change(self,
                   file_path: Path,
                   proposed_content: str,
                   original_full_content: Optional[str], # Python hint still Optional
                   original_block_content: Optional[str],# Python hint still Optional
                   original_start_line: int,
                   original_end_line: int,
                   match_confidence: str):
        """Adds a detected change to the list with detailed info."""
        was_empty = self.is_empty()
        display_name = file_path.name
        change_id = str(uuid.uuid4())
        change_type = "replace" if match_confidence in ('exact', 'partial') else "insert_manual"

        change_data = {
            'id': change_id, 'file_path': file_path, 'display_name': display_name,
            'change_type': change_type, 'proposed_content': proposed_content,
            'original_full_content': original_full_content, 'original_block_content': original_block_content,
            'original_start_line': original_start_line, 'original_end_line': original_end_line,
            'match_confidence': match_confidence,
        }
        item = QListWidgetItem(display_name)
        item.setData(Qt.ItemDataRole.UserRole, change_data)
        # Add icon based on confidence
        icon_name = 'fa5s.check-double' if match_confidence == 'exact' else ('fa5s.question-circle' if match_confidence == 'partial' else 'fa5s.hand-pointer')
        try: item.setIcon(qta.icon(icon_name, color='gray'))
        except Exception as e: logger.warning(f"Failed to set icon {icon_name}: {e}")

        self.change_list.addItem(item)
        logger.info(f"ChangeQueue: Added pending '{change_type}' change for {display_name} (ID: {change_id}, Confidence: {match_confidence})")
        if was_empty: self.queue_status_changed.emit(False); self._update_button_states()

    @Slot(list)
    def remove_items(self, items_to_remove: List[QListWidgetItem]):
        # This function remains the same
        if not items_to_remove: return
        logger.debug(f"ChangeQueue: Removing {len(items_to_remove)} items.")
        self.change_list.blockSignals(True)
        try:
            for item in items_to_remove:
                data = item.data(Qt.ItemDataRole.UserRole); change_id = data.get('id', 'N/A') if isinstance(data, dict) else 'N/A'
                row = self.change_list.row(item)
                if row != -1: self.change_list.takeItem(row); logger.trace(f"Removed item {item.text()} (ID: {change_id})")
                else: logger.warning(f"Tried to remove item {item.text()} but wasn't found.")
        finally: self.change_list.blockSignals(False)
        is_now_empty = self.is_empty(); self.queue_status_changed.emit(is_now_empty); self._update_button_states()

    @Slot(QListWidgetItem)
    def _on_item_double_clicked(self, item: QListWidgetItem):
        change_data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(change_data, dict): logger.debug(f"ChangeQueue: View requested for {change_data.get('id')}"); self.view_requested.emit(change_data)

    @Slot()
    def _on_apply_clicked(self):
        selected_items = self.change_list.selectedItems()
        if not selected_items: return
        selected_data = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if isinstance(item.data(Qt.ItemDataRole.UserRole), dict)]
        if selected_data: logger.debug(f"ChangeQueue: Apply req for {len(selected_data)} items via button."); self.apply_requested.emit(selected_data)
        else: logger.warning("ChangeQueue: Apply clicked but no valid data.")

    @Slot()
    def _on_reject_clicked(self):
        selected_items = self.change_list.selectedItems()
        if not selected_items: return
        selected_data = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if isinstance(item.data(Qt.ItemDataRole.UserRole), dict)]
        if selected_data: logger.debug(f"ChangeQueue: Reject req for {len(selected_data)} items via button."); self.reject_requested.emit(selected_data)
        else: logger.warning("ChangeQueue: Reject clicked but no valid data.")

    @Slot()
    def _update_button_states(self):
        """Enable/disable Apply/Reject based on selection."""
        has_selection = len(self.change_list.selectedItems()) > 0
        # Enable apply if ANY selected item has confidence 'exact' or 'partial'
        can_apply_any_auto = False
        if has_selection:
            for item in self.change_list.selectedItems():
                 data = item.data(Qt.ItemDataRole.UserRole)
                 if isinstance(data, dict) and data.get('match_confidence') in ('exact', 'partial'):
                      can_apply_any_auto = True; break
        self.apply_button.setEnabled(can_apply_any_auto) # Only batch-apply if auto-match found
        self.reject_button.setEnabled(has_selection)

