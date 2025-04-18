# pm/ui/chat_message_widget.py
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSizePolicy, QTextBrowser, QSpacerItem
)
# --- Import QSize, QFontMetrics ---
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QTextBlock, QFontMetrics
import qtawesome as qta
from markdown2 import markdown
from loguru import logger

MIN_CHAT_LINES = 5
MAX_CHAT_LINES = 200

class ChatMessageWidget(QWidget):
    """Custom widget to display a single chat message with interaction buttons."""
    deleteRequested = Signal(str)
    editRequested = Signal(str)
    editSubmitted = Signal(str, str)

    def __init__(self, message_data: dict, parent=None):
        super().__init__(parent)
        self.message_data = message_data
        self.message_id = message_data.get('id', '')
        self._raw_content = message_data.get('content', '')
        self._min_content_height = 0
        self._max_content_height = 0

        self._init_ui()
        self._calculate_min_max_heights()
        self.update_content(self._raw_content)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(3)

        # Header Row (simplified)
        header_layout = QHBoxLayout(); header_layout.setContentsMargins(0, 0, 0, 0)
        role = self.message_data.get('role', 'unknown').capitalize(); role_color = "#A0A0FF" if role == 'User' else "#FFA0A0"
        self.role_label = QLabel(f"<b>{role}</b>"); self.role_label.setStyleSheet(f"color: {role_color};")
        header_layout.addWidget(self.role_label)
        timestamp = self.message_data.get('timestamp'); ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp, datetime.datetime) else ""
        self.timestamp_label = QLabel(ts_str); self.timestamp_label.setStyleSheet("color: grey; font-size: 8pt;"); header_layout.addWidget(self.timestamp_label)
        header_layout.addStretch(1)
        self.button_layout = QHBoxLayout(); self.button_layout.setSpacing(5)
        self.delete_button = QPushButton("X"); self.delete_button.setFixedSize(20, 20); self.delete_button.setToolTip("Delete this message and subsequent history"); self.delete_button.clicked.connect(self._request_delete)
        self.button_layout.addWidget(self.delete_button)
        if self.message_data.get('role') == 'user': self.edit_button = QPushButton(); self.edit_button.setIcon(qta.icon('fa5s.edit')); self.edit_button.setFixedSize(20, 20); self.edit_button.setToolTip("Edit this message and resubmit"); self.edit_button.clicked.connect(self._request_edit); self.button_layout.addWidget(self.edit_button)
        else: self.edit_button = None
        header_layout.addLayout(self.button_layout); main_layout.addLayout(header_layout)

        # Content Display
        self.content_display = QTextBrowser(openExternalLinks=True)
        self.content_display.setReadOnly(True); self.content_display.setOpenExternalLinks(True)
        self.content_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_display.setStyleSheet("QTextBrowser { border: none; background-color: transparent; padding: 0px; } pre, code { font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace; background-color: rgba(0, 0, 0, 0.15); border: 1px solid rgba(255, 255, 255, 0.1); padding: 5px; border-radius: 4px; font-size: 10pt; } pre { display: block; white-space: pre-wrap; word-wrap: break-word; }")
        # --- Important: Keep Expanding, but rely on min/max height for limits ---
        self.content_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.content_display)

        # Edit Area (simplified)
        self.edit_widget = QWidget(); edit_layout = QVBoxLayout(self.edit_widget); edit_layout.setContentsMargins(0, 5, 0, 0)
        self.edit_area = QTextEdit(); self.edit_area.setAcceptRichText(False); self.edit_area.setPlaceholderText("Edit your message...")
        edit_layout.addWidget(self.edit_area)
        edit_button_layout = QHBoxLayout(); edit_button_layout.addStretch(1)
        self.save_button = QPushButton("Save & Resubmit"); self.save_button.clicked.connect(self._handle_save); edit_button_layout.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.clicked.connect(self.exit_edit_mode); edit_button_layout.addWidget(self.cancel_button)
        edit_layout.addLayout(edit_button_layout); self.edit_widget.setVisible(False); main_layout.addWidget(self.edit_widget)

        self.setLayout(main_layout)
        # --- Set VPolicy to Preferred, allowing growth/shrink based on content hint ---
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def _calculate_min_max_heights(self):
        font_metrics = QFontMetrics(self.content_display.font())
        line_spacing = font_metrics.lineSpacing()
        # Add document margin (default is often 4) + frame width (usually 1*2)
        vertical_padding = (self.content_display.document().documentMargin() * 2) + (self.content_display.frameWidth() * 2) + 2 # Extra pixels

        self._min_content_height = line_spacing * MIN_CHAT_LINES + vertical_padding
        self._max_content_height = line_spacing * MAX_CHAT_LINES + vertical_padding

        # Apply ONLY to the content browser
        self.content_display.setMinimumHeight(self._min_content_height)
        self.content_display.setMaximumHeight(self._max_content_height)
        logger.trace(f"ChatMessageWidget ({self.message_id[:4]}...): Min/Max Content Height set to {self._min_content_height}/{self._max_content_height} px")

    def update_content(self, new_raw_content: str):
        self._raw_content = new_raw_content
        try:
            html_content = markdown(new_raw_content, extras=["fenced-code-blocks", "code-friendly", "break-on-newline"])
            self.content_display.setHtml(html_content)
        except Exception as e:
            logger.error(f"Markdown formatting error: {e}")
            self.content_display.setPlainText(f"[Error formatting content]\n{new_raw_content}")

        # --- Trigger layout update ---
        # This is usually enough, sizeHint override does the rest
        self.layout().activate()
        self.updateGeometry() # Crucial: tell parent layout the hint might have changed
        # ---------------------------

    # --- Override sizeHint ---
    def sizeHint(self) -> QSize:
        """Provide a size hint based on content, clamped by min/max height."""
        # Get the ideal height of the document content
        doc_height = self.content_display.document().size().height()

        # Add margins/padding of the QTextBrowser itself
        margins = self.content_display.contentsMargins()
        vertical_margins = margins.top() + margins.bottom() + (self.content_display.frameWidth() * 2)

        # Calculate target content height, clamped by min/max
        target_content_height = max(self._min_content_height, min(doc_height + vertical_margins, self._max_content_height))

        # Calculate total widget height (content + header + spacing)
        header_height = self.role_label.sizeHint().height() # Approx header height
        spacing = self.layout().spacing()
        total_height = header_height + spacing + target_content_height

        # Width remains default/expanding
        width = super().sizeHint().width()
        hint = QSize(width, int(total_height))
        # logger.trace(f"SizeHint ({self.message_id[:4]}): DocH={doc_height:.0f}, TargetH={target_content_height:.0f}, TotalH={total_height:.0f} -> {hint}")
        return hint

    # --- Override minimumSizeHint ---
    def minimumSizeHint(self) -> QSize:
         """Provide a minimum hint based on minimum content height."""
         header_height = self.role_label.sizeHint().height()
         spacing = self.layout().spacing()
         total_min_height = header_height + spacing + self._min_content_height
         width = super().minimumSizeHint().width() # Keep default width logic
         hint = QSize(width, int(total_min_height))
         # logger.trace(f"MinSizeHint ({self.message_id[:4]}): -> {hint}")
         return hint


    def enter_edit_mode(self):
        self.content_display.setVisible(False); self.delete_button.setVisible(False)
        if self.edit_button: self.edit_button.setVisible(False)
        self.edit_widget.setVisible(True)
        self.edit_area.setPlainText(self._raw_content)
        # Calculate a reasonable height for the edit area too
        edit_area_height = max(self._min_content_height, min(self.edit_area.document().size().height() + 10, self._max_content_height))
        self.edit_area.setFixedHeight(int(edit_area_height))
        self.edit_area.setFocus()
        logger.debug(f"Entering edit mode for message ID: {self.message_id}")
        self.updateGeometry()

    def exit_edit_mode(self):
        self.edit_widget.setVisible(False); self.content_display.setVisible(True)
        self.delete_button.setVisible(True);
        if self.edit_button: self.edit_button.setVisible(True)
        logger.debug(f"Exiting edit mode for message ID: {self.message_id}")
        self.updateGeometry()

    def _request_delete(self): self.deleteRequested.emit(self.message_id)
    def _request_edit(self): self.editRequested.emit(self.message_id)
    def _handle_save(self): self.editSubmitted.emit(self.message_id, self.edit_area.toPlainText()); self.exit_edit_mode()
