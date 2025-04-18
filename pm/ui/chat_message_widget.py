# pm/ui/chat_message_widget.py
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSizePolicy, QTextBrowser, QSpacerItem, QApplication, QListWidget # Added QListWidget
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QTextBlock, QFontMetrics, QGuiApplication
import qtawesome as qta
from markdown2 import markdown
from loguru import logger
import uuid

class ChatMessageWidget(QWidget):
    """Custom widget to display a single chat message with interaction buttons."""
    deleteRequested = Signal(str)
    editRequested = Signal(str)
    editSubmitted = Signal(str, str)
    copyRequested = Signal(str)

    def __init__(self, message_data: dict, parent=None):
        super().__init__(parent)
        self.message_data = message_data
        self.message_id = message_data.get('id', str(uuid.uuid4()))
        self._raw_content = message_data.get('content', '')

        self._init_ui()
        # Initial population calls update_content -> updateGeometry
        self.update_content(self._raw_content)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(3)

        # --- Header Row ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        role = self.message_data.get('role', 'unknown').capitalize()
        role_color = "#A0A0FF" if role == 'User' else "#90EE90"
        self.role_label = QLabel(f"<b>{role}</b>")
        self.role_label.setStyleSheet(f"color: {role_color};")
        header_layout.addWidget(self.role_label)

        timestamp = self.message_data.get('timestamp')
        ts_str = timestamp.strftime("%H:%M:%S") if isinstance(timestamp, datetime.datetime) else ""
        self.timestamp_label = QLabel(ts_str)
        self.timestamp_label.setStyleSheet("color: grey; font-size: 8pt;")
        header_layout.addWidget(self.timestamp_label)

        header_layout.addStretch(1)

        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(5)
        self.copy_button = QPushButton()
        self.copy_button.setIcon(qta.icon('fa5s.copy'))
        self.copy_button.setFixedSize(20, 20)
        self.copy_button.setToolTip("Copy message content")
        self.copy_button.clicked.connect(self._request_copy)
        self.button_layout.addWidget(self.copy_button)

        if self.message_data.get('role') == 'user':
             self.edit_button = QPushButton()
             self.edit_button.setIcon(qta.icon('fa5s.edit'))
             self.edit_button.setFixedSize(20, 20)
             self.edit_button.setToolTip("Edit this message and resubmit")
             self.edit_button.clicked.connect(self._request_edit)
             self.button_layout.addWidget(self.edit_button)
        else:
             self.edit_button = None

        self.delete_button = QPushButton()
        self.delete_button.setIcon(qta.icon('fa5s.trash-alt', color='#F44336'))
        self.delete_button.setFixedSize(20, 20)
        self.delete_button.setToolTip("Delete this message and subsequent history")
        self.delete_button.clicked.connect(self._request_delete)
        self.button_layout.addWidget(self.delete_button)

        header_layout.addLayout(self.button_layout)
        main_layout.addLayout(header_layout)

        # --- Content Display ---
        self.content_display = QTextBrowser(openExternalLinks=True)
        self.content_display.setReadOnly(True)
        self.content_display.setOpenExternalLinks(True)
        # *** IMPORTANT: Keep scrollbars off for the BROWSER itself ***
        self.content_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_display.setMinimumHeight(20) # Prevent collapsing completely
        # Removed fixed height here
        self.content_display.setStyleSheet(
            "QTextBrowser { border: none; background-color: transparent; padding: 0px; }"
            "pre, code { font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace; "
            "background-color: rgba(0, 0, 0, 0.15); border: 1px solid rgba(255, 255, 255, 0.1); "
            "padding: 5px; border-radius: 4px; font-size: 10pt; }"
            "pre { display: block; white-space: pre-wrap; word-wrap: break-word; }"
        )
        # Let the widget expand horizontally, but its height should be determined by content
        self.content_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        main_layout.addWidget(self.content_display)

        # --- Edit Area ---
        self.edit_widget = QWidget()
        edit_layout = QVBoxLayout(self.edit_widget)
        edit_layout.setContentsMargins(0, 5, 0, 0)

        self.edit_area = QTextEdit()
        self.edit_area.setAcceptRichText(False)
        self.edit_area.setPlaceholderText("Edit your message...")
        self.edit_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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

        self.edit_widget.setVisible(False)
        main_layout.addWidget(self.edit_widget)

        self.setLayout(main_layout)
        # The widget itself should prefer its calculated height
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def update_content(self, new_raw_content: str):
        """Updates the text browser content and triggers layout recalculation."""
        self._raw_content = new_raw_content
        try:
            # Ensure code blocks wrap and newlines work reasonably
            html_content = markdown(new_raw_content, extras=["fenced-code-blocks", "code-friendly", "break-on-newline"])
            # Try to fix extra space from empty <p><br />\n</p> tags
            html_content = html_content.replace("<p><br />\n</p>", "<br />")
            self.content_display.setHtml(html_content)
        except Exception as e:
            logger.error(f"Markdown formatting error: {e}")
            self.content_display.setPlainText(f"[Error formatting content]\n{new_raw_content}")

        # *** Trigger geometry update AFTER content is set ***
        # This informs the layout system that the size hint may have changed.
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        """Provide a size hint based primarily on the document's height."""
        # --- Header Height ---
        header_height = 0
        header_layout_item = self.layout().itemAt(0)
        if header_layout_item and header_layout_item.layout():
             header_height = header_layout_item.layout().sizeHint().height()
        elif self.role_label: # Fallback if layout isn't ready?
             header_height = self.role_label.sizeHint().height()
        header_height = max(20, header_height) # Ensure minimum header height

        # --- Content Height ---
        content_height = 0
        if self.content_display.isVisible():
            # Determine available width more reliably
            available_width = self._calculate_available_width()

            # Set the document's width for height calculation
            self.content_display.document().setTextWidth(available_width)
            # Get the calculated document height
            doc_height = self.content_display.document().size().height()

            # Add margins/padding (adjust as needed)
            margins = self.content_display.contentsMargins()
            vertical_margins = margins.top() + margins.bottom() + (self.content_display.frameWidth() * 2)
            content_height = doc_height + vertical_margins + 5 # Small buffer

            # Ensure minimum content height
            content_height = max(self.content_display.minimumHeight(), content_height)

        # --- Edit Height ---
        edit_height = 0
        if self.edit_widget.isVisible():
            # Edit area height is managed in enter_edit_mode, but hint can be used
            edit_height = self.edit_widget.sizeHint().height()

        # --- Total Height ---
        spacing = self.layout().spacing() if self.layout() else 3
        total_height = header_height + spacing + max(content_height, edit_height)
        layout_margins = self.layout().contentsMargins()
        total_height += layout_margins.top() + layout_margins.bottom()

        width = super().sizeHint().width() # Keep default width hint behavior
        hint = QSize(width, int(total_height))

        # logger.trace(f"SizeHint ({self.message_id[:4]}): w={self.width()}->aw={available_width:.0f}, DocH={doc_height:.0f}, CntH={content_height:.0f}, TotH={total_height:.0f} -> {hint}")
        return hint

    def _calculate_available_width(self) -> int:
        """Helper to find a reasonable width for height calculation."""
        # Try self.width() first, but it might be 0 or small during initial layout
        current_width = self.width()
        if current_width > 50:
            return current_width - 10 # Subtract a bit for padding/margins

        # Fallback: Traverse up to find the QListWidget viewport width
        parent_widget = self.parent()
        while parent_widget and not isinstance(parent_widget, QListWidget):
            parent_widget = parent_widget.parent()

        if isinstance(parent_widget, QListWidget) and parent_widget.viewport():
            viewport_width = parent_widget.viewport().width()
            # Subtract scrollbar width (approx) and some padding
            scrollbar_width = parent_widget.verticalScrollBar().width() if parent_widget.verticalScrollBar().isVisible() else 0
            effective_width = viewport_width - scrollbar_width - 25 # More generous buffer
            return max(100, effective_width) # Ensure a minimum reasonable width

        # Absolute fallback if no list widget found
        return 600

    def enter_edit_mode(self):
        self.content_display.setVisible(False)
        self.copy_button.setVisible(False)
        self.delete_button.setVisible(False)
        if self.edit_button: self.edit_button.setVisible(False)

        self.edit_widget.setVisible(True)
        self.edit_area.setPlainText(self._raw_content)

        # Set fixed height for edit area based on lines (adjust multiplier as needed)
        line_count = self._raw_content.count('\n') + 1
        fm = QFontMetrics(self.edit_area.font())
        # Min height of ~5 lines, max based on content + buffer
        edit_area_height = max(fm.lineSpacing() * 5, fm.lineSpacing() * line_count + fm.lineSpacing())
        self.edit_area.setFixedHeight(int(edit_area_height))

        self.edit_area.setFocus()
        self.edit_area.selectAll()
        logger.debug(f"Entering edit mode for message ID: {self.message_id}")
        self.updateGeometry() # Recalculate size hint based on edit widget

    def exit_edit_mode(self):
        self.edit_widget.setVisible(False)
        self.content_display.setVisible(True)
        self.copy_button.setVisible(True)
        self.delete_button.setVisible(True)
        if self.edit_button: self.edit_button.setVisible(True)
        logger.debug(f"Exiting edit mode for message ID: {self.message_id}")
        self.updateGeometry() # Recalculate size hint based on content display

    def _request_delete(self):
        self.deleteRequested.emit(self.message_id)

    def _request_edit(self):
        self.editRequested.emit(self.message_id)

    def _handle_save(self):
        new_content = self.edit_area.toPlainText().strip() # Strip whitespace
        # Check if content actually changed
        if new_content != self._raw_content.strip():
            self.editSubmitted.emit(self.message_id, new_content)
            # Exit edit mode handled by ChatActionHandler after processing submission
            # self.exit_edit_mode() # Don't exit here immediately
        else:
            logger.debug("Edit submitted, but content unchanged. Cancelling edit.")
            self.exit_edit_mode() # Exit if no change

    def _request_copy(self):
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self._raw_content)
        logger.debug(f"Copied content of message {self.message_id} to clipboard.")

