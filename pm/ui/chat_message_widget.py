# pm/ui/chat_message_widget.py
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSizePolicy, QTextBrowser, QSpacerItem
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
import qtawesome as qta
from markdown2 import markdown
from loguru import logger

class ChatMessageWidget(QWidget):
    """Custom widget to display a single chat message with interaction buttons."""
    deleteRequested = Signal(str)  # Emits message_id when delete is clicked
    editRequested = Signal(str)    # Emits message_id when edit is clicked
    editSubmitted = Signal(str, str) # Emits message_id, new_content when save is clicked

    def __init__(self, message_data: dict, parent=None):
        super().__init__(parent)
        self.message_data = message_data
        self.message_id = message_data.get('id', '')
        self._raw_content = message_data.get('content', '') # Store raw content for editing

        self._init_ui()
        self.update_content(self._raw_content) # Initial content render

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(3)

        # --- Header Row (Role, Timestamp, Buttons) ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        role = self.message_data.get('role', 'unknown').capitalize()
        role_color = "#A0A0FF" if role == 'User' else "#FFA0A0" # Blue for user, Reddish for AI
        self.role_label = QLabel(f"<b>{role}</b>")
        self.role_label.setStyleSheet(f"color: {role_color};")
        header_layout.addWidget(self.role_label)

        timestamp = self.message_data.get('timestamp')
        if isinstance(timestamp, datetime.datetime):
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            self.timestamp_label = QLabel(ts_str)
            self.timestamp_label.setStyleSheet("color: grey; font-size: 8pt;")
            header_layout.addWidget(self.timestamp_label)

        header_layout.addStretch(1) # Push buttons to the right

        # Buttons (Delete, Edit)
        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(5)

        self.delete_button = QPushButton("X") # Simple delete button
        self.delete_button.setFixedSize(20, 20)
        self.delete_button.setToolTip("Delete this message and subsequent history")
        self.delete_button.clicked.connect(self._request_delete)
        self.button_layout.addWidget(self.delete_button)

        if self.message_data.get('role') == 'user':
            self.edit_button = QPushButton()
            self.edit_button.setIcon(qta.icon('fa5s.edit'))
            self.edit_button.setFixedSize(20, 20)
            self.edit_button.setToolTip("Edit this message and resubmit")
            self.edit_button.clicked.connect(self._request_edit)
            self.button_layout.addWidget(self.edit_button)
        else:
            self.edit_button = None # No edit button for AI

        header_layout.addLayout(self.button_layout)
        main_layout.addLayout(header_layout)

        # --- Content Display ---
        self.content_display = QTextBrowser(openExternalLinks=True)
        self.content_display.setReadOnly(True)
        self.content_display.setOpenExternalLinks(True)
        self.content_display.setStyleSheet("""
            QTextBrowser {
                border: none;
                background-color: transparent; /* Inherit background */
                padding: 0px;
            }
            pre, code { /* Basic Code block styles - theme might override */
                font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
                background-color: rgba(0, 0, 0, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 5px;
                border-radius: 4px;
                font-size: 10pt;
            }
            pre { display: block; white-space: pre-wrap; word-wrap: break-word; }
        """)
        # Make it expand vertically but start reasonably small
        self.content_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        main_layout.addWidget(self.content_display)

        # --- Edit Area (Initially Hidden) ---
        self.edit_widget = QWidget()
        edit_layout = QVBoxLayout(self.edit_widget)
        edit_layout.setContentsMargins(0, 5, 0, 0)
        self.edit_area = QTextEdit()
        self.edit_area.setAcceptRichText(False) # Edit raw text
        self.edit_area.setPlaceholderText("Edit your message...")
        edit_layout.addWidget(self.edit_area)

        edit_button_layout = QHBoxLayout()
        edit_button_layout.addStretch(1)
        self.save_button = QPushButton("Save & Resubmit")
        self.save_button.clicked.connect(self._handle_save)
        edit_button_layout.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.exit_edit_mode)
        edit_button_layout.addWidget(self.cancel_button)
        edit_layout.addLayout(edit_button_layout)

        self.edit_widget.setVisible(False) # Hide initially
        main_layout.addWidget(self.edit_widget)

        self.setLayout(main_layout)

    def update_content(self, new_raw_content: str):
        """Updates the displayed content, formatting markdown."""
        self._raw_content = new_raw_content # Store raw content
        try:
            # Format using markdown
            html_content = markdown(new_raw_content, extras=["fenced-code-blocks", "code-friendly", "break-on-newline"])
            # Set content *before* adjusting size
            self.content_display.setHtml(html_content)
        except Exception as e:
            logger.error(f"Markdown formatting error: {e}")
            self.content_display.setPlainText(f"[Error formatting content]\n{new_raw_content}") # Fallback

        # Adjust size *after* content update
        self.adjustSize()
        # Ensure the layout recalculates based on the new content size
        self.layout().activate()
        # Return the potentially updated size hint
        return self.sizeHint() # <<< ADD THIS RETURN


    def enter_edit_mode(self):
        """Switches the widget view to editing mode."""
        self.content_display.setVisible(False)
        self.delete_button.setVisible(False)
        if self.edit_button: self.edit_button.setVisible(False)

        self.edit_widget.setVisible(True)
        self.edit_area.setPlainText(self._raw_content)
        self.edit_area.setFocus()
        logger.debug(f"Entering edit mode for message ID: {self.message_id}")

    def exit_edit_mode(self):
        """Switches the widget view back to display mode."""
        self.edit_widget.setVisible(False)

        self.content_display.setVisible(True)
        self.delete_button.setVisible(True)
        if self.edit_button: self.edit_button.setVisible(True)
        logger.debug(f"Exiting edit mode for message ID: {self.message_id}")

    def _request_delete(self):
        """Emits the deleteRequested signal."""
        logger.debug(f"Delete requested for message ID: {self.message_id}")
        self.deleteRequested.emit(self.message_id)

    def _request_edit(self):
        """Emits the editRequested signal."""
        logger.debug(f"Edit requested for message ID: {self.message_id}")
        self.editRequested.emit(self.message_id)
        # The MainWindow handler will call enter_edit_mode

    def _handle_save(self):
        """Emits the editSubmitted signal and exits edit mode."""
        new_content = self.edit_area.toPlainText()
        logger.debug(f"Edit submitted for message ID: {self.message_id}")
        self.editSubmitted.emit(self.message_id, new_content)
        # self.update_content(new_content) # Update display immediately? Handled by rerender in main window
        self.exit_edit_mode()
