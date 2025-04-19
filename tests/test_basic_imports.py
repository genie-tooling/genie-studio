# tests/test_basic_imports.py
import pytest

def test_import_core_modules():
    """Tests if core modules can be imported without immediate errors."""
    try:
        from pm.core import app_core
        from pm.core import settings_service
        from pm.core import chat_manager
        from pm.core import workspace_manager
        from pm.core import task_manager
        from pm.core import llm_service_provider
        from pm.core import model_list_service
        from pm.core import rag_service
    except ImportError as e:
        pytest.fail(f"Failed to import core modules: {e}")
    except Exception as e:
        pytest.fail(f"Exception during core module import: {e}")

def test_import_ui_modules():
    """Tests if UI modules can be imported without immediate errors."""
    try:
        from pm.ui import main_window
        from pm.ui import main_window_ui
        from pm.ui import config_dock
        from pm.ui import chat_message_widget
        from pm.ui import change_queue_widget
        from pm.ui import settings_dialog
    except ImportError as e:
        pytest.fail(f"Failed to import UI modules: {e}")
    except Exception as e:
        # Note: Qt-related errors might occur here if run without a GUI context,
        # but basic import should succeed.
        pytest.fail(f"Exception during UI module import: {e}")

def test_import_handler_modules():
    """Tests if handler modules can be imported without immediate errors."""
    try:
        from pm.handlers import chat_action_handler
        from pm.handlers import workspace_action_handler
        from pm.handlers import settings_action_handler
        from pm.handlers import prompt_action_handler
        from pm.handlers import change_queue_handler
    except ImportError as e:
        pytest.fail(f"Failed to import handler modules: {e}")
    except Exception as e:
        pytest.fail(f"Exception during handler module import: {e}")

