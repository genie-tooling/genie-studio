# tests/test_chat_manager.py
import pytest
from unittest.mock import patch
import uuid

# @patch('PyQt6.QtCore.QObject.__init__', return_value=None) # REMOVED: Let real QObject init run
def test_chat_manager_add_and_delete():
    """Tests adding user messages and deleting/truncating history."""
    # Must import AFTER patches are applied if they affect imports
    from pm.core.chat_manager import ChatManager

    # A QApplication instance might be needed if pyqtSignals cause issues without an event loop
    # from PyQt6.QtWidgets import QApplication
    # app = QApplication.instance() or QApplication([]) # Get existing or create one

    manager = ChatManager(parent=None) # Let QObject init run
    assert len(manager.get_history_snapshot()) == 0

    # Add messages
    msg1_id = manager.add_user_message("Hello")
    msg2_id = manager.add_ai_placeholder()
    manager.stream_ai_content_update(msg2_id, "Hi there!")
    manager.finalize_ai_message(msg2_id, "Hi there!")
    msg3_id = manager.add_user_message("How are you?")

    history = manager.get_history_snapshot()
    assert len(history) == 3
    assert history[0]['id'] == msg1_id
    assert history[0]['role'] == 'user'
    assert history[0]['content'] == 'Hello'
    assert history[1]['id'] == msg2_id
    assert history[1]['role'] == 'ai'
    assert history[1]['content'] == 'Hi there!'
    assert history[2]['id'] == msg3_id
    assert history[2]['role'] == 'user'
    assert history[2]['content'] == 'How are you?'

    # Delete the second message (AI response)
    manager.delete_message_and_truncate(msg2_id)

    history_after_delete = manager.get_history_snapshot()
    assert len(history_after_delete) == 1 # Should keep only the first message
    assert history_after_delete[0]['id'] == msg1_id
    assert history_after_delete[0]['content'] == 'Hello'

    # Add another message after truncation
    msg4_id = manager.add_user_message("Testing again")
    history_final = manager.get_history_snapshot()
    assert len(history_final) == 2
    assert history_final[0]['id'] == msg1_id
    assert history_final[1]['id'] == msg4_id
    assert history_final[1]['content'] == "Testing again"

# @patch('PyQt6.QtCore.QObject.__init__', return_value=None) # REMOVED: Let real QObject init run
def test_chat_manager_add_user_message_integration():
    """Tests adding a user message and checking history state."""
    from pm.core.chat_manager import ChatManager

    # A QApplication instance might be needed
    # from PyQt6.QtWidgets import QApplication
    # app = QApplication.instance() or QApplication([])

    manager = ChatManager(parent=None)
    initial_len = len(manager.get_history_snapshot())

    user_content = f"Test message {uuid.uuid4()}"
    message_id = manager.add_user_message(user_content)

    assert message_id is not None
    history = manager.get_history_snapshot()
    assert len(history) == initial_len + 1
    last_message = history[-1]
    assert last_message['id'] == message_id
    assert last_message['role'] == 'user'
    assert last_message['content'] == user_content
    assert 'timestamp' in last_message

