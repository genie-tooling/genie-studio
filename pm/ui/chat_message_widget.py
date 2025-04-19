# pm/ui/chat_message_widget.py
import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSizePolicy, QTextBrowser, QSpacerItem, QApplication, QListWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QTextBlock, QFontMetrics, QGuiApplication
import qtawesome as qta
from markdown2 import markdown
from loguru import logger
import uuid

class ChatMessageWidget(QWidget):
    """Custom widget to display a single chat message with interaction buttons."""
    deleteRequested = pyqtSignal(str)
    editRequested = pyqtSignal(str)
    editSubmitted = pyqtSignal(str, str)
    copyRequested = pyqtSignal(str)

    def __init__(self, message_data: dict, parent=None):
        super().__init__(parent)
        self.message_data = message_data
        self.message_id = message_data.get('id', str(uuid.uuid4()))
        self._raw_content = message_data.get('content', '')
        self._current_html_content = ""

        # --- UI element references needed for sizeHint ---
        self.role_label: QLabel = None
        self.copy_button: QPushButton = None # Need a reference to a button in the layout
        self.content_display: QTextBrowser = None
        self.edit_widget: QWidget = None
        # --- End UI references ---

        self._init_ui()
        self.update_content(self._raw_content)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5); main_layout.setSpacing(3)
        header_layout = QHBoxLayout(); header_layout.setContentsMargins(0, 0, 0, 0)
        role = self.message_data.get('role', 'unknown').capitalize(); role_color = "#A0A0FF" if role == 'User' else "#90EE90"
        self.role_label = QLabel(f"<b>{role}</b>"); self.role_label.setStyleSheet(f"color: {role_color};") # Assign here
        header_layout.addWidget(self.role_label)
        timestamp = self.message_data.get('timestamp'); ts_str = timestamp.strftime("%H:%M:%S") if isinstance(timestamp, datetime.datetime) else ""
        self.timestamp_label = QLabel(ts_str); self.timestamp_label.setStyleSheet("color: grey; font-size: 8pt;")
        header_layout.addWidget(self.timestamp_label)
        header_layout.addStretch(1)

        button_layout_widget = QWidget() # Create a widget to hold the button layout
        self.button_layout = QHBoxLayout(button_layout_widget) # Apply layout to the widget
        self.button_layout.setSpacing(5); self.button_layout.setContentsMargins(0,0,0,0) # No margins for inner layout

        self.copy_button = QPushButton(qta.icon('fa5s.copy'), ""); self.copy_button.setFixedSize(20, 20); self.copy_button.setToolTip("Copy message content"); self.copy_button.clicked.connect(self._request_copy) # Assign here
        self.button_layout.addWidget(self.copy_button)
        if self.message_data.get('role') == 'user':
             self.edit_button = QPushButton(qta.icon('fa5s.edit'), ""); self.edit_button.setFixedSize(20, 20); self.edit_button.setToolTip("Edit this message and resubmit"); self.edit_button.clicked.connect(self._request_edit); self.button_layout.addWidget(self.edit_button)
        else: self.edit_button = None
        self.delete_button = QPushButton(qta.icon('fa5s.trash-alt', color='#F44336'), ""); self.delete_button.setFixedSize(20, 20); self.delete_button.setToolTip("Delete this message and subsequent history"); self.delete_button.clicked.connect(self._request_delete); self.button_layout.addWidget(self.delete_button)

        header_layout.addWidget(button_layout_widget) # Add the widget containing buttons
        main_layout.addLayout(header_layout)

        self.content_display = QTextBrowser(openExternalLinks=True); self.content_display.setReadOnly(True); self.content_display.setOpenExternalLinks(True) # Assign here
        self.content_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.content_display.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_display.setMinimumHeight(20); self.content_display.setStyleSheet("QTextBrowser { border: none; background-color: transparent; padding: 0px; }" "pre, code { font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace; background-color: rgba(0, 0, 0, 0.15); border: 1px solid rgba(255, 255, 255, 0.1); padding: 5px; border-radius: 4px; font-size: 10pt; }" "pre { display: block; white-space: pre-wrap; word-wrap: break-word; }")
        self.content_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); main_layout.addWidget(self.content_display)

        self.edit_widget = QWidget(); edit_layout = QVBoxLayout(self.edit_widget); edit_layout.setContentsMargins(0, 5, 0, 0) # Assign here
        self.edit_area = QTextEdit(); self.edit_area.setAcceptRichText(False); self.edit_area.setPlaceholderText("Edit your message..."); self.edit_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); edit_layout.addWidget(self.edit_area)
        edit_button_layout = QHBoxLayout(); edit_button_layout.addStretch(1)
        self.save_button = QPushButton("Save & Resubmit"); self.save_button.clicked.connect(self._handle_save); edit_button_layout.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.clicked.connect(self.exit_edit_mode); edit_button_layout.addWidget(self.cancel_button)
        edit_layout.addLayout(edit_button_layout); self.edit_widget.setVisible(False); main_layout.addWidget(self.edit_widget)
        self.setLayout(main_layout); self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def update_content(self, new_raw_content: str):
        if self._raw_content == new_raw_content and self.content_display.toHtml() == self._current_html_content:
            return
        self._raw_content = new_raw_content
        try:
            html_content = markdown(new_raw_content, extras=["fenced-code-blocks", "code-friendly", "break-on-newline"])
            html_content = html_content.replace("<p><br />\n</p>", "<br />")
            self.content_display.setHtml(html_content)
            self._current_html_content = html_content
        except Exception as e:
            logger.error(f"Markdown formatting error: {e}")
            error_html = f"<p>[Error formatting content]</p><pre>{new_raw_content}</pre>"
            self.content_display.setHtml(error_html)
            self._current_html_content = error_html
        QTimer.singleShot(0, self.updateGeometry)

    def sizeHint(self) -> QSize:
        """Provide a size hint based primarily on the content's height."""
        width = self.width() or self._calculate_available_width()

        # Header Height
        header_height = self.role_label.sizeHint().height() if self.role_label and self.role_label.isVisible() else 0
        # --- FIX: Check visibility of a WIDGET in the layout ---
        # Use self.copy_button as it's always present conceptually, even if hidden in edit mode
        if self.copy_button and self.copy_button.isVisible():
            # Calculate height based on the button layout's parent widget if needed
            # Or estimate based on a button's height
            button_height = self.copy_button.sizeHint().height()
            header_height = max(header_height, button_height + self.button_layout.contentsMargins().top() + self.button_layout.contentsMargins().bottom())
        # -------------------------------------------------------
        header_height = max(20, header_height) # Ensure minimum

        # Content Height
        content_height = 0
        if self.content_display and self.content_display.isVisible():
            self.content_display.document().adjustSize()
            self.content_display.document().setTextWidth(width)
            doc_height = self.content_display.document().size().height()
            margins = self.content_display.contentsMargins()
            vertical_margins = margins.top() + margins.bottom() + (self.content_display.frameWidth() * 2)
            content_height = doc_height + vertical_margins + 5
            content_height = max(self.content_display.minimumHeight(), content_height)

        # Edit Height
        edit_height = 0
        if self.edit_widget and self.edit_widget.isVisible():
            edit_height = self.edit_widget.sizeHint().height()

        spacing = self.layout().spacing() if self.layout() else 3
        total_height = header_height + spacing + max(content_height, edit_height)
        layout_margins = self.layout().contentsMargins()
        total_height += layout_margins.top() + layout_margins.bottom()

        hint = QSize(width, int(total_height))
        return hint

    def _calculate_available_width(self) -> int:
        parent_widget = self.parent()
        while parent_widget and not isinstance(parent_widget, QListWidget): parent_widget = parent_widget.parent()
        if isinstance(parent_widget, QListWidget) and parent_widget.viewport():
            vp_width = parent_widget.viewport().width()
            scrollbar_width = parent_widget.verticalScrollBar().width() if parent_widget.verticalScrollBar().isVisible() else 0
            margins = parent_widget.contentsMargins(); list_padding = margins.left() + margins.right()
            effective_width = vp_width - scrollbar_width - list_padding - 25
            return max(100, effective_width)
        return 600

    def enter_edit_mode(self):
        self.content_display.setVisible(False); self.copy_button.setVisible(False)
        self.delete_button.setVisible(False);
        if self.edit_button: self.edit_button.setVisible(False)
        self.edit_widget.setVisible(True); self.edit_area.setPlainText(self._raw_content)
        line_count = self._raw_content.count('\n') + 1; fm = QFontMetrics(self.edit_area.font())
        edit_area_height = max(fm.lineSpacing() * 5, fm.lineSpacing() * line_count + fm.lineSpacing())
        self.edit_area.setFixedHeight(int(edit_area_height))
        self.edit_area.setFocus(); self.edit_area.selectAll()
        logger.debug(f"Entering edit mode for message ID: {self.message_id}"); self.updateGeometry()

    def exit_edit_mode(self):
        self.edit_widget.setVisible(False); self.content_display.setVisible(True)
        self.copy_button.setVisible(True); self.delete_button.setVisible(True);
        if self.edit_button: self.edit_button.setVisible(True)
        logger.debug(f"Exiting edit mode for message ID: {self.message_id}"); self.updateGeometry()

    def _request_delete(self): self.deleteRequested.emit(self.message_id)
    def _request_edit(self): self.editRequested.emit(self.message_id)
    def _handle_save(self):
        new_content = self.edit_area.toPlainText().strip()
        if new_content != self._raw_content.strip(): self.editSubmitted.emit(self.message_id, new_content)
        else: logger.debug("Edit cancelled, content unchanged."); self.exit_edit_mode()
    def _request_copy(self): QGuiApplication.clipboard().setText(self._raw_content); logger.debug(f"Copied msg {self.message_id}.")

