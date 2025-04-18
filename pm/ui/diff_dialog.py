# pm/ui/diff_dialog.py

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QDialogButtonBox, QApplication
)
from PySide6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor # For optional highlighting
from PySide6.QtCore import QRegularExpression # For optional highlighting
# import difflib # Import if you plan to process diffs further

class DiffHighlighter(QSyntaxHighlighter):
    """Basic syntax highlighter for diff/patch files."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []

        # Format for added lines (+)
        add_format = QTextCharFormat()
        add_format.setForeground(QColor("green"))
        self.highlightingRules.append((QRegularExpression(r"^\+.*"), add_format))

        # Format for removed lines (-)
        remove_format = QTextCharFormat()
        remove_format.setForeground(QColor("red"))
        self.highlightingRules.append((QRegularExpression(r"^\-.*"), remove_format))

        # Format for header lines (---, +++)
        header_format = QTextCharFormat()
        header_format.setForeground(QColor("cyan"))
        self.highlightingRules.append((QRegularExpression(r"^(---|\+\+\+).*"), header_format))

        # Format for context/hunk lines (@@ ... @@)
        hunk_format = QTextCharFormat()
        hunk_format.setForeground(QColor("magenta"))
        self.highlightingRules.append((QRegularExpression(r"^@@.*@@.*"), hunk_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)


class DiffDialog(QDialog):
    def __init__(self, diff_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detected Diff / Patch")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout(self)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        # Use a monospaced font for better diff alignment
        font = QFont("Courier New", 10) # Or another monospaced font like Fira Code
        self.diff_view.setFont(font)
        self.diff_view.setPlainText(diff_content) # Display raw diff

        # Apply basic diff syntax highlighting
        self.highlighter = DiffHighlighter(self.diff_view.document())

        layout.addWidget(self.diff_view)

        # Standard buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject) # Close connects to reject

        # Placeholder for Apply button - uncomment and connect later
        # apply_btn = button_box.addButton("Apply Patch", QDialogButtonBox.ButtonRole.AcceptRole)
        # apply_btn.setEnabled(False) # Disable until functionality exists
        # apply_btn.setToolTip("Apply patch (Not Implemented)")
        # apply_btn.clicked.connect(self.accept) # Or custom apply slot

        layout.addWidget(button_box)
        self.setLayout(layout)

        # Optional: Add copy button for the whole diff
        copy_button = QPushButton("Copy Diff")
        copy_button.clicked.connect(self._copy_diff_content)
        button_box.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)

    def _copy_diff_content(self):
        """Copies the entire diff content to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.diff_view.toPlainText())
        # Optional: Add status feedback if needed