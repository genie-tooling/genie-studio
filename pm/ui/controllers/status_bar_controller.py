# pm/ui/controllers/status_bar_controller.py
from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt
from PySide6.QtWidgets import QStatusBar, QLabel
from loguru import logger
from typing import Optional

class StatusBarController(QObject):
    """Manages the content and appearance of the application's status bar."""
    def __init__(self, status_bar: QStatusBar, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._status_bar = status_bar
        self._status_label: QLabel = None
        self._token_label: QLabel = None
        self._current_max_tokens = 0 # Store the limit locally

        self._setup_widgets()
        logger.debug("StatusBarController initialized.")

    def _setup_widgets(self):
        """Creates and adds widgets to the status bar."""
        self._status_label = QLabel("Ready.")
        self._status_bar.addWidget(self._status_label, 1) # Stretch factor 1

        self._token_label = QLabel("Selected: 0 / 0")
        self._token_label.setObjectName("token_label")
        self._token_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_bar.addPermanentWidget(self._token_label)
        logger.debug("StatusBarController: Widgets added.")

    @Slot(str)
    @Slot(str, int)
    def update_status(self, message: str, timeout: int = 0):
        """Updates the main status message, optionally clearing after a timeout."""
        logger.debug(f"StatusBar: Updating status: '{message}' (Timeout: {timeout}ms)")
        if self._status_label:
            self._status_label.setText(message)
            if timeout > 0:
                # Use lambda to capture current message for accurate clear check
                expected_message = message
                QTimer.singleShot(timeout, lambda: self._clear_status(expected_message))
        else:
            logger.error("StatusBarController: Status label is None, cannot update.")

    def _clear_status(self, expected_message: str):
        """Clears the status message if it hasn't changed."""
        if self._status_label and self._status_label.text() == expected_message:
             self._status_label.setText("Ready.")
             logger.debug("StatusBar: Status cleared by timer.")

    @Slot(int, int)
    def update_token_count(self, selected_tokens: int, max_tokens: int):
        """Updates the token count display."""
        self._current_max_tokens = max_tokens # Update stored limit
        logger.trace(f"StatusBar: Updating token display: Selected={selected_tokens} / Max={max_tokens}")
        if self._token_label:
            display_text = f"Selected: {selected_tokens:,} / {max_tokens:,}"
            self._token_label.setText(display_text)
            # Apply warning style if over limit
            if selected_tokens > max_tokens and max_tokens > 0:
                self._token_label.setStyleSheet("color: orange;")
            else:
                self._token_label.setStyleSheet("") # Reset style
        else:
            logger.error("StatusBarController: Token label is None, cannot update.")

    @Slot(int)
    def update_token_limit(self, max_tokens: int):
        """Updates only the maximum token limit part of the display."""
        # This might be called when the limit changes but selection hasn't yet.
        self._current_max_tokens = max_tokens
        # Re-render the display using the last known selected count
        # This avoids needing to recalculate selected tokens immediately
        current_text = self._token_label.text()
        try:
             # Extract current selected count if possible
             parts = current_text.split('/')
             selected_part = parts[0].replace("Selected:", "").replace(",", "").strip()
             current_selected = int(selected_part) if selected_part else 0
        except Exception:
             current_selected = 0 # Fallback if parsing fails
        logger.debug(f"StatusBar: Updating token limit display only. Max={max_tokens}")
        self.update_token_count(current_selected, max_tokens)

