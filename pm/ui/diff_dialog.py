# pm/ui/diff_dialog.py
import difflib
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QTextBrowser, QPushButton, QDialogButtonBox, QApplication,
    QWidget, QLabel, QSizePolicy, QSplitter, QScrollBar, QMessageBox
)
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor, QTextBlockFormat, QPainter, QTextBlock
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSlot, QTimer
from loguru import logger

class DiffDialog(QDialog):
    """
    Displays differences, handles auto-detected changes, manual insertion, and applying as patch.
    """
    def __init__(self,
                 original_full_content: str,
                 original_block_content: Optional[str],
                 original_start_line: int,
                 original_end_line: int,
                 proposed_content: str,
                 match_confidence: str, # 'exact', 'partial', 'none'
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Proposed Code Change")
        self.setMinimumSize(1000, 700)

        self._original_full_content = original_full_content
        self._original_block_content = original_block_content if original_block_content is not None else ""
        self._original_start_line = original_start_line
        self._original_end_line = original_end_line
        self._proposed_content = proposed_content
        self._match_confidence = match_confidence
        self._can_auto_apply = (match_confidence in ('exact', 'partial'))

        # --- State ---
        self.insertion_line = -1 # Set if user chooses 'Insert Here'
        self.apply_mode = 'reject' # Default: 'auto_replace', 'insert', 'reject', 'patch'
        self._interaction_mode = 'auto' if self._can_auto_apply else 'insert' # 'auto' or 'insert'
        self._highlighted_insertion_block: Optional[QTextBlock] = None
        self._insertion_highlight_format = QTextBlockFormat()
        self._insertion_highlight_format.setBackground(QColor("#004488")) # Blue insertion highlight

        self._setup_ui()
        self._populate_views()
        self._highlight_content()
        if self._interaction_mode == 'auto':
             self._scroll_to_original_block()
        else:
            self._set_insertion_mode_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget); left_layout.setContentsMargins(0,0,0,0)
        left_layout.addWidget(QLabel("Original File Content:"))
        self.original_view = QTextBrowser(); self.original_view.setReadOnly(True)
        self.original_view.setFont(QFont("Fira Code", 10)); self.original_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        left_layout.addWidget(self.original_view); self.splitter.addWidget(left_widget)

        right_widget = QWidget(); right_layout = QVBoxLayout(right_widget); right_layout.setContentsMargins(0,0,0,0)
        right_layout.addWidget(QLabel("Proposed Code Block:"))
        self.proposed_view = QTextBrowser(); self.proposed_view.setReadOnly(True)
        self.proposed_view.setFont(QFont("Fira Code", 10)); self.proposed_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_layout.addWidget(self.proposed_view); self.splitter.addWidget(right_widget)

        main_layout.addWidget(self.splitter, 1)

        self.button_box = QDialogButtonBox()
        self.info_layout = QHBoxLayout()

        # --- Conditional Buttons ---
        if self._can_auto_apply:
            self.apply_button = self.button_box.addButton("Apply Auto-Detected Change", QDialogButtonBox.ButtonRole.AcceptRole)
            self.apply_button.setToolTip("Replace the auto-detected original block with the proposed code.")
            self.apply_button.clicked.connect(self._handle_auto_apply_clicked)

            # NEW: Apply as Patch button (only if auto-detection possible)
            self.apply_patch_button = QPushButton("Apply as Patch...")
            self.apply_patch_button.setToolTip("Generate a diff patch and attempt to apply it (experimental).")
            self.apply_patch_button.clicked.connect(self._handle_apply_patch_clicked)
            self.button_box.addButton(self.apply_patch_button, QDialogButtonBox.ButtonRole.ActionRole)

            self.choose_location_button = QPushButton("Choose Insert Location...")
            self.choose_location_button.setToolTip("Ignore auto-detection and manually select where to insert the code.")
            self.choose_location_button.clicked.connect(self._handle_choose_location_clicked)
            self.button_box.addButton(self.choose_location_button, QDialogButtonBox.ButtonRole.ActionRole)

            self.insert_button = QPushButton("Insert at Highlighted Line")
            self.insert_button.setToolTip("Insert the proposed code AT the highlighted line in the original view.")
            self.insert_button.setEnabled(False); self.insert_button.setVisible(False)
            self.insert_button.clicked.connect(self._handle_insert_clicked)
            self.button_box.addButton(self.insert_button, QDialogButtonBox.ButtonRole.AcceptRole)

            confidence_text = "Exact Match" if self._match_confidence == 'exact' else "Partial Match"
            info_label = QLabel(f"<i>Auto-detected location ({confidence_text}).</i>")
            info_label.setStyleSheet("color: lightgreen;" if self._match_confidence == 'exact' else "color: yellow;")
            self.info_layout.addWidget(info_label, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        else: # Cannot auto apply
            self.apply_button = None
            self.apply_patch_button = None # No patch if no auto-detection
            self.choose_location_button = None
            self.insert_button = QPushButton("Insert at Highlighted Line")
            self.insert_button.setToolTip("Insert the proposed code AT the highlighted line in the original view.")
            self.insert_button.setEnabled(False)
            self.insert_button.clicked.connect(self._handle_insert_clicked)
            self.button_box.addButton(self.insert_button, QDialogButtonBox.ButtonRole.AcceptRole)

            info_label = QLabel("<i>Cannot apply automatically. Click line to highlight insertion point.</i>")
            info_label.setStyleSheet("color: orange;")
            self.info_layout.addWidget(info_label, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        # --- Standard Buttons ---
        self.reject_button = self.button_box.addButton("Reject Change", QDialogButtonBox.ButtonRole.RejectRole)
        self.copy_button = QPushButton("Copy Proposed")
        self.copy_button.setToolTip("Copy the proposed code block to the clipboard.")
        self.button_box.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)

        bottom_layout = QHBoxLayout()
        bottom_layout.addLayout(self.info_layout, 1)
        bottom_layout.addWidget(self.button_box)
        main_layout.addLayout(bottom_layout)

        # --- Connections ---
        self.reject_button.clicked.connect(self.reject)
        self.copy_button.clicked.connect(self._copy_proposed_content)
        self.original_view.cursorPositionChanged.connect(self._handle_cursor_change)
        self.original_view.verticalScrollBar().valueChanged.connect(self._sync_scroll_original)
        self.proposed_view.verticalScrollBar().valueChanged.connect(self._sync_scroll_proposed)

        self.setLayout(main_layout)

    def accept(self):
        self._remove_insertion_highlight()
        super().accept()
    def reject(self):
        self._remove_insertion_highlight()
        self.apply_mode = 'reject'
        super().reject()

    def _set_insertion_mode_ui(self):
        """Configure UI elements for manual insertion mode."""
        self._interaction_mode = 'insert'
        self.original_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.original_view.setFocus()
        if self.apply_button: self.apply_button.setVisible(False); self.apply_button.setEnabled(False)
        if self.apply_patch_button: self.apply_patch_button.setVisible(False); self.apply_patch_button.setEnabled(False) # Hide patch button too
        if self.choose_location_button: self.choose_location_button.setVisible(False); self.choose_location_button.setEnabled(False)
        if self.insert_button: self.insert_button.setVisible(True); self.insert_button.setEnabled(False)
        info_label_widget = self.info_layout.itemAt(0).widget()
        if isinstance(info_label_widget, QLabel):
             info_label_widget.setText("<i>Click line to highlight insertion point.</i>")
             info_label_widget.setStyleSheet("color: orange;")
        logger.debug("Switched DiffDialog to INSERT mode.")

    @pyqtSlot()
    def _handle_auto_apply_clicked(self):
        self.apply_mode = 'auto_replace'
        self.accept()

    @pyqtSlot()
    def _handle_choose_location_clicked(self):
        self._set_insertion_mode_ui()

    @pyqtSlot()
    def _handle_insert_clicked(self):
        if self._highlighted_insertion_block and self._highlighted_insertion_block.isValid():
            self.insertion_line = self._highlighted_insertion_block.blockNumber()
            self.apply_mode = 'insert'
            logger.info(f"DiffDialog: 'Insert Here' confirmed for line {self.insertion_line + 1}")
            self.accept()
        else: logger.warning("Insert clicked, but no valid line highlighted.")

    @pyqtSlot()
    def _handle_apply_patch_clicked(self):
        """Handles the 'Apply as Patch' button click."""
        # This is currently experimental and might not be fully implemented downstream
        # For now, just set the mode and accept the dialog
        self.apply_mode = 'patch'
        QMessageBox.information(self, "Experimental", "Apply as Patch selected. Note: Downstream patch application might not be fully implemented.")
        self.accept()

    @pyqtSlot()
    def _handle_cursor_change(self):
        if self._interaction_mode != 'insert': return
        cursor = self.original_view.textCursor()
        current_block = cursor.block()
        if current_block != self._highlighted_insertion_block:
            self._remove_insertion_highlight()
            self._apply_insertion_highlight(current_block)
        if self.insert_button:
            self.insert_button.setEnabled(self._highlighted_insertion_block is not None)

    def _remove_insertion_highlight(self):
        if self._highlighted_insertion_block and self._highlighted_insertion_block.isValid():
            cursor = QTextCursor(self._highlighted_insertion_block)
            current_fmt = self._highlighted_insertion_block.blockFormat()
            current_fmt.clearBackground()
            cursor.setBlockFormat(current_fmt)
        self._highlighted_insertion_block = None

    def _apply_insertion_highlight(self, block: QTextBlock):
        if block and block.isValid():
            cursor = QTextCursor(block)
            current_fmt = block.blockFormat()
            current_fmt.setBackground(self._insertion_highlight_format.background())
            cursor.setBlockFormat(current_fmt)
            self._highlighted_insertion_block = block
        else: self._highlighted_insertion_block = None

    def _populate_views(self):
        self.original_view.setPlainText(self._original_full_content)
        self.proposed_view.setPlainText(self._proposed_content)

    def _scroll_to_original_block(self):
        if self._original_start_line != -1:
            cursor = self.original_view.textCursor()
            block = self.original_view.document().findBlockByLineNumber(self._original_start_line)
            if block.isValid(): cursor.setPosition(block.position()); self.original_view.setTextCursor(cursor); self.original_view.ensureCursorVisible()
            else: logger.warning(f"Cannot scroll to invalid block line {self._original_start_line}")

    def _highlight_content(self):
        if self._interaction_mode == 'auto': self._highlight_differences()
        else: self._highlight_insertion_mode()

    def _highlight_insertion_mode(self):
        logger.debug("Highlighting for insertion mode.")
        fmt = QTextCharFormat(); fmt.setBackground(QColor("#303030"))
        cursor_prop = self.proposed_view.textCursor(); cursor_prop.select(QTextCursor.SelectionType.Document)
        cursor_prop.mergeCharFormat(fmt); cursor_prop.clearSelection()

    def _highlight_differences(self):
        if not self._can_auto_apply: return
        original_block_lines = self._original_block_content.splitlines()
        proposed_lines = self._proposed_content.splitlines()
        differ = difflib.SequenceMatcher(None, original_block_lines, proposed_lines, autojunk=False)
        opcodes = differ.get_opcodes()
        cursor_orig = self.original_view.textCursor()
        cursor_prop = self.proposed_view.textCursor()

        color_delete = QColor("#5A3131"); color_insert = QColor("#315A31")
        color_replace_orig = QColor("#5A5A31") if self._match_confidence == 'partial' else color_delete
        color_replace_prop = QColor("#315A31")
        outline_color = QColor("#383838") if self._match_confidence == 'exact' else QColor("#505030")

        try: # Outline block
            start_block = self.original_view.document().findBlockByLineNumber(self._original_start_line)
            end_block = self.original_view.document().findBlockByLineNumber(self._original_end_line)
            if start_block.isValid() and end_block.isValid():
                cursor_orig.setPosition(start_block.position())
                cursor_orig.setPosition(end_block.position() + end_block.length() -1, QTextCursor.MoveMode.KeepAnchor)
                outline_fmt = QTextCharFormat(); outline_fmt.setBackground(outline_color)
                cursor_orig.mergeCharFormat(outline_fmt); cursor_orig.clearSelection()
        except Exception as e: logger.error(f"Error applying outline: {e}")

        for tag, i1, i2, j1, j2 in opcodes: # Apply diffs
            if tag == 'equal': continue
            if tag == 'delete' or tag == 'replace':
                self._apply_block_background(self.original_view, self._original_start_line + i1, self._original_start_line + i2 - 1, color_delete if tag == 'delete' else color_replace_orig)
            if tag == 'insert' or tag == 'replace':
                self._apply_block_background(self.proposed_view, j1, j2 - 1, color_insert if tag == 'insert' else color_replace_prop)

    def _apply_block_background(self, text_edit: QTextBrowser, start_line: int, end_line: int, color: QColor):
        cursor = text_edit.textCursor(); start_block = text_edit.document().findBlockByLineNumber(start_line); end_block = text_edit.document().findBlockByLineNumber(end_line)
        if not (start_block.isValid() and end_block.isValid()): return
        cursor.beginEditBlock(); current_block = start_block
        while current_block.isValid() and current_block.blockNumber() <= end_block.blockNumber():
            block_fmt = current_block.blockFormat(); block_fmt.setBackground(color); temp_cursor = QTextCursor(current_block); temp_cursor.setBlockFormat(block_fmt); current_block = current_block.next()
        cursor.endEditBlock()

    _syncing_scroll = False
    @pyqtSlot(int)
    def _sync_scroll_original(self, value):
        if self._syncing_scroll: return; self._syncing_scroll = True; self.proposed_view.verticalScrollBar().setValue(value); QTimer.singleShot(0, lambda: setattr(self, '_syncing_scroll', False))
    @pyqtSlot(int)
    def _sync_scroll_proposed(self, value):
        if self._syncing_scroll: return; self._syncing_scroll = True; self.original_view.verticalScrollBar().setValue(value); QTimer.singleShot(0, lambda: setattr(self, '_syncing_scroll', False))

    @pyqtSlot()
    def _copy_proposed_content(self):
        QApplication.clipboard().setText(self._proposed_content)

