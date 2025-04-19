# pm/ui/prompt_editor_dialog.py
import uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QTextEdit,
    QDialogButtonBox, QLabel, QMessageBox
)
from PyQt6.QtCore import pyqtSlot, Qt
from loguru import logger
from typing import Dict, Optional

class PromptEditorDialog(QDialog):
    """Dialog for creating or editing user prompts."""

    def __init__(self, prompt_data: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Prompt" if prompt_data else "New Prompt")
        self.setMinimumSize(500, 400)

        self._prompt_id = prompt_data.get('id', str(uuid.uuid4())) if prompt_data else str(uuid.uuid4())
        self._is_editing = prompt_data is not None

        # --- UI Elements ---
        main_layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter a short, descriptive name")
        form_layout.addRow("Name:", self.name_input)

        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("Enter the prompt content...")
        self.content_edit.setAcceptRichText(False)
        # Set a reasonable minimum height
        self.content_edit.setMinimumHeight(150)
        form_layout.addRow("Content:", self.content_edit)

        self.id_label = QLabel(f"ID: {self._prompt_id}") # Display ID for reference
        form_layout.addRow(self.id_label)

        main_layout.addLayout(form_layout)

        # --- Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # --- Populate if editing ---
        if prompt_data:
            self.name_input.setText(prompt_data.get('name', ''))
            self.content_edit.setPlainText(prompt_data.get('content', ''))

        logger.debug(f"PromptEditorDialog initialized (Editing: {self._is_editing}, ID: {self._prompt_id})")

    @pyqtSlot()
    def _validate_and_accept(self):
        """Validate input before accepting the dialog."""
        name = self.name_input.text().strip()
        content = self.content_edit.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "Input Required", "Prompt name cannot be empty.")
            self.name_input.setFocus()
            return
        if not content:
            QMessageBox.warning(self, "Input Required", "Prompt content cannot be empty.")
            self.content_edit.setFocus()
            return

        self.accept() # Proceed if validation passes

    def get_prompt_data(self) -> Dict:
        """Returns the entered prompt data."""
        return {
            'id': self._prompt_id, # Return the existing or newly generated ID
            'name': self.name_input.text().strip(),
            'content': self.content_edit.toPlainText().strip()
        }
