# pm/core/chat_manager.py
from PySide6.QtCore import QObject, Signal
from loguru import logger
import datetime
import uuid
from typing import List, Dict, Optional

class ChatManager(QObject):
    """Manages chat history state and logic."""
    # Signals changes requiring UI update or full re-render
    history_changed = Signal()
    # Signals a specific message content update (for dynamic streaming)
    message_content_updated = Signal(str, str) # message_id, full_content
    # Signals when the history is truncated (e.g., after delete/edit)
    history_truncated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_history: List[Dict] = []
        logger.info("ChatManager initialized.")

    def add_user_message(self, content: str) -> Optional[str]:
        """Adds a user message to the history."""
        if not content:
            return None
        msg = {
            'id': str(uuid.uuid4()),
            'role': 'user',
            'content': content,
            'timestamp': datetime.datetime.now()
        }
        self.chat_history.append(msg)
        logger.debug(f"ChatManager: Added user message {msg['id']}")
        self.history_changed.emit() # Trigger re-render
        return msg['id']

    def add_ai_placeholder(self) -> Optional[str]:
        """Adds an empty placeholder for an incoming AI message."""
        msg = {
            'id': str(uuid.uuid4()),
            'role': 'ai',
            'content': '',
            'timestamp': datetime.datetime.now()
        }
        self.chat_history.append(msg)
        logger.debug(f"ChatManager: Added AI placeholder {msg['id']}")
        self.history_changed.emit() # Trigger re-render to show placeholder
        return msg['id']

    def _find_message_by_id(self, message_id: str) -> Optional[Dict]:
        """Finds a message dictionary by its ID."""
        # Iterate backwards as updates usually affect recent messages
        for msg in reversed(self.chat_history):
            if msg.get('id') == message_id:
                return msg
        return None

    def stream_ai_content_update(self, message_id: str, chunk: str):
        """Appends a chunk to an AI message's content (for streaming)."""
        message = self._find_message_by_id(message_id)
        if message and message.get('role') == 'ai':
            message['content'] += chunk
            # Emit specific update signal for dynamic UI update
            self.message_content_updated.emit(message_id, message['content'])
        else:
             # Only log warning if ID was expected but not found/wrong role
             if message_id:
                logger.warning(f"ChatManager: Could not find AI message {message_id} to stream update.")

    def finalize_ai_message(self, message_id: str, final_content: str):
        """Sets the final content for an AI message after streaming."""
        message = self._find_message_by_id(message_id)
        if message and message.get('role') == 'ai':
             if message['content'] != final_content: # Avoid redundant signal if content unchanged
                  message['content'] = final_content
                  # Emit specific update signal ensures final content is rendered
                  self.message_content_updated.emit(message_id, final_content)
                  logger.debug(f"ChatManager: Finalized AI message {message_id}")
             else:
                   logger.debug(f"ChatManager: AI message {message_id} final content already set.")
        else:
             if message_id:
                logger.warning(f"ChatManager: Could not find AI message {message_id} to finalize.")


    def delete_message_and_truncate(self, message_id: str):
        """Finds message by ID, removes it and all subsequent messages."""
        idx = next((i for i, m in enumerate(self.chat_history) if m.get('id') == message_id), -1)
        if idx != -1:
            original_length = len(self.chat_history)
            self.chat_history = self.chat_history[:idx]
            logger.info(f"ChatManager: Deleted message {message_id} & truncated history from {original_length} to {len(self.chat_history)} items.")
            self.history_truncated.emit() # Signal truncation happened
            self.history_changed.emit() # Signal general change for re-render
        else:
             logger.warning(f"ChatManager: Cannot find message {message_id} to delete.")

    def update_message_content(self, message_id: str, new_content: str) -> bool:
        """Updates the content of a specific message (typically user for editing)."""
        message = self._find_message_by_id(message_id)
        if message:
            message['content'] = new_content
            logger.info(
                f"ChatManager: Updated content for message {message_id}."
            )
            # This usually precedes truncation and re-submission, history_changed will be emitted later.
            # If immediate visual update is needed before truncation, emit here:
            # self.history_changed.emit()
            return True
        else:
            logger.warning(f"ChatManager: Cannot find message {message_id} to update content.")
            return False

    def truncate_history_after(self, message_id: str):
        """Truncates history *after* the specified message ID."""
        idx = next((i for i, m in enumerate(self.chat_history) if m.get('id') == message_id), -1)
        if idx != -1:
             original_length = len(self.chat_history)
             self.chat_history = self.chat_history[:idx + 1] # Keep the message itself
             logger.info(f"ChatManager: Truncated history *after* message {message_id}. Len: {original_length} -> {len(self.chat_history)}.")
             self.history_truncated.emit()
             self.history_changed.emit()
        else:
             logger.warning(f"ChatManager: Cannot find message {message_id} to truncate after.")


    def get_history_snapshot(self) -> List[Dict]:
        """Returns a shallow copy of the current chat history."""
        # Use shallow copy as dicts themselves contain primitive types mostly
        return list(self.chat_history)

    def clear_history(self):
        """Clears the chat history."""
        self.chat_history = []
        logger.info("ChatManager: History cleared.")
        self.history_changed.emit()

