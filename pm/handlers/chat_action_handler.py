# pm/handlers/chat_action_handler.py
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
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
        self._is_rendering = False # Flag to prevent re-entrancy issues

        # Connect UI Signals
        self._send_button.clicked.connect(self.handle_send_button_click)
        self._chat_input.textChanged.connect(self._update_send_button_state)

        # Connect Manager/Task Signals
        self._chat_manager.history_changed.connect(self._render_chat_history)
        self._chat_manager.message_content_updated.connect(self._update_message_widget_content)
        self._chat_manager.history_truncated.connect(self._handle_history_truncation)
        self._task_manager.generation_started.connect(self._on_generation_started)
        self._task_manager.generation_finished.connect(self._on_generation_finished)
        self._task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self._task_manager.stream_error.connect(self._handle_stream_error)

        # Initial State
        self._update_send_button_state()
        # Use QTimer to ensure initial render happens after event loop starts
        QTimer.singleShot(0, self._render_chat_history)
        logger.info("ChatActionHandler initialized and connected.")

    @Slot()
    def handle_send_button_click(self):
        if self._task_manager.is_busy():
             logger.warning("Ignoring send click while LLM busy.")
             return
        user_query = self._chat_input.toPlainText().strip()
        if not user_query: return
        logger.info("Sending user message.")
        self._chat_manager.add_user_message(user_query) # Emits history_changed -> _render_chat_history
        self._chat_input.clear()
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder() # Emits history_changed -> _render_chat_history
        # Start generation after UI has potentially updated
        QTimer.singleShot(0, self._start_generation_task)

    def _start_generation_task(self):
        """Helper to start the task after UI updates."""
        history_snapshot = self._chat_manager.get_history_snapshot()
        checked_files = self._get_checked_files()
        project_path = self._get_project_path()
        self._task_manager.start_generation(history_snapshot, checked_files, project_path)


    @Slot()
    def _update_send_button_state(self):
        can_send = bool(self._chat_input.toPlainText().strip()) and not self._task_manager.is_busy()
        self._send_button.setEnabled(can_send)

    @Slot()
    def _render_chat_history(self):
        # Prevent re-entrant calls if signals trigger rapidly
        if self._is_rendering:
            logger.trace("Render already in progress, skipping.")
            return
        self._is_rendering = True
        logger.debug("Rendering chat history...")

        scrollbar = self._chat_list_widget.verticalScrollBar()
        old_value = scrollbar.value()
        was_at_bottom = old_value >= scrollbar.maximum() - 10

        # Block signals on the list widget during modification
        self._chat_list_widget.blockSignals(True)
        try:
            self._chat_list_widget.clear()
            history = self._chat_manager.get_history_snapshot()
            logger.trace(f"Rendering {len(history)} messages...")
            for message_data in history:
                message_id = message_data.get('id')
                if not message_id: continue
                try:
                    # Create widget first
                    chat_widget = ChatMessageWidget(message_data) # No parent needed for setItemWidget
                    chat_widget.deleteRequested.connect(self._handle_delete_request)
                    chat_widget.editRequested.connect(self._handle_edit_request)
                    chat_widget.editSubmitted.connect(self._handle_edit_submit)

                    # Create list item
                    item = QListWidgetItem() # Don't parent here
                    item.setData(Qt.ItemDataRole.UserRole, message_id) # Store ID for later lookup

                    # *** IMPORTANT ORDER ***
                    # 1. Add the item to the list
                    self._chat_list_widget.addItem(item)
                    # 2. Set the custom widget for the item
                    self._chat_list_widget.setItemWidget(item, chat_widget)
                    # 3. Set the size hint AFTER the widget is set
                    #    Use the widget's calculated size hint
                    item.setSizeHint(chat_widget.sizeHint())
                    # logger.trace(f"Render: Set size hint for item {message_id[:8]} to {chat_widget.sizeHint()}")

                except Exception as e:
                    logger.exception(f"Error creating/adding ChatMessageWidget for id {message_id}: {e}")
        finally:
             self._chat_list_widget.blockSignals(False) # Ensure signals unblocked
             self._is_rendering = False # Reset flag

        # Restore scroll position using QTimer to allow layout to settle
        QTimer.singleShot(10, lambda: self._adjust_scroll(was_at_bottom, old_value)) # Slightly longer delay?

        logger.debug("Chat history rendering complete.")

    def _adjust_scroll(self, was_at_bottom, old_value):
        """Adjusts scroll position after render."""
        scrollbar = self._chat_list_widget.verticalScrollBar()
        if was_at_bottom:
            self._chat_list_widget.scrollToBottom()
            logger.trace("Scrolled to bottom post-render.")
        else:
            # Only restore if the max scroll position didn't drastically change
            # This prevents jumping if content made the list much shorter
            if old_value <= scrollbar.maximum():
                 scrollbar.setValue(old_value)
                 logger.trace(f"Restored scroll position to {old_value} post-render.")
            else:
                 self._chat_list_widget.scrollToBottom()
                 logger.trace("Old scroll value invalid after render, scrolled to bottom.")


    @Slot(str, str)
    def _update_message_widget_content(self, message_id: str, full_content: str):
        """Finds the specific ChatMessageWidget, updates its content, and resets size hint."""
        item_to_update = None
        widget_to_update = None

        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                    item_to_update = item
                    widget_to_update = widget
                    break

        if item_to_update and widget_to_update:
            logger.trace(f"Updating content for widget {message_id[:8]}")
            # 1. Update the widget's internal content (this calls widget.updateGeometry())
            widget_to_update.update_content(full_content)
            # 2. Get the NEW size hint from the updated widget
            new_hint = widget_to_update.sizeHint()
            # 3. Update the QListWidgetItem's size hint
            item_to_update.setSizeHint(new_hint)
            logger.trace(f"Update: Set size hint for item {message_id[:8]} to {new_hint}")

            # Schedule scroll check after a short delay to ensure layout updates
            # Crucially, only scroll if the *last* item was the one updated
            is_last_item = (self._chat_list_widget.item(self._chat_list_widget.count() - 1) == item_to_update)
            if is_last_item:
                 QTimer.singleShot(10, lambda item=item_to_update: self._ensure_item_visible(item))
        # else: logger.warning(f"Could not find item/widget to update content for message {message_id}")


    def _ensure_item_visible(self, item: QListWidgetItem):
        """Scrolls to ensure the item is visible, usually the last item."""
        self._chat_list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)
        logger.trace(f"Ensured visibility for updated item.")


    @Slot()
    def _handle_history_truncation(self):
        logger.debug("History truncated signal received. Full re-render handled by history_changed.")
        # No need to call _render_chat_history here, history_changed handles it


    @Slot(str)
    def _handle_delete_request(self, message_id: str):
        if self._task_manager.is_busy():
             QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot delete while LLM is processing.")
             return
        logger.info(f"Handling delete request for message {message_id}")
        # Show confirmation dialog
        reply = QMessageBox.question(self._chat_list_widget.window(), "Confirm Deletion",
                                      "Delete this message and all subsequent messages?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self._chat_manager.delete_message_and_truncate(message_id) # -> history_changed
        else:
            logger.debug("User cancelled message deletion.")


    @Slot(str)
    def _handle_edit_request(self, message_id: str):
        if self._task_manager.is_busy():
             QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot edit while LLM is processing.")
             return
        logger.info(f"Handling edit request for message {message_id}")
        item_to_edit = None
        widget_to_edit = None
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                    item_to_edit = item
                    widget_to_edit = widget
                    break

        if item_to_edit and widget_to_edit:
             widget_to_edit.enter_edit_mode() # Calls updateGeometry internally
             new_hint = widget_to_edit.sizeHint() # Get hint AFTER entering edit mode
             item_to_edit.setSizeHint(new_hint) # Update item hint for edit mode
             logger.trace(f"Edit: Set size hint for item {message_id[:8]} to {new_hint}")
             QTimer.singleShot(0, lambda it=item_to_edit: self._chat_list_widget.scrollToItem(it, QListWidget.ScrollHint.EnsureVisible))


    @Slot(str, str)
    def _handle_edit_submit(self, message_id: str, new_content: str):
        if self._task_manager.is_busy():
             QMessageBox.warning(self._chat_list_widget.window(), "Operation Denied", "Cannot submit edits while LLM is processing.")
             return
        logger.info(f"Handling edit submission for message {message_id}")

        # Find the widget to exit edit mode AFTER processing
        widget_to_exit = None
        for i in range(self._chat_list_widget.count()):
             item = self._chat_list_widget.item(i)
             if item.data(Qt.ItemDataRole.UserRole) == message_id:
                  widget = self._chat_list_widget.itemWidget(item)
                  if isinstance(widget, ChatMessageWidget):
                       widget_to_exit = widget
                       break

        # Update the manager first (no UI changes yet)
        if not self._chat_manager.update_message_content(message_id, new_content):
            if widget_to_exit: widget_to_exit.exit_edit_mode() # Ensure exit even if update fails
            return

        # Truncate history AFTER the edited message (causes history_changed -> re-render)
        self._chat_manager.truncate_history_after(message_id)

        # Add placeholder for AI response (causes history_changed -> re-render)
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()

        # Start generation task after UI updates triggered by history_changed settle
        QTimer.singleShot(0, self._start_generation_task)

        # Explicitly exit edit mode on the specific widget *after* manager updates
        # This might be redundant due to re-render, but ensures state is correct visually.
        # Use a timer to ensure it happens after the render potentially starts.
        if widget_to_exit:
             QTimer.singleShot(0, lambda w=widget_to_exit: w.exit_edit_mode())


    # --- TaskManager Signal Handlers ---
    @Slot()
    def _on_generation_started(self):
         logger.debug("Generation started.")
         self._chat_input.setEnabled(False)
         self._update_send_button_state()

    @Slot(bool)
    def _on_generation_finished(self, stopped_by_user: bool):
         logger.debug(f"Generation finished. Stopped: {stopped_by_user}")
         self._chat_input.setEnabled(True)
         self._update_send_button_state()
         self._chat_input.setFocus()
         self._current_ai_message_id = None # Clear the ID after generation fully stops

    @Slot(str)
    def _handle_stream_chunk(self, chunk: str):
        if self._current_ai_message_id:
            # Update manager's data model (emits message_content_updated -> _update_message_widget_content)
            self._chat_manager.stream_ai_content_update(self._current_ai_message_id, chunk)
        else:
            logger.warning("Received stream chunk but no active AI message ID.")

    @Slot(str)
    def _handle_stream_error(self, error_message: str):
         logger.error(f"Received stream error: {error_message}")
         error_text_display = f"\n\n[ERROR: {error_message}]"
         if self._current_ai_message_id:
             # Add error text to the current AI message placeholder
             self._chat_manager.stream_ai_content_update(self._current_ai_message_id, error_text_display)
             # Make sure the final content with the error is set (might be redundant if stream_ai does it)
             final_content_with_error = ""
             msg = self._chat_manager._find_message_by_id(self._current_ai_message_id)
             if msg: final_content_with_error = msg.get('content', error_text_display)
             # Schedule final UI update using the specific slot AFTER potential streaming updates
             QTimer.singleShot(0, lambda id=self._current_ai_message_id, content=final_content_with_error: self._update_message_widget_content(id, content))

         # Treat error as generation finish (not stopped by user)
         self._on_generation_finished(stopped_by_user=False)

