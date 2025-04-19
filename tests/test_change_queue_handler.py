# tests/test_change_queue_handler.py
import pytest
from unittest.mock import MagicMock, patch

# Import the real classes to use with spec
from pm.ui.change_queue_widget import ChangeQueueWidget
from pm.core.workspace_manager import WorkspaceManager
from pm.ui.controllers.status_bar_controller import StatusBarController

# Mock the base QObject init if necessary
@patch('PyQt6.QtCore.QObject.__init__', return_value=None)
def test_find_original_block_simple_match(mock_qobject_init):
    """Tests _find_original_block with a simple, exact match."""
    from pm.handlers.change_queue_handler import ChangeQueueHandler

    mock_widget = MagicMock(spec=ChangeQueueWidget)
    mock_workspace = MagicMock(spec=WorkspaceManager)
    mock_status_bar = MagicMock(spec=StatusBarController)
    mock_widget.view_requested = MagicMock()
    mock_widget.apply_requested = MagicMock()
    mock_widget.reject_requested = MagicMock()

    handler = ChangeQueueHandler(
        widget=mock_widget,
        workspace=mock_workspace,
        status_bar=mock_status_bar,
        parent=None
    )

    original_content = [
        "line 1\n", "line 2\n", "def my_function():\n",
        "    pass # Original\n", "line 5\n",
    ]
    original_full_content_str = "".join(original_content)
    proposed_content_lines = [
        "def my_function():\n", "    pass # Original\n",
    ]
    proposed_content_str = "".join(proposed_content_lines)
    original_lines_for_match = [line.rstrip('\n\r') for line in original_content]
    proposed_lines_for_match = [line.rstrip('\n\r') for line in proposed_content_lines]

    start, end, confidence = handler._find_original_block(original_lines_for_match, proposed_lines_for_match)

    assert start == 2
    assert end == 3
    assert confidence == 'exact'

# Mock the python-patch library if it's imported in the handler
@patch('pm.handlers.change_queue_handler.patch_library')
@patch('pm.handlers.change_queue_handler.HAS_PATCH_LIB', True)
@patch('pm.ui.change_queue_widget.ChangeQueueWidget', MagicMock()) # No arg injected
@patch('pm.core.workspace_manager.WorkspaceManager') # Injects MockWorkspaceManager
@patch('pm.ui.controllers.status_bar_controller.StatusBarController', MagicMock()) # No arg injected
@patch('PyQt6.QtCore.QObject.__init__', return_value=None) # Injects mock_qobject_init
# Correct signature order (matches non-MagicMock patches bottom-up)
def test_apply_request_patch_mode(mock_qobject_init, MockWorkspaceManager, mock_has_patch, mock_patch_lib):
    """Tests applying a change using the 'patch' apply_type."""
    from pm.handlers.change_queue_handler import ChangeQueueHandler, apply_patch
    from pathlib import Path
    # Need access to the mocked classes passed directly via MagicMock() in decorator
    from pm.ui.change_queue_widget import ChangeQueueWidget
    from pm.ui.controllers.status_bar_controller import StatusBarController

    # --- Setup ---
    mock_widget_instance = ChangeQueueWidget # Access the mock class directly
    mock_status_bar_instance = StatusBarController # Access the mock class directly
    mock_workspace_instance = MockWorkspaceManager.return_value
    mock_workspace_instance.save_tab_content_directly.return_value = True

    mock_patch_set_instance = MagicMock()
    original_content = "line 1\nline 2\nline 3\n"
    patched_content = "line 1\nline two\nline 3\n"
    mock_patch_set_instance.apply.return_value = patched_content.encode('utf-8')
    mock_patch_lib.fromstring.return_value = mock_patch_set_instance

    # Need to mock pyqtSignals on the class mock if __init__ uses them
    mock_widget_instance.view_requested = MagicMock()
    mock_widget_instance.apply_requested = MagicMock()
    mock_widget_instance.reject_requested = MagicMock()

    handler = ChangeQueueHandler(
        widget=mock_widget_instance,
        workspace=mock_workspace_instance,
        status_bar=mock_status_bar_instance,
        parent=None
    )

    test_file_path = Path("/fake/path/test.py")
    change_data = {
        'id': 'patch-test-1', 'file_path': test_file_path,
        'original_full_content': original_content,
        'proposed_content': "line 1\nline two\nline 3\n",
        'original_start_line': 1, 'original_end_line': 1,
        'match_confidence': 'exact',
        'apply_type': 'patch'
    }
    handler._find_item_by_id = MagicMock(return_value=MagicMock())

    # --- Action ---
    handler._handle_apply_request([change_data])

    # --- Assertions ---
    mock_patch_lib.fromstring.assert_called_once()
    mock_patch_set_instance.apply.assert_called_once_with(original_content.encode('utf-8'))
    mock_workspace_instance.save_tab_content_directly.assert_called_once_with(
        test_file_path, patched_content
    )
    mock_status_bar_instance.update_status.assert_called()
    mock_widget_instance.remove_items.assert_called_once()

