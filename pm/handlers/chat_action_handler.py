# pm/handlers/chat_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QListWidget, QListWidgetItem, QApplication, QMessageBox
from loguru import logger
from typing import Optional

from ..core.chat_manager import ChatManager
from ..core.task_manager import BackgroundTaskManager
from ..ui.chat_message_widget import ChatMessageWidget

class ChatActionHandler(QObject):
    """Handles user interactions related to the chat interface."""

    request_llm_generation = Signal(list, list, object)

    def __init__(self,
                 chat_input: QPlainTextEdit,
                 send_button: QPushButton,
                 chat_list_widget: QListWidget,
                 chat_manager: ChatManager,
                 task_manager: BackgroundTaskManager,
                 get_checked_files_callback: callable,
                 get_project_path_callback: callable,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._chat_input = chat_input
        self._send_button = send_button
        self._chat_list_widget = chat_list_widget
        self._chat_manager = chat_manager
        self._task_manager = task_manager
        self._get_checked_files = get_checked_files_callback
        self._get_project_path = get_project_path_callback
        self._current_ai_message_id: Optional[str] = None

        # Connect UI Signals
        self._send_button.clicked.connect(self.handle_send_button_click)
        self._chat_input.textChanged.connect(self._update_send_button_state)

        # Connect Manager/Task Signals
        self._chat_manager.history_changed.connect(self._render_chat_history)
        self._chat_manager.message_content_updated.connect(self._update_message_widget_content) # Connect this
        self._chat_manager.history_truncated.connect(self._handle_history_truncation)
        self._task_manager.generation_started.connect(self._on_generation_started)
        self._task_manager.generation_finished.connect(self._on_generation_finished)
        self._task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self._task_manager.stream_error.connect(self._handle_stream_error)

        # Initial State
        self._update_send_button_state()
        self._render_chat_history()
        logger.info("ChatActionHandler initialized and connected.")

    @Slot()
    def handle_send_button_click(self):
        if self._task_manager.is_busy(): logger.warning("Ignoring send click while LLM busy."); return
        user_query = self._chat_input.toPlainText().strip();
        if not user_query: return
        logger.info("Sending user message.")
        self._chat_manager.add_user_message(user_query); self._chat_input.clear()
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        history_snapshot = self._chat_manager.get_history_snapshot()
        checked_files = self._get_checked_files(); project_path = self._get_project_path()
        self._task_manager.start_generation(history_snapshot, checked_files, project_path)

    @Slot()
    def _update_send_button_state(self):
        can_send = bool(self._chat_input.toPlainText().strip()) and not self._task_manager.is_busy()
        self._send_button.setEnabled(can_send)

    @Slot()
    def _render_chat_history(self):
        logger.debug("Rendering chat history...")
        current_scroll = self._chat_list_widget.verticalScrollBar().value()
        max_scroll = self._chat_list_widget.verticalScrollBar().maximum()
        is_at_bottom = current_scroll >= max_scroll - 10 # Check if near bottom

        self._chat_list_widget.clear()
        history = self._chat_manager.get_history_snapshot()
        for message_data in history:
            message_id = message_data.get('id');
            if not message_id: continue
            try:
                chat_widget = ChatMessageWidget(message_data)
                chat_widget.deleteRequested.connect(self._handle_delete_request)
                chat_widget.editRequested.connect(self._handle_edit_request)
                chat_widget.editSubmitted.connect(self._handle_edit_submit)
                item = QListWidgetItem(self._chat_list_widget)
                # --- SET SIZE HINT HERE ---
                item.setSizeHint(chat_widget.sizeHint()) # Use overridden hint
                # --------------------------
                self._chat_list_widget.addItem(item)
                self._chat_list_widget.setItemWidget(item, chat_widget)
                item.setData(Qt.ItemDataRole.UserRole, message_id)
            except Exception as e: logger.exception(f"Error creating/adding ChatMessageWidget for id {message_id}: {e}")

        # Scroll to bottom only if user was already near the bottom
        if is_at_bottom:
            QApplication.processEvents() # Allow layout to update
            self._chat_list_widget.scrollToBottom()
        else:
            # Restore previous scroll position if not at bottom
            self._chat_list_widget.verticalScrollBar().setValue(current_scroll)

        logger.debug("Chat history rendering complete.")

    # --- MODIFY THIS SLOT ---
    @Slot(str, str)
    def _update_message_widget_content(self, message_id: str, full_content: str):
        """Finds the specific ChatMessageWidget, updates its content, and RESETS SIZE HINT."""
        widget_updated = False
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id: # More reliable check
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                    widget.update_content(full_content) # Update the content first
                    # --- CRUCIAL: Update the item's size hint ---
                    item.setSizeHint(widget.sizeHint())
                    # ---------------------------------------------
                    widget_updated = True
                    # Ensure visibility, scroll if it's the last message being updated
                    if i == self._chat_list_widget.count() - 1:
                         self._chat_list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)
                    break # Found and updated
        # if not widget_updated: logger.warning(f"Could not find widget to update content for message {message_id}")

    @Slot()
    def _handle_history_truncation(self): logger.debug("History truncated, triggering re-render.")

    @Slot(str)
    def _handle_delete_request(self, message_id: str):
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot delete messages while the LLM is processing."); return
        logger.info(f"Handling delete request for message {message_id}")
        self._chat_manager.delete_message_and_truncate(message_id)

    @Slot(str)
    def _handle_edit_request(self, message_id: str):
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot edit messages while the LLM is processing."); return
        logger.info(f"Handling edit request for message {message_id}")
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                    widget.enter_edit_mode()
                    item.setSizeHint(widget.sizeHint()) # Update hint for edit controls
                    self._chat_list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)
                    break

    @Slot(str, str)
    def _handle_edit_submit(self, message_id: str, new_content: str):
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot submit edits while the LLM is processing."); return
        logger.info(f"Handling edit submission for message {message_id}")
        updated = self._chat_manager.update_message_content(message_id, new_content);
        if not updated: return
        self._chat_manager.truncate_history_after(message_id)
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        history_snapshot = self._chat_manager.get_history_snapshot()
        checked_files = self._get_checked_files(); project_path = self._get_project_path()
        self._task_manager.start_generation(history_snapshot, checked_files, project_path)

    # TaskManager Signal Handlers
    @Slot()
    def _on_generation_started(self): logger.debug("Generation started."); self._chat_input.setEnabled(False); self._update_send_button_state()
    @Slot(bool)
    def _on_generation_finished(self, stopped_by_user: bool): logger.debug(f"Generation finished. Stopped: {stopped_by_user}"); self._chat_input.setEnabled(True); self._update_send_button_state(); self._chat_input.setFocus(); self._current_ai_message_id = None
    @Slot(str)
    def _handle_stream_chunk(self, chunk: str):
        if self._current_ai_message_id: self._chat_manager.stream_ai_content_update(self._current_ai_message_id, chunk)
        else: logger.warning("Received stream chunk but no active AI message ID.")
    @Slot(str)
    def _handle_stream_error(self, error_message: str):
         logger.error(f"Received stream error: {error_message}")
         if self._current_ai_message_id:
             error_text = f"\n\n[ERROR: {error_message}]"; self._chat_manager.stream_ai_content_update(self._current_ai_message_id, error_text)
             try: self._update_message_widget_content(self._current_ai_message_id, self._chat_manager._find_message_by_id(self._current_ai_message_id)['content'])
             except Exception as e: logger.warning(f"Could not update widget with final error message: {e}")
         self._on_generation_finished(stopped_by_user=False)
