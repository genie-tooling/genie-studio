# pm/handlers/chat_action_handler.py
import re
import os # For line ending normalization
from pathlib import Path # For path operations
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QListWidget, QListWidgetItem, QApplication, QMessageBox
from loguru import logger
from typing import Optional, List

# Updated Imports: Core components instead of MainWindow
from ..core.app_core import AppCore
from ..core.chat_manager import ChatManager
from ..core.task_manager import BackgroundTaskManager
from ..ui.chat_message_widget import ChatMessageWidget

# Helper to normalize line endings
def normalize_newlines(text: str) -> str:
    if text is None: return ""
    return text.replace('\r\n', '\n').replace('\r', '\n')

class ChatActionHandler(QObject):
    """Handles user interactions related to the chat interface."""

    potential_change_detected = Signal(str) # Emits content of blocks with ACTUAL changes

    def __init__(self,
                 core: AppCore,
                 chat_input: QPlainTextEdit,
                 send_button: QPushButton,
                 chat_list_widget: QListWidget,
                 get_checked_files_callback: callable,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._core = core
        self._chat_input = chat_input
        self._send_button = send_button
        self._chat_list_widget = chat_list_widget
        self._get_checked_files = get_checked_files_callback
        self._chat_manager: ChatManager = core.chat
        self._task_manager: BackgroundTaskManager = core.tasks
        self._current_ai_message_id: Optional[str] = None
        self._is_rendering = False
        self._current_full_ai_response: str = "" # Store full response during generation

        self._connect_signals()
        self._update_send_button_state()
        QTimer.singleShot(0, self._render_chat_history)
        logger.info("ChatActionHandler initialized and connected.")

    def _connect_signals(self):
        self._send_button.clicked.connect(self.handle_send_button_click)
        self._chat_input.textChanged.connect(self._update_send_button_state)
        self._chat_manager.history_changed.connect(self._render_chat_history)
        self._chat_manager.message_content_updated.connect(self._update_message_widget_content)
        self._chat_manager.history_truncated.connect(self._handle_history_truncation)
        self._task_manager.generation_started.connect(self._on_generation_started)
        self._task_manager.generation_finished.connect(self._on_generation_finished)
        self._task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self._task_manager.stream_error.connect(self._handle_stream_error)
        # Connect to Change Queue status
        if hasattr(self.parent(), 'ui') and hasattr(self.parent().ui, 'change_queue_widget'):
            logger.debug("Connecting ChatActionHandler to ChangeQueueWidget status.")
            change_queue = getattr(self.parent().ui, 'change_queue_widget', None)
            if change_queue and hasattr(change_queue, 'queue_status_changed'):
                 change_queue.queue_status_changed.connect(self._update_send_button_state)
            else: logger.error("ChatActionHandler could not find change_queue_widget or its signal!")
        else: logger.error("ChatActionHandler could not find parent.ui or parent.ui.change_queue_widget!")


    @Slot()
    def handle_send_button_click(self):
        if self._task_manager.is_busy():
             logger.warning("Ignoring send click while LLM busy."); return
        queue_widget = None
        if hasattr(self.parent(), 'ui') and hasattr(self.parent().ui, 'change_queue_widget'):
            queue_widget = getattr(self.parent().ui, 'change_queue_widget', None)
        if queue_widget and not queue_widget.is_empty():
              QMessageBox.warning(self._chat_input.window(), "Action Denied", "Please apply or reject pending file changes before sending.")
              logger.warning("Ignoring send click while change queue is populated."); return

        user_query = self._chat_input.toPlainText().strip()
        if not user_query: return
        logger.info("Sending user message.")
        self._chat_manager.add_user_message(user_query)
        self._chat_input.clear()
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        self._current_full_ai_response = "" # Reset accumulator for new message
        QTimer.singleShot(0, self._start_generation_task)

    def _start_generation_task(self):
        logger.info("ChatActionHandler: _start_generation_task called.")
        history_snapshot = self._chat_manager.get_history_snapshot()
        checked_files = self._get_checked_files()
        project_path = self._core.workspace.project_path
        disable_critic = self._core.settings.get_setting('disable_critic_workflow', False)
        logger.debug(f"Starting generation with {len(history_snapshot)} items, {len(checked_files)} files (Critic Disabled: {disable_critic}).")
        self._task_manager.start_generation(history_snapshot, checked_files, project_path, disable_critic=disable_critic)

    @Slot()
    def _update_send_button_state(self):
        queue_is_populated = False
        queue_widget = None
        if hasattr(self.parent(), 'ui') and hasattr(self.parent().ui, 'change_queue_widget'):
             queue_widget = getattr(self.parent().ui, 'change_queue_widget', None)
        if queue_widget:
            try: queue_is_populated = not queue_widget.is_empty()
            except Exception as e: logger.error(f"Error checking change queue state: {e}")

        can_send = bool(self._chat_input.toPlainText().strip()) and not self._task_manager.is_busy() and not queue_is_populated
        self._send_button.setEnabled(can_send)
        can_input = not self._task_manager.is_busy() and not queue_is_populated
        self._chat_input.setEnabled(can_input)
        if queue_is_populated: self._chat_input.setPlaceholderText("Clear change queue before sending new messages.")
        else: self._chat_input.setPlaceholderText("Enter your message or /command...")

    @Slot()
    def _render_chat_history(self):
        # This function remains the same
        if self._is_rendering: logger.trace("Render already in progress."); return
        self._is_rendering = True; logger.debug("Rendering chat history...")
        scrollbar = self._chat_list_widget.verticalScrollBar(); old_value = scrollbar.value(); was_at_bottom = old_value >= scrollbar.maximum() - 10
        self._chat_list_widget.blockSignals(True)
        try:
            self._chat_list_widget.clear(); history = self._chat_manager.get_history_snapshot()
            logger.debug(f"_render_chat_history: Rendering {len(history)} messages...")
            for message_data in history:
                message_id = message_data.get('id')
                if not message_id: continue
                try:
                    chat_widget = ChatMessageWidget(message_data)
                    chat_widget.deleteRequested.connect(self._handle_delete_request)
                    chat_widget.editRequested.connect(self._handle_edit_request)
                    chat_widget.editSubmitted.connect(self._handle_edit_submit)
                    item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, message_id)
                    self._chat_list_widget.addItem(item); self._chat_list_widget.setItemWidget(item, chat_widget)
                    item.setSizeHint(chat_widget.sizeHint())
                except Exception as e: logger.exception(f"Error creating/adding widget id {message_id}: {e}")
        finally: self._chat_list_widget.blockSignals(False); self._is_rendering = False
        QTimer.singleShot(10, lambda: self._adjust_scroll(was_at_bottom, old_value))
        logger.debug("Chat history rendering complete.")

    def _adjust_scroll(self, was_at_bottom, old_value):
        # This function remains the same
        scrollbar = self._chat_list_widget.verticalScrollBar()
        if was_at_bottom: self._chat_list_widget.scrollToBottom(); logger.trace("Scrolled bottom.")
        else:
            if old_value <= scrollbar.maximum(): scrollbar.setValue(old_value); logger.trace(f"Restored scroll {old_value}.")
            else: self._chat_list_widget.scrollToBottom(); logger.trace("Old scroll invalid, scrolled bottom.")

    @Slot(str, str)
    def _update_message_widget_content(self, message_id: str, full_content: str):
        # This function remains the same
        item_to_update = None; widget_to_update = None
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget): item_to_update = item; widget_to_update = widget; break
        if item_to_update and widget_to_update:
            logger.trace(f"Updating content for widget {message_id[:8]}")
            widget_to_update.update_content(full_content); new_hint = widget_to_update.sizeHint()
            item_to_update.setSizeHint(new_hint); logger.trace(f"Update: Set size hint {new_hint}")
            is_last = (self._chat_list_widget.item(self._chat_list_widget.count() - 1) == item_to_update)
            if is_last: QTimer.singleShot(10, lambda item=item_to_update: self._ensure_item_visible(item))

    def _ensure_item_visible(self, item: QListWidgetItem):
        self._chat_list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible); logger.trace(f"Ensured visibility.")

    @Slot()
    def _handle_history_truncation(self):
        logger.debug("History truncated signal received. Full re-render handles UI.")

    @Slot(str)
    def _handle_delete_request(self, message_id: str):
        # This function remains the same
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot delete while LLM processing."); return
        logger.info(f"Handling delete request for message {message_id}")
        reply = QMessageBox.question(self._chat_list_widget.window(), "Confirm Deletion", "Delete this and subsequent messages?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes: self._chat_manager.delete_message_and_truncate(message_id)
        else: logger.debug("User cancelled message deletion.")

    @Slot(str)
    def _handle_edit_request(self, message_id: str):
        # This function remains the same
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot edit while LLM processing."); return
        logger.info(f"Handling edit request for message {message_id}")
        item_to_edit = None; widget_to_edit = None
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget): item_to_edit = item; widget_to_edit = widget; break
        if item_to_edit and widget_to_edit:
             widget_to_edit.enter_edit_mode(); new_hint = widget_to_edit.sizeHint()
             item_to_edit.setSizeHint(new_hint); logger.trace(f"Edit: Set hint {new_hint}")
             QTimer.singleShot(0, lambda it=item_to_edit: self._chat_list_widget.scrollToItem(it, QListWidget.ScrollHint.EnsureVisible))

    @Slot(str, str)
    def _handle_edit_submit(self, message_id: str, new_content: str):
        # This function remains the same
        if self._task_manager.is_busy(): QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot submit edits while LLM processing."); return
        logger.info(f"Handling edit submission for message {message_id}")
        widget_to_exit = None
        for i in range(self._chat_list_widget.count()):
             item = self._chat_list_widget.item(i)
             if item.data(Qt.ItemDataRole.UserRole) == message_id:
                  widget = self._chat_list_widget.itemWidget(item)
                  if isinstance(widget, ChatMessageWidget): widget_to_exit = widget; break
        logger.debug(f"Edit Submit: Updating content for {message_id[:8]}...")
        if not self._chat_manager.update_message_content(message_id, new_content):
            logger.warning(f"Edit Submit: Update failed for {message_id[:8]}. Aborting.")
            if widget_to_exit: widget_to_exit.exit_edit_mode(); return
        logger.debug(f"Edit Submit: Truncating history after {message_id[:8]}...")
        self._chat_manager.truncate_history_after(message_id)
        logger.debug(f"Edit Submit: Adding AI placeholder...")
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        self._current_full_ai_response = "" # Reset accumulator
        logger.debug(f"Edit Submit: Scheduling generation task start...")
        QTimer.singleShot(0, self._start_generation_task)

    @Slot()
    def _on_generation_started(self):
         logger.debug("ChatActionHandler: Generation started, updating UI state.")
         self._update_send_button_state()
         self._current_full_ai_response = "" # Ensure accumulator is clear

    @Slot(bool)
    def _on_generation_finished(self, stopped_by_user: bool):
         logger.debug(f"ChatActionHandler: Generation finished (Stopped: {stopped_by_user}), updating UI state.")
         if self._current_ai_message_id:
              self._check_for_pending_changes(self._current_full_ai_response, self._current_ai_message_id)
         else:
              logger.debug("Generation finished, but no current AI message ID to check for changes.")

         self._update_send_button_state()
         self._chat_input.setFocus()
         self._current_ai_message_id = None
         self._current_full_ai_response = "" # Clear accumulator

    @Slot(str)
    def _handle_stream_chunk(self, chunk: str):
        if self._current_ai_message_id:
            self._current_full_ai_response += chunk
            self._chat_manager.stream_ai_content_update(self._current_ai_message_id, chunk)
        else:
            logger.trace("Received stream chunk but no active AI message ID.")

    @Slot(str)
    def _handle_stream_error(self, error_message: str):
        logger.error(f"ChatActionHandler received stream error: {error_message}")
        error_text_display = f"\n\n[ERROR: {error_message}]"
        if self._current_ai_message_id:
             self._current_full_ai_response += error_text_display
             self._chat_manager.stream_ai_content_update(self._current_ai_message_id, error_text_display)
        QTimer.singleShot(0, lambda: self._on_generation_finished(stopped_by_user=False))

    # <<< Added Debug Logging to Comparison Logic >>>
    def _check_for_pending_changes(self, full_ai_content: str, message_id: str):
        logger.debug("ChatActionHandler: Checking for pending changes in AI content...")
        change_pattern = re.compile(
            r"### START FILE: (?P<filepath>.*?) ###\n(?P<content>.*?)\n### END FILE: (?P=filepath) ###",
            re.DOTALL | re.MULTILINE
        )
        matches = list(change_pattern.finditer(full_ai_content))

        if not matches:
            logger.debug("No file change markers found.")
            self._chat_manager.finalize_ai_message(message_id, full_ai_content)
            return

        actual_changes_found = False
        content_with_actual_changes = ""

        for match in matches:
            try:
                relative_path_str = match.group('filepath').strip()
                proposed_content_raw = match.group('content')
                if not relative_path_str: logger.warning("Empty file path."); continue

                abs_path = self._core.workspace.project_path / relative_path_str
                if not abs_path.is_file():
                    logger.warning(f"File path '{abs_path}' not found. Treating as change.")
                    actual_changes_found = True; content_with_actual_changes += match.group(0) + "\n\n"; continue

                try:
                    original_content_raw = abs_path.read_text(encoding='utf-8')
                except Exception as e:
                    logger.error(f"Failed read original {abs_path}: {e}")
                    logger.warning(f"Treating '{relative_path_str}' as change due to read error.")
                    actual_changes_found = True; content_with_actual_changes += match.group(0) + "\n\n"; continue

                # Compare (after normalizing line endings)
                norm_original = normalize_newlines(original_content_raw)
                norm_proposed = normalize_newlines(proposed_content_raw)

                # +++ Add Detailed Logging +++
                logger.debug(f"--- Comparing Content for: {relative_path_str} ---")
                orig_snippet = norm_original[:200] + ('...' if len(norm_original) > 200 else '')
                prop_snippet = norm_proposed[:200] + ('...' if len(norm_proposed) > 200 else '')
                logger.debug(f"Original Normalized Snippet:\n{orig_snippet}")
                logger.debug(f"Proposed Normalized Snippet:\n{prop_snippet}")
                comparison_result = norm_original != norm_proposed
                logger.debug(f"Comparison Result (norm_original != norm_proposed): {comparison_result}")
                # +++ End Detailed Logging +++

                if comparison_result: # Use the stored result
                    logger.info(f"Actual change detected for: {relative_path_str}")
                    actual_changes_found = True
                    content_with_actual_changes += match.group(0) + "\n\n" # Add block with diff
                else:
                    logger.info(f"No actual change detected for: {relative_path_str} (content matches disk).")

            except Exception as e:
                 logger.exception(f"Error processing change block during comparison: {e}")
                 actual_changes_found = True; content_with_actual_changes += match.group(0) + "\n\n"

        if actual_changes_found:
            logger.info("ChatActionHandler: Emitting potential_change_detected with differing blocks.")
            self.potential_change_detected.emit(content_with_actual_changes.strip())
            display_text = f"[File change detected ({content_with_actual_changes.count('### START FILE:')} block(s)) - review in Change Queue]"
            self._chat_manager.finalize_ai_message(message_id, display_text)
            QTimer.singleShot(0, lambda id=message_id, txt=display_text: self._update_message_widget_content(id, txt))
        else:
            logger.info("ChatActionHandler: No actual file changes detected despite markers. Displaying full response.")
            self._chat_manager.finalize_ai_message(message_id, full_ai_content)
            QTimer.singleShot(0, lambda id=message_id, content=full_ai_content: self._update_message_widget_content(id, content))

