# --- START OF FILE pm/core/workspace_manager.py ---
# pm/core/workspace_manager.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QTabWidget, QMessageBox, QApplication,
    QWidget
)
from PyQt6.QtGui import QFont, QIcon, QColor
from PyQt6.Qsci import (
    QsciScintilla, QsciLexerPython, QsciLexerCPP, QsciLexerCSharp, QsciLexerCSS,
    QsciLexerDiff, QsciLexerHTML, QsciLexerJavaScript, QsciLexerJSON,
    QsciLexerMarkdown, QsciLexerProperties, QsciLexerRuby, QsciLexerSQL,
    QsciLexerBash, QsciLexerYAML, QsciLexerXML, QsciLexerBatch, QsciLexerCMake,
    QsciLexerCoffeeScript, QsciLexerD, QsciLexerFortran, QsciLexerJava,
    QsciLexerLua, QsciLexerMakefile, QsciLexerMatlab, QsciLexerOctave,
    QsciLexerPascal, QsciLexerPerl, QsciLexerPostScript, QsciLexerPO,
    QsciLexerPOV, QsciLexerSpice, QsciLexerTCL, QsciLexerTeX, QsciLexerVerilog,
    QsciLexerVHDL
)
from pathlib import Path
import os
from loguru import logger
import qtawesome as qta
from typing import Dict, Optional

from .token_utils import count_tokens
from .constants import TOKEN_COUNT_ROLE, TREE_TOKEN_SIZE_LIMIT
from .settings_service import SettingsService
from .project_config import DEFAULT_CONFIG
from .constants import THEME_DEFINITIONS, LEXER_STYLE_ATTRIBUTE_MAP
# -------------------------------------

IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', '.mypy_cache', '.pytest_cache', 'node_modules'}
IGNORE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.zip', '.tar', '.gz', '.ico', '.svg', '.db', '.sqlite', '.bin', '.exe', '.dll', '.so', '.o', '.a', '.lib'}

LEXER_MAP = {
    '.py': QsciLexerPython,
    '.js': QsciLexerJavaScript,
    '.jsx': QsciLexerJavaScript,
    '.ts': QsciLexerJavaScript,
    '.tsx': QsciLexerJavaScript,
    '.html': QsciLexerHTML,
    '.htm': QsciLexerHTML,
    '.css': QsciLexerCSS,
    '.json': QsciLexerJSON,
    '.yaml': QsciLexerYAML,
    '.yml': QsciLexerYAML,
    '.sh': QsciLexerBash,
    '.bash': QsciLexerBash,
    '.zsh': QsciLexerBash,
    '.bat': QsciLexerBatch,
    '.cmd': QsciLexerBatch,
    '.c': QsciLexerCPP,
    '.cpp': QsciLexerCPP,
    '.cxx': QsciLexerCPP,
    '.h': QsciLexerCPP,
    '.hpp': QsciLexerCPP,
    '.cs': QsciLexerCSharp,
    '.java': QsciLexerJava,
    '.xml': QsciLexerXML,
    '.sql': QsciLexerSQL,
    '.md': QsciLexerMarkdown,
    '.markdown': QsciLexerMarkdown,
    '.rb': QsciLexerRuby,
    '.go': None,
    '.rs': None,
    '.php': None,
    '.pl': QsciLexerPerl,
    '.lua': QsciLexerLua,
    '.diff': QsciLexerDiff,
    '.patch': QsciLexerDiff,
    '.tex': QsciLexerTeX,
    '.vhd': QsciLexerVHDL,
    '.vhdl': QsciLexerVHDL,
    '.v': QsciLexerVerilog,
    '.sv': QsciLexerVerilog,
    '.tcl': QsciLexerTCL,
    '.mk': QsciLexerMakefile,
    'makefile': QsciLexerMakefile,
    'cmakelists.txt': QsciLexerCMake,
    '.cmake': QsciLexerCMake,
    '.ini': QsciLexerProperties,
    '.conf': QsciLexerProperties,
    '.properties': QsciLexerProperties,
    '.toml': QsciLexerProperties,
    '.ps1': None,
    '.ps': QsciLexerPostScript,
    '.pas': QsciLexerPascal,
    '.f': QsciLexerFortran,
    '.f90': QsciLexerFortran,
    '.d': QsciLexerD,
    '.coffee': QsciLexerCoffeeScript,
    '.m': QsciLexerMatlab,
    '.octave': QsciLexerOctave,
    '.spice': QsciLexerSpice,
    '.po': QsciLexerPO,
    '.pov': QsciLexerPOV,
}

class WorkspaceManager(QObject):
    """Manages project state, file tree, and editor tabs using QScintilla."""
    project_changed = pyqtSignal(Path)
    editors_changed = pyqtSignal()
    file_saved = pyqtSignal(Path)
    file_operation_error = pyqtSignal(str)

    def __init__(self, initial_project_path: Path, settings_service: SettingsService, parent=None):
        super().__init__(parent)
        self._project_path = initial_project_path
        self._settings_service = settings_service
        self.open_editors: Dict[Path, QsciScintilla] = {}
        logger.info(f"WorkspaceManager initialized for path: {initial_project_path}")

        # Connect to the new editor_theme_changed signal
        self._settings_service.editor_theme_changed.connect(self.apply_editor_theme)

    @property
    def project_path(self) -> Path:
        return self._project_path

    def set_project_path(self, new_path: Path):
        new_path = Path(new_path).resolve()

        if new_path != self._project_path:
            if new_path.is_dir():
                logger.info(f"WorkspaceManager: Setting project path to {new_path}")
                self._project_path = new_path
                self.open_editors.clear()
                self.project_changed.emit(new_path)
                self.editors_changed.emit()
            else:
                error_msg = f"Invalid project path selected: {new_path}"
                logger.error(f"WorkspaceManager: {error_msg}")
                self.file_operation_error.emit(error_msg)

    def populate_file_tree(self, tree_widget: QTreeWidget):
        if not self._project_path or not self._project_path.is_dir():
            logger.error("Wks Mgr: Populate tree fail - invalid path.")
            tree_widget.clear()

            return

        logger.info(f"Wks Mgr: Populating file tree for {self._project_path}")
        tree_widget.blockSignals(True)
        tree_widget.clear()

        try:
            proj_root_item = QTreeWidgetItem(tree_widget, [self._project_path.name, ""])
            proj_root_item.setIcon(0, qta.icon('fa5s.folder-open', color='lightblue'))
            proj_root_item.setData(0, Qt.ItemDataRole.UserRole, str(self._project_path))
            proj_root_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            tree_items = {str(self._project_path): proj_root_item}

            for root, dirs, files in os.walk(self._project_path, topdown=True, onerror=logger.warning):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
                parent_item = tree_items.get(str(root_path))

                if parent_item is None:
                    continue

                for dname in sorted(dirs):
                    dir_path = root_path / dname
                    item = QTreeWidgetItem(parent_item, [dname, ""])
                    item.setIcon(0, qta.icon('fa5s.folder', color='lightgray'))
                    item.setData(0, Qt.ItemDataRole.UserRole, str(dir_path))
                    required_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                    item.setFlags(required_flags)
                    item.setCheckState(0, Qt.CheckState.Checked)
                    tree_items[str(dir_path)] = item

                for fname in sorted(files):
                    fpath = root_path / fname

                    if fname.startswith('.') or fpath.suffix.lower() in IGNORE_EXT:
                        continue

                    token_display = "-"
                    token_count = 0

                    try:
                        fsize = fpath.stat().st_size

                        if fsize <= TREE_TOKEN_SIZE_LIMIT:
                            try:
                                content = fpath.read_text(encoding='utf-8', errors='ignore')
                                token_count = count_tokens(content)
                                token_display = f"{token_count:,}"

                            except Exception:
                                token_display = "Error"

                        else:
                            token_display = f">{TREE_TOKEN_SIZE_LIMIT // 1024}KB"

                    except OSError:
                        token_display = "N/A"
                        continue

                    item = QTreeWidgetItem(parent_item, [fname, token_display])
                    item.setIcon(0, qta.icon('fa5s.file-code', color='darkgray'))
                    item.setData(0, Qt.ItemDataRole.UserRole, str(fpath))
                    item.setData(0, TOKEN_COUNT_ROLE, token_count)
                    required_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                    item.setFlags(required_flags)
                    item.setCheckState(0, Qt.CheckState.Checked)
                    item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        except Exception as e:
            logger.exception(f"Wks Mgr: Error during tree population: {e}")

        finally:
            tree_widget.expandToDepth(0)
            tree_widget.blockSignals(False)
            logger.info("Wks Mgr: File tree population finished.")

    def load_file(self, path: Path, tab_widget: QTabWidget) -> Optional[QsciScintilla]:
        path = path.resolve()

        if not path.is_file():
            logger.warning(f"WorkspaceManager: Attempted to load non-file: {path}")
            self.file_operation_error.emit(f"Cannot load: '{path.name}' is not a file.")
            return None

        if path in self.open_editors:
            editor = self.open_editors[path]
            found_tab_index = -1
            for i in range(tab_widget.count()):
                if tab_widget.widget(i) == editor:
                    found_tab_index = i
                    break

            if found_tab_index != -1:
                logger.debug(f"File already open, focusing tab {found_tab_index}: {path.name}")
                tab_widget.setCurrentIndex(found_tab_index)
                editor.setFocus()
                return editor
            else:
                logger.warning(f"Editor for {path} in dict but not found in tabs. Reloading.")
                try: del self.open_editors[path]
                except KeyError: pass

        logger.info(f"WorkspaceManager: Loading file into new tab: {path}")

        try:
            if path.stat().st_size > (5 * 1024 * 1024):
                reply = QMessageBox.question(QApplication.activeWindow(), "Large File", f"'{path.name}' is large.\nLoad anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.No: return None

            content_bytes = path.read_bytes()
            content_text = None
            is_text_file = True
            try:
                content_text = content_bytes.decode('utf-8')
                if '\x00' in content_text[:1000]:
                    is_text_file = False
                    logger.warning(f"File '{path.name}' appears to contain null bytes, may be binary.")
                    content_text = None
            except UnicodeDecodeError:
                is_text_file = False
                logger.warning(f"File '{path.name}' is not UTF-8, may be binary.")
                content_text = None
            except Exception as e:
                is_text_file = False
                logger.warning(f"Error decoding file '{path.name}': {e}")
                content_text = None

            if not is_text_file or content_text is None:
                error_msg = f"Cannot open non-text or potentially binary file:\n{path}"
                logger.error(f"WorkspaceManager: {error_msg}")
                self.file_operation_error.emit(error_msg)
                return None

        except Exception as e:
            error_msg = f"Could not read file:\n{path}\n\nError: {e}"
            logger.error(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)
            return None

        try:
            editor = QsciScintilla()
            editor.SendScintilla(QsciScintilla.SCI_SETCODEPAGE, QsciScintilla.SC_CP_UTF8)
            editor.setText(content_text)
            editor.setObjectName(str(path)) # Store path in objectName

            editor.setUtf8(True)
            editor.setIndentationsUseTabs(False)
            editor.setTabWidth(4)
            editor.setIndentationGuides(True)
            editor.setAutoIndent(True)
            editor.setCaretLineVisible(True)
            # Base caret line color - will be overridden by theme
            editor.setCaretLineBackgroundColor(QColor("#333333"))

            font_metrics = editor.fontMetrics()
            editor.setMarginsFont(editor.font())
            editor.setMarginWidth(0, font_metrics.horizontalAdvance("00000") + 6)
            editor.setMarginLineNumbers(0, True)
            # Base margin colors - will be overridden by theme
            editor.setMarginsBackgroundColor(QColor("#303030"))
            editor.setMarginsForegroundColor(QColor("#888888"))
            editor.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle, 1)
            editor.setMarginWidth(1, 12)
            # Base fold margin colors - will be overridden by theme
            editor.setFoldMarginColors(QColor("#303030"), QColor("#303030"))

            # Font is applied by apply_font_to_editors, but set it here initially
            font_name = self._settings_service.get_setting("editor_font", "Fira Code")
            font_size = int(self._settings_service.get_setting("editor_font_size", 11))
            editor_font = QFont(font_name, font_size)
            editor.setFont(editor_font)

            self._set_lexer(editor, path)

            # --- REMOVE THIS LINE ---
            # current_theme_name = self._settings_service.get_setting('editor_theme', DEFAULT_CONFIG['editor_theme'])
            # self._configure_lexer_style(editor, current_theme_name)
            # ------------------------

            editor.setModified(False)

            logger.debug(f"Configured QScintilla editor for {path.name}")

        except Exception as e:
            error_msg = f"Error creating editor widget for {path.name}: {e}"
            logger.exception(error_msg)
            self.file_operation_error.emit(error_msg)
            return None

        try:
            index = tab_widget.addTab(editor, path.name)
            if index == -1: raise RuntimeError("Failed to add tab to QTabWidget.")

            tab_widget.setTabToolTip(index, str(path))
            tab_widget.setCurrentWidget(editor)
            editor.setFocus()

            logger.info(f"Added editor for {path.name} at tab index {index}")
            self.open_editors[path] = editor
            self.editors_changed.emit()

            # --- IMPORTANT: Apply the current theme AFTER the editor is added and lexer is set ---
            # This ensures the styling is applied correctly based on the lexer.
            # Use a singleShot timer to ensure this happens after the event loop processes adding the tab
            QTimer.singleShot(0, lambda ed=editor: self._apply_theme_to_single_editor(ed))
            # ------------------------------------------------------------------------------------

            return editor

        except Exception as e:
            error_msg = f"Error adding editor tab for {path.name}: {e}"
            logger.exception(error_msg)
            self.file_operation_error.emit(error_msg)
            if editor: editor.deleteLater()
            if path in self.open_editors: del self.open_editors[path]; self.editors_changed.emit()
            return None

    # --- NEW Helper method to apply theme to a single editor ---
    # This is called by the QTimer after load_file adds the editor
    @pyqtSlot(QsciScintilla)
    def _apply_theme_to_single_editor(self, editor: QsciScintilla):
        """Applies the current editor theme to a single editor instance."""
        if not editor or not editor.objectName():
            logger.warning("Attempted to apply theme to invalid editor.")
            return

        path = Path(editor.objectName())
        logger.debug(f"Applying current editor theme to editor: {path.name}")

        current_theme_name = self._settings_service.get_setting('editor_theme', DEFAULT_CONFIG['editor_theme'])
        theme_definition = THEME_DEFINITIONS.get(current_theme_name)

        if not theme_definition:
            logger.error(f"Theme definition not found for '{current_theme_name}'. Using Native Dark fallback for single editor.")
            theme_definition = THEME_DEFINITIONS.get("Native Dark", THEME_DEFINITIONS[list(THEME_DEFINITIONS.keys())[0]]) # Fallback to Native Dark or first available

        palette = theme_definition['palette']
        style_mapping = theme_definition['mapping']

        # Apply base editor properties (paper, color, caret line, margins)
        editor_paper = theme_definition.get('editor_paper', QColor(palette['editor_paper']))
        editor_color = theme_definition.get('editor_color', QColor(palette['editor_color']))
        caret_line_bg = theme_definition.get('caret_line_bg', QColor(palette.get('caret_line_bg', '#333333')))
        margins_bg = theme_definition.get('margins_bg', QColor(palette.get('margins_bg', '#303030')))
        margins_fg = theme_definition.get('margins_fg', QColor(palette.get('margins_fg', '#888888')))

        try:
            editor.setPaper(editor_paper)
            editor.setColor(editor_color)
            editor.setCaretLineBackgroundColor(caret_line_bg)
            editor.setMarginsBackgroundColor(margins_bg)
            editor.setMarginsForegroundColor(margins_fg)

            # Apply default font (important!) - Use the editor's current font (set by apply_font_to_editors)
            default_font = editor.font()

            # Apply default font, color, and paper to Style 0 (default text style) using SendScintilla
            editor.SendScintilla(QsciScintilla.SCI_STYLESETFONT, 0, default_font.family().encode('utf-8'))
            editor.SendScintilla(QsciScintilla.SCI_STYLESETSIZE, 0, default_font.pointSize())
            editor.SendScintilla(QsciScintilla.SCI_STYLESETFORE, 0, editor_color.rgb())
            editor.SendScintilla(QsciScintilla.SCI_STYLESETBACK, 0, editor_paper.rgb())

            lexer = editor.lexer()

            if lexer:
                # Reset all lexer styles (0-255) to Style 0's properties first (clean slate)
                style_count = 256 # Scintilla supports up to 256 styles (0-255)

                for i in range(style_count):
                     # Use SCI_STYLESET... to explicitly set properties
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETFORE, i, editor_color.rgb())
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETBACK, i, editor_paper.rgb())
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETBOLD, i, False)
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETITALIC, i, False)
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETUNDERLINE, i, False)
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETFONT, i, default_font.family().encode('utf-8'))
                     editor.SendScintilla(QsciScintilla.SCI_STYLESETSIZE, i, default_font.pointSize())

                # Now apply specific colors based on the theme's palette and the mapping
                for attr_name, palette_key in style_mapping.items():
                    # Check if the lexer has this style attribute AND the palette has the color key
                    if hasattr(lexer, attr_name) and palette_key in palette:
                        style_id = getattr(lexer, attr_name)
                        color = QColor(palette[palette_key])

                        try:
                            # Set color for the specific style ID using lexer's method
                            lexer.setColor(color, style_id)
                            # Optionally set font properties like bold/italic here if theme defines it
                            # e.g., if palette has {'keyword': {'color': '#...', 'bold': True}}
                            # if isinstance(palette[palette_key], dict) and palette[palette_key].get('bold'):
                            #    lexer.setFont(QFont(default_font.family(), default_font.pointSize(), QFont.Weight.Bold), style_id)

                        except Exception as style_e:
                            # Log if a specific style application fails but continue with others
                            logger.warning(f"Failed to apply color for lexer style attribute '{attr_name}' (Palette key '{palette_key}') on {editor.objectName()}: {style_e}")

            logger.trace(f"Applied theme '{current_theme_name}' styling to editor: {editor.objectName()}")

        except Exception as e:
            logger.error(f"Error applying editor theme '{current_theme_name}' to {editor.objectName()}: {e}")

    @pyqtSlot() # Add decorator for signal connection
    @pyqtSlot(str) # Allow direct call with theme name
    # --- RENAMED method ---
    def apply_editor_theme(self, theme_name: Optional[str] = None):
        """Applies the selected editor theme to all currently open editors."""
        # Fetch the current theme name from settings if not provided
        current_theme_name = theme_name if theme_name is not None else self._settings_service.get_setting('editor_theme', DEFAULT_CONFIG['editor_theme'])

        logger.info(f"WorkspaceManager: Applying editor theme '{current_theme_name}' to {len(self.open_editors)} editors.")

        # Iterate through all open editors and apply the theme to each
        for editor in self.open_editors.values():
            # Call the helper method for each editor
            self._apply_theme_to_single_editor(editor)

    @pyqtSlot(str, int)
    def apply_font_to_editors(self, font_family: str, font_size: int):
        """Applies the specified font family and size to all open editor widgets."""
        logger.info(f"Applying font '{font_family}', size {font_size} to {len(self.open_editors)} editors.")

        new_font = QFont(font_family, font_size)

        for editor in self.open_editors.values():
            try:
                editor.setFont(new_font)
                editor.setMarginsFont(new_font)
                # Re-apply editor theme to pick up the new font for styling
                # Passing the current theme name to ensure correct theme is applied
                # This also re-applies Style 0 font via _apply_theme_to_single_editor
                current_theme_name = self._settings_service.get_setting('editor_theme', DEFAULT_CONFIG['editor_theme'])
                self._apply_theme_to_single_editor(editor) # Call the single editor helper

            except Exception as e:
                logger.error(f"Error applying font to {editor.objectName()}: {e}")

    def close_tab(self, index: int, tab_widget: QTabWidget):
        widget = tab_widget.widget(index)

        if widget and isinstance(widget, QsciScintilla):
            path_to_remove = Path(widget.objectName())
            tab_widget.removeTab(index)

            if path_to_remove in self.open_editors:
                del self.open_editors[path_to_remove]
                logger.info(f"WorkspaceManager: Closed tab {path_to_remove.name}")
                self.editors_changed.emit()

            else:
                logger.warning(f"WorkspaceManager: Closed tab path {path_to_remove} not in dict.")

            widget.deleteLater()

        elif widget:
            logger.warning(f"Closing tab at index {index}, but widget is not QsciScintilla: {type(widget)}")
            tab_widget.removeTab(index)
            widget.deleteLater()

    def save_tab_content(self, editor: QsciScintilla) -> bool:
        path_str = editor.objectName()

        if not path_str:
            logger.error("WorkspaceManager: Cannot save tab, no path associated.")
            self.file_operation_error.emit("Cannot save file: Path unknown.")

            return False

        current_path = Path(path_str)

        try:
            text = editor.text()
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_text(text, encoding='utf-8')

            logger.info(f'WorkspaceManager: Saved {current_path}')
            editor.setModified(False)
            self.file_saved.emit(current_path)

            return True

        except Exception as e:
            error_msg = f"Could not save file:\n{current_path}\n\nError: {e}"
            logger.error(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)

            return False

    def save_tab_content_directly(self, file_path: Path, content: str) -> bool:
        logger.info(f"WorkspaceManager: Directly saving content to {file_path}")

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')

            logger.info(f'WorkspaceManager: Saved {file_path}')
            self.file_saved.emit(file_path)

            if file_path in self.open_editors:
                editor = self.open_editors[file_path]
                # Block signals to prevent modificationChanged from firing repeatedly
                editor.blockSignals(True)
                editor.setText(content)
                editor.setModified(False)
                editor.blockSignals(False)
                # Re-apply theme to ensure styling is correct after content change
                self._apply_theme_to_single_editor(editor)


            return True

        except Exception as e:
            error_msg = f"Could not save file:\n{file_path}\n\nError: {e}"
            logger.error(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)

            return False
    def _set_lexer(self, editor: QsciScintilla, path: Path):
        ext = path.suffix.lower()
        lexer_class = LEXER_MAP.get(ext)

        if not lexer_class:
            if path.name.lower() == 'makefile':
                lexer_class = QsciLexerMakefile

            elif path.name.lower().startswith('cmakelists'):
                lexer_class = QsciLexerCMake

            elif path.name.lower().endswith('.conf'):
                lexer_class = QsciLexerProperties

        if lexer_class:
            lexer = lexer_class(editor)

            if isinstance(lexer, QsciLexerCPP):
                lexer.setLanguage(QsciLexerCPP.Language.Cpp)

            elif isinstance(lexer, QsciLexerPython):
                # No setLanguage method for QsciLexerPython
                pass

            editor.setLexer(lexer)
            logger.debug(f"Set lexer '{lexer.__class__.__name__}' for {path.name}")

        else:
            editor.setLexer(None)
            logger.debug(f"No specific lexer found for extension '{ext}', using default styling.")

    def create_new_file(self, filename: str) -> Optional[Path]:
        if not filename:
            return None

        fpath = self._project_path / filename.strip()

        if fpath.exists():
            error_msg = f"File '{fpath.name}' already exists."
            logger.warning(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)

            return None

        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text('', encoding='utf-8')

            logger.info(f"WorkspaceManager: Created new file: {fpath}")

            return fpath

        except Exception as e:
            error_msg = f"Could not create file:\n{fpath}\n\nError: {e}"
            logger.error(f"WorkspaceManager: {error_msg}")
            self.file_operation_error.emit(error_msg)

            return None

        # This method can be called by MainWindow after initialization
    def apply_initial_settings(self):
        """Applies theme and font settings when the application starts."""
        logger.debug("SettingsActionHandler: Applying initial theme, font, style...")
        self._apply_theme(self._settings_service.get_setting('theme', 'Dark'))
        self._apply_font(
            self._settings_service.get_setting('editor_font', 'Fira Code'),
            self._settings_service.get_setting('editor_font_size', 11)
        )
        self._apply_syntax_style(self._settings_service.get_setting('syntax_highlighting_style'))

    # pyqtSlots to apply settings remain largely the same
    @pyqtSlot(str)
    def _apply_theme(self, theme_name: str):
        """Applies the selected UI theme (Dark/Light)."""
        logger.info(f"Applying theme: {theme_name}")
        try:
            stylesheet = pyqtdarktheme.load_stylesheet(theme_name.lower())
            self._main_window.setStyleSheet(stylesheet) # Apply to main window
        except Exception as e:
            logger.error(f"Failed to apply theme '{theme_name}': {e}")

    @pyqtSlot(str, int)
    def _apply_font(self, font_family: str, font_size: int):
        """Applies font changes to relevant widgets via WorkspaceManager."""
        logger.info(f"Applying font: {font_family}, Size: {font_size}")
        self._workspace_manager.apply_font_to_editors(font_family, font_size)

    @pyqtSlot(str)
    def _apply_syntax_style(self, style_name: str):
        """Applies the selected syntax highlighting style via WorkspaceManager."""
        logger.info(f"Applying syntax style: {style_name}")
        self._workspace_manager.apply_syntax_style(style_name)

# --- END OF FILE pm/core/workspace_manager.py ---