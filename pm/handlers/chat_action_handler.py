# pm/handlers/chat_action_handler.py
import re
import os
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer
from PyQt6.QtWidgets import QPlainTextEdit, QPushButton, QListWidget, QListWidgetItem, QApplication, QMessageBox
from loguru import logger
from typing import Optional, List

from ..core.app_core import AppCore
from ..core.chat_manager import ChatManager
from ..core.task_manager import BackgroundTaskManager
from ..ui.chat_message_widget import ChatMessageWidget

def normalize_newlines(text: Optional[str]) -> str:
    """Replaces CRLF and CR with LF."""
    if text is None:
        return ""
    return text.replace('\r\n', '\n').replace('\r', '\n')

class ChatActionHandler(QObject):
    """Handles user interactions related to the chat interface."""
    potential_change_detected = pyqtSignal(str)

    def __init__(self, core: AppCore, chat_input: QPlainTextEdit, send_button: QPushButton, chat_list_widget: QListWidget, get_checked_files_callback: callable, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._core = core; self._chat_input = chat_input; self._send_button = send_button
        self._chat_list_widget = chat_list_widget; self._get_checked_files = get_checked_files_callback
        self._chat_manager: ChatManager = core.chat; self._task_manager: BackgroundTaskManager = core.tasks
        self._current_ai_message_id: Optional[str] = None; self._is_rendering = False
        self._current_full_ai_response: str = ""
        self._connect_pyqtSignals(); self._update_send_button_state()
        QTimer.singleShot(0, self._render_chat_history)
        logger.info("ChatActionHandler initialized and connected.")

    def _connect_pyqtSignals(self):
        self._send_button.clicked.connect(self.handle_send_button_click)
        self._chat_input.textChanged.connect(self._update_send_button_state)
        self._chat_manager.history_changed.connect(self._render_chat_history)
        self._chat_manager.message_content_updated.connect(self._update_message_widget_content)
        self._chat_manager.history_truncated.connect(self._handle_history_truncation)
        self._task_manager.generation_started.connect(self._on_generation_started)
        self._task_manager.generation_finished.connect(self._on_generation_finished)
        self._task_manager.stream_chunk.connect(self._handle_stream_chunk)
        self._task_manager.stream_error.connect(self._handle_stream_error)
        try: # Safely connect to change queue
            # Access change queue through parent's UI attribute if possible
            parent_ui = getattr(self.parent(), 'ui', None)
            change_queue = getattr(parent_ui, 'change_queue_widget', None) if parent_ui else None
            if change_queue and hasattr(change_queue, 'queue_status_changed'):
                 change_queue.queue_status_changed.connect(self._update_send_button_state)
                 logger.debug("ChatActionHandler connected to ChangeQueueWidget status.")
            else:
                 logger.warning("ChatActionHandler could not connect to ChangeQueueWidget status!")
        except AttributeError:
            logger.error("ChatActionHandler could not find parent UI or ChangeQueueWidget.")

    @pyqtSlot()
    def handle_send_button_click(self):
        if self._task_manager.is_busy():
            logger.warning("Ignoring send click while LLM busy.")
            return
        try:
            parent_ui = getattr(self.parent(), 'ui', None)
            queue_widget = getattr(parent_ui, 'change_queue_widget', None) if parent_ui else None
        except AttributeError:
            queue_widget = None

        if queue_widget and not queue_widget.is_empty():
              QMessageBox.warning(self._chat_input.window(), "Action Denied", "Please apply or reject pending file changes before sending.")
              return

        user_query = self._chat_input.toPlainText().strip()
        if not user_query:
            return

        logger.info("Sending user message.")
        self._chat_manager.add_user_message(user_query)
        self._chat_input.clear()
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        self._current_full_ai_response = ""
        QTimer.singleShot(0, self._start_generation_task) # Use timer to ensure UI updates first

    def _start_generation_task(self):
        logger.info("ChatActionHandler: _start_generation_task called.")
        history_snapshot = self._chat_manager.get_history_snapshot()
        checked_files = self._get_checked_files()
        project_path = self._core.workspace.project_path
        disable_critic = self._core.settings.get_setting('disable_critic_workflow', False)
        logger.debug(f"Starting generation with {len(history_snapshot)} history items, {len(checked_files)} checked files (Critic Disabled: {disable_critic}).")
        # Ensure task manager has the latest services (might have changed)
        self._task_manager.set_services(self._core.llm.get_model_service(), self._core.llm.get_summarizer_service())
        self._task_manager.start_generation(history_snapshot, checked_files, project_path, disable_critic=disable_critic)

    @pyqtSlot()
    def _update_send_button_state(self):
        queue_is_populated = False; queue_widget = None
        try:
            parent_ui = getattr(self.parent(), 'ui', None)
            queue_widget = getattr(parent_ui, 'change_queue_widget', None) if parent_ui else None
        except AttributeError: pass

        if queue_widget:
            try: queue_is_populated = not queue_widget.is_empty()
            except Exception as e: logger.error(f"Error checking change queue state: {e}")

        llm_is_busy = self._task_manager.is_busy()
        can_send = bool(self._chat_input.toPlainText().strip()) and not llm_is_busy and not queue_is_populated
        can_input = not llm_is_busy and not queue_is_populated

        self._send_button.setEnabled(can_send)
        self._chat_input.setEnabled(can_input)

        if llm_is_busy:
            placeholder = "LLM is processing..."
        elif queue_is_populated:
            placeholder = "Clear change queue before sending new messages."
        else:
            placeholder = "Enter your message or /command..."
        self._chat_input.setPlaceholderText(placeholder)

    @pyqtSlot()
    def _render_chat_history(self):
        if self._is_rendering:
            logger.trace("Skipping render, already rendering.")
            return

        self._is_rendering = True
        logger.debug("Rendering chat history...")
        scrollbar = self._chat_list_widget.verticalScrollBar();
        old_value = scrollbar.value();
        was_at_bottom = old_value >= scrollbar.maximum() - 10 # Heuristic for being at bottom
        self._chat_list_widget.blockSignals(True)
        try:
            self._chat_list_widget.clear()
            history = self._chat_manager.get_history_snapshot()
            for message_data in history:
                message_id = message_data.get('id')
                if not message_id:
                    logger.warning("Skipping message with no ID.")
                    continue
                try:
                    chat_widget = ChatMessageWidget(message_data);
                    chat_widget.deleteRequested.connect(self._handle_delete_request)
                    chat_widget.editRequested.connect(self._handle_edit_request)
                    chat_widget.editSubmitted.connect(self._handle_edit_submit)
                    # chat_widget.copyRequested.connect(...) # If copy needed
                    item = QListWidgetItem();
                    item.setData(Qt.ItemDataRole.UserRole, message_id)
                    item.setSizeHint(chat_widget.sizeHint()) # Set hint BEFORE adding
                    self._chat_list_widget.addItem(item)
                    self._chat_list_widget.setItemWidget(item, chat_widget);
                except Exception as e:
                    logger.exception(f"Error creating/adding widget id {message_id}: {e}")
        finally:
            self._chat_list_widget.blockSignals(False)
            self._is_rendering = False

        # Adjust scroll after render, slightly delayed
        QTimer.singleShot(10, lambda b=was_at_bottom, v=old_value: self._adjust_scroll(b, v))
        logger.debug("Chat history rendering complete.")

    def _adjust_scroll(self, was_at_bottom, old_value):
        scrollbar = self._chat_list_widget.verticalScrollBar()
        if was_at_bottom:
            self._chat_list_widget.scrollToBottom()
        elif old_value <= scrollbar.maximum():
             # Restore previous position only if valid
             scrollbar.setValue(old_value)
        else:
             # Fallback if old position is invalid after render
             self._chat_list_widget.scrollToBottom()

    @pyqtSlot(str, str)
    def _update_message_widget_content(self, message_id: str, full_content: str):
        item_to_update = None; widget_to_update = None
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                    item_to_update = item; widget_to_update = widget; break
        if item_to_update and widget_to_update:
            widget_to_update.update_content(full_content);
            new_hint = widget_to_update.sizeHint()
            item_to_update.setSizeHint(new_hint)
            # Ensure visible if it's the last item (streaming)
            is_last = (self._chat_list_widget.row(item_to_update) == self._chat_list_widget.count() - 1)
            if is_last:
                 QTimer.singleShot(10, lambda item=item_to_update: self._ensure_item_visible(item))

    def _ensure_item_visible(self, item: QListWidgetItem):
        if item: # Check if item still exists
            self._chat_list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)

    @pyqtSlot()
    def _handle_history_truncation(self):
        logger.debug("History truncated pyqtSignal received.")
        # Re-render handled by history_changed pyqtSignal

    @pyqtSlot(str)
    def _handle_delete_request(self, message_id: str):
        if self._task_manager.is_busy():
            QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot delete while LLM processing.")
            return
        logger.info(f"Handling delete request for message {message_id}")
        reply = QMessageBox.question(self._chat_list_widget.window(), "Confirm Deletion", "Delete this and subsequent messages?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            self._chat_manager.delete_message_and_truncate(message_id)

    @pyqtSlot(str)
    def _handle_edit_request(self, message_id: str):
        if self._task_manager.is_busy():
            QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot edit while LLM processing.")
            return
        logger.info(f"Handling edit request for message {message_id}")
        item_to_edit = None; widget_to_edit = None
        for i in range(self._chat_list_widget.count()):
            item = self._chat_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == message_id:
                widget = self._chat_list_widget.itemWidget(item)
                if isinstance(widget, ChatMessageWidget):
                     item_to_edit = item; widget_to_edit = widget; break
        if item_to_edit and widget_to_edit:
             widget_to_edit.enter_edit_mode();
             # Update size hint after entering edit mode
             new_hint = widget_to_edit.sizeHint()
             item_to_edit.setSizeHint(new_hint)
             QTimer.singleShot(0, lambda it=item_to_edit: self._chat_list_widget.scrollToItem(it, QListWidget.ScrollHint.EnsureVisible))

    @pyqtSlot(str, str)
    def _handle_edit_submit(self, message_id: str, new_content: str):
        if self._task_manager.is_busy():
            QMessageBox.warning(self._chat_list_widget.window(), "Denied", "Cannot submit edits while LLM processing.")
            return
        logger.info(f"Handling edit submission for message {message_id}")
        # Find widget just to call exit_edit_mode if update fails
        widget_to_exit = None
        for i in range(self._chat_list_widget.count()):
             item = self._chat_list_widget.item(i)
             if item.data(Qt.ItemDataRole.UserRole) == message_id:
                  widget = self._chat_list_widget.itemWidget(item)
                  if isinstance(widget, ChatMessageWidget):
                      widget_to_exit = widget; break

        logger.debug(f"Edit Submit: Updating content for {message_id[:8]}...")
        if not self._chat_manager.update_message_content(message_id, new_content):
            logger.warning(f"Edit Submit: Update failed for {message_id[:8]}. Aborting.")
            if widget_to_exit: widget_to_exit.exit_edit_mode(); # Exit edit mode on failure
            return

        # Truncate history *after* the updated message
        logger.debug(f"Edit Submit: Truncating history after {message_id[:8]}...")
        self._chat_manager.truncate_history_after(message_id)

        # Add AI placeholder for the new response
        logger.debug(f"Edit Submit: Adding AI placeholder...")
        self._current_ai_message_id = self._chat_manager.add_ai_placeholder()
        self._current_full_ai_response = ""

        # Start generation task
        logger.debug(f"Edit Submit: Scheduling generation task start...")
        QTimer.singleShot(0, self._start_generation_task)

    @pyqtSlot()
    def _on_generation_started(self):
         logger.debug("ChatActionHandler: Generation started.");
         self._update_send_button_state();
         self._current_full_ai_response = "" # Reset buffer

    @pyqtSlot(bool)
    def _on_generation_finished(self, stopped_by_user: bool):
         logger.debug(f"ChatActionHandler: Generation finished (Stopped: {stopped_by_user}).")
         if self._current_ai_message_id:
              # Use the accumulated response buffer for checking changes
              self._check_for_pending_changes(self._current_full_ai_response, self._current_ai_message_id)
         self._update_send_button_state();
         self._chat_input.setFocus()
         # Clear state AFTER potentially using it in _check_for_pending_changes
         self._current_ai_message_id = None;
         self._current_full_ai_response = ""

    @pyqtSlot(str)
    def _handle_stream_chunk(self, chunk: str):
        if self._current_ai_message_id:
            self._current_full_ai_response += chunk # Accumulate full response
            # Update manager (which updates UI dynamically)
            self._chat_manager.stream_ai_content_update(self._current_ai_message_id, chunk)

    @pyqtSlot(str)
    def _handle_stream_error(self, error_message: str):
        logger.error(f"ChatActionHandler received stream error: {error_message}")
        error_text_display = f"\n\n[ERROR: {error_message}]"
        if self._current_ai_message_id:
             # Append error to buffer and update UI
             self._current_full_ai_response += error_text_display
             self._chat_manager.stream_ai_content_update(self._current_ai_message_id, error_text_display)
        # Ensure UI state resets even on error
        QTimer.singleShot(0, lambda: self._on_generation_finished(stopped_by_user=False))

    def _check_for_pending_changes(self, full_ai_content: str, message_id: str):
        """Checks AI content for file markers and emits pyqtSignal if actual changes found."""
        logger.debug(f"ChatActionHandler: Checking for pending changes in AI content (Msg ID: {message_id[:8]})...")
        change_pattern = re.compile(
            r"### START FILE: (?P<filepath>.*?) ###\n(?P<content>.*?)\n### END FILE: (?P=filepath) ###",
            re.DOTALL | re.MULTILINE
        )
        matches = list(change_pattern.finditer(full_ai_content))

        if not matches:
            logger.debug("No file change markers found. Finalizing AI message normally.")
            self._chat_manager.finalize_ai_message(message_id, full_ai_content)
            return

        actual_changes_found = False
        content_with_actual_changes = "" # Collect only blocks with actual changes
        logger.info(f"Found {len(matches)} potential file change blocks.")

        for i, match in enumerate(matches):
            logger.debug(f"--- Processing potential change block {i+1}/{len(matches)} ---")
            is_actual_change = False # Assume no change initially for this block
            try:
                relative_path_str = match.group('filepath').strip()
                proposed_content_raw = match.group('content') # Keep original line endings for now
                if not relative_path_str:
                    logger.warning(f"Block {i+1}: Empty file path."); continue
                logger.debug(f"Block {i+1}: Filepath='{relative_path_str}'")

                abs_path = self._core.workspace.project_path / relative_path_str
                if not abs_path.is_file():
                    logger.warning(f"Block {i+1}: File path '{abs_path}' not found. Treating as change.")
                    is_actual_change = True # Treat new files as changes
                else:
                    try:
                        original_content_raw = abs_path.read_text(encoding='utf-8')
                        # --- FIX: Compare using normalized newlines ---
                        norm_original = normalize_newlines(original_content_raw)
                        norm_proposed = normalize_newlines(proposed_content_raw)
                        # ---------------------------------------------

                        # Detailed Logging for comparison
                        orig_len = len(norm_original); prop_len = len(norm_proposed)
                        logger.debug(f"Block {i+1}: Comparing Content for: {relative_path_str} (Orig Len: {orig_len}, Prop Len: {prop_len})")
                        comparison_result = (norm_original != norm_proposed)
                        logger.debug(f"Block {i+1}: Comparison Result (norm_original != norm_proposed): {comparison_result}")

                        if comparison_result: # Content differs
                            logger.info(f"Block {i+1}: Actual change detected for: {relative_path_str}")
                            is_actual_change = True
                        else:
                            logger.info(f"Block {i+1}: No actual change detected (content matches disk): {relative_path_str}")
                    except Exception as e:
                        logger.error(f"Block {i+1}: Failed read/compare original {abs_path}: {e}")
                        logger.warning(f"Treating '{relative_path_str}' as change due to read/compare error.")
                        is_actual_change = True # Treat read errors as changes

            except Exception as e:
                 logger.exception(f"Block {i+1}: Error processing change block during detection: {e}")
                 is_actual_change = True # Treat errors during processing as changes

            # --- Collect block content only if it's an actual change ---
            if is_actual_change:
                actual_changes_found = True
                # Add the *original matched block* (including markers) to the content to be emitted
                content_with_actual_changes += match.group(0) + "\n\n"
        # --- End Loop ---

        if actual_changes_found:
            num_change_blocks = content_with_actual_changes.count('### START FILE:')
            logger.info(f"ChatActionHandler: Emitting potential_change_detected pyqtSignal with {num_change_blocks} actual change blocks.")
            try:
                 # Emit only the content containing actual changes
                 self.potential_change_detected.emit(content_with_actual_changes.strip())
            except Exception as emit_err:
                 logger.exception(f"ChatActionHandler: ERROR EMITTING potential_change_detected pyqtSignal: {emit_err}")

            # Update the chat message to indicate changes are pending review
            display_text = f"[File change detected ({num_change_blocks} block(s)) - review in Change Queue]"
            self._chat_manager.finalize_ai_message(message_id, display_text)
            # Schedule UI update for the placeholder text
            QTimer.singleShot(0, lambda id=message_id, txt=display_text: self._update_message_widget_content(id, txt))
        else:
            # If markers were present but NO actual changes found, display the full original response
            logger.info("ChatActionHandler: No actual file changes detected despite markers. Displaying full response.")
            self._chat_manager.finalize_ai_message(message_id, full_ai_content)
            # Ensure full content is displayed if no changes were emitted
            QTimer.singleShot(0, lambda id=message_id, content=full_ai_content: self._update_message_widget_content(id, content))

