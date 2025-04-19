# tests/test_workspace_manager.py
import pytest
from unittest.mock import MagicMock, patch, ANY
from pathlib import Path

# Attempt to import QApplication for test environment setup
try:
    from PyQt6.QtWidgets import QApplication, QTabWidget
    from PyQt6.QtGui import QFont # Import for spec
    from PyQt6.Qsci import QsciScintilla # Import QScintilla
except ImportError:
    # Define dummy classes if PyQt6/QScintilla is completely unavailable
    class QApplication: pass
    class QTabWidget: pass
    class QFont: pass
    class QsciScintilla: pass
    print("Warning: PyQt6/QScintilla not found, mocks are dummies.")

# Patch QScintilla and its lexer where they are used
@patch('pm.core.workspace_manager.SettingsService')
@patch('pm.core.workspace_manager.QFont')
@patch('pm.core.workspace_manager.QsciScintilla') # Patch QScintilla
@patch('pm.core.workspace_manager.QsciLexerPython') # Patch a specific lexer (adjust if needed)
@patch('PyQt6.QtWidgets.QTabWidget')
def test_load_file_integration(MockQTabWidget_cls, MockLexer_cls, MockQsciScintilla_cls, MockQFont_cls, MockSettingsService_cls, tmp_path):
    """Tests WorkspaceManager.load_file basic integration with QScintilla."""
    app = QApplication.instance() or QApplication([]) # Ensure QApplication exists

    # Import must happen *after* class mocks are applied
    from pm.core.workspace_manager import WorkspaceManager

    # --- Setup ---
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    test_file = project_dir / "test.py"
    test_file_content = "print('Hello from test file!')"
    test_file.write_text(test_file_content)

    # Configure mock SettingsService instance
    mock_settings_instance = MockSettingsService_cls.return_value
    mock_settings_instance.get_setting.side_effect = lambda key, default=None: {
        'editor_font': 'MockFont',
        'editor_font_size': 10,
        'syntax_highlighting_style': 'mockstyle' # Style name still needed? Maybe for _configure_lexer_style
    }.get(key, default)

    # Configure mock QsciScintilla *instance* behavior
    mock_editor_instance = MockQsciScintilla_cls.return_value
    mock_editor_instance.objectName.return_value = str(test_file) # Set object name for retrieval

    # Configure mock lexer instance
    mock_lexer_instance = MockLexer_cls.return_value

    # Configure mock QFont instance
    mock_qfont_instance = MockQFont_cls.return_value

    # Instantiate the class under test
    manager = WorkspaceManager(
        initial_project_path=project_dir,
        settings_service=mock_settings_instance,
        parent=None
    )
    mock_tab_widget_instance = MockQTabWidget_cls.return_value

    # --- Action ---
    editor_widget_result = manager.load_file(test_file, mock_tab_widget_instance)

    # --- Assertions ---
    # Check editor instance creation and storage
    assert editor_widget_result is mock_editor_instance
    assert test_file.resolve() in manager.open_editors
    assert manager.open_editors[test_file.resolve()] is mock_editor_instance
    MockQsciScintilla_cls.assert_called_once()

    # Check interactions with the mock QsciScintilla instance
    mock_editor_instance.setText.assert_called_once_with(test_file_content)
    mock_editor_instance.setModified.assert_called_with(False) # Should be called after setting text
    mock_editor_instance.setUtf8.assert_called_once_with(True)
    mock_editor_instance.setLexer.assert_called_once_with(mock_lexer_instance) # Check lexer was set
    # Check font was set (using standard QWidget method)
    mock_editor_instance.setFont.assert_called_once_with(mock_qfont_instance)
    MockQFont_cls.assert_called_once_with('MockFont', 10)

    # Check lexer creation (assuming python file leads to python lexer)
    MockLexer_cls.assert_called_once_with(mock_editor_instance)

    # Check interactions with the mock tab widget instance
    mock_tab_widget_instance.addTab.assert_called_once_with(mock_editor_instance, test_file.name)
    mock_tab_widget_instance.setCurrentWidget.assert_called_with(mock_editor_instance)
    mock_editor_instance.setFocus.assert_called_once() # Check focus was called

    # Check lexer styling call (internal detail, maybe mock _configure_lexer_style if complex)
    # For now, assume it's called implicitly or test it separately
