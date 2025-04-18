# pm/ui/highlighter.py
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import Qt # Added Qt for Font weight
from pygments import lex
from pygments.lexers import get_lexer_by_name, guess_lexer, find_lexer_class_for_filename
from pygments.styles import get_style_by_name
from pygments.token import Token, Error # Import Error token
from pygments.util import ClassNotFound
from loguru import logger
from typing import Optional

class PygmentsHighlighter(QSyntaxHighlighter):
    """
    A syntax highlighter using Pygments lexers and styles.
    """
    def __init__(self, document, language: Optional[str] = None, style_name: str = 'native'):
        super().__init__(document)
        self.language = language
        self.lexer = None
        self.style = None
        self.formats = {}

        self._set_style(style_name)
        self._update_lexer(language) # Try to set initial lexer

        logger.debug(f"PygmentsHighlighter initialized. Language='{language}', Style='{style_name}'")

    def _set_style(self, style_name: str):
        """Loads and prepares the Pygments style."""
        try:
            self.style = get_style_by_name(style_name)
            self.formats = {}
            # Pre-calculate QTextCharFormats for each token type in the style
            for token, style_dict in self.style:
                fmt = QTextCharFormat()
                if style_dict['color']:
                    fmt.setForeground(QColor(f"#{style_dict['color']}"))
                # Background color from style is usually unwanted in editors, let QSS handle it
                # if style_dict['bgcolor']:
                #     fmt.setBackground(QColor(f"#{style_dict['bgcolor']}"))
                if style_dict['bold']:
                    fmt.setFontWeight(QFont.Weight.Bold) # Use QFont enum
                if style_dict['italic']:
                    fmt.setFontItalic(True)
                if style_dict['underline']:
                    fmt.setFontUnderline(True)
                self.formats[token] = fmt
            logger.debug(f"Loaded Pygments style '{style_name}'.")
        except ClassNotFound:
            logger.error(f"Pygments style '{style_name}' not found. Falling back to default.")
            self.style = get_style_by_name('default') # Fallback
            self._set_style('default') # Recurse to load default formats

    def _update_lexer(self, language: Optional[str] = None):
        """Updates the lexer based on language name or guessing."""
        self.language = language
        self.lexer = None
        if self.language:
            try:
                self.lexer = get_lexer_by_name(self.language)
                logger.trace(f"Set lexer by name: '{self.language}'")
                return
            except ClassNotFound:
                logger.warning(f"Lexer for language '{self.language}' not found by name.")
                # Fall through to guessing based on filename/content if name fails

        # Try guessing from filename if available from document
        doc = self.document()
        file_path = getattr(doc, 'filePath', None) # Check if document has filePath attribute
        if file_path:
             try:
                  self.lexer = find_lexer_class_for_filename(file_path)().start() # Instantiate the found class
                  logger.trace(f"Set lexer by filename '{file_path}': {self.lexer.name}")
                  return
             except ClassNotFound:
                   logger.trace(f"No specific lexer found for filename '{file_path}'. Will guess by content.")
             except Exception as e:
                  logger.error(f"Error finding lexer for filename '{file_path}': {e}")

        # If language/filename fails, mark for content guessing in highlightBlock
        self.lexer = None
        logger.trace("Lexer not set by name/filename, will guess by content.")


    def highlightBlock(self, text: str):
        """Highlights a block of text using the configured lexer and style."""
        current_lexer = self.lexer

        # 1. Guess Lexer by Content if not already set
        if current_lexer is None and text.strip(): # Avoid guessing on empty lines
            try:
                # Note: Guessing per block can be slow, but necessary if filename/lang fails
                current_lexer = guess_lexer(text)
                # logger.trace(f"Guessed lexer by content: {current_lexer.name}")
            except Exception:
                 # logger.warning(f"Could not guess lexer for block: '{text[:50]}...'")
                 return # Cannot highlight without a lexer

        if current_lexer is None:
            return # No lexer found or guessed

        # 2. Tokenize and Apply Formats
        try:
             # Use documented interface: lexer.get_tokens_unprocessed()
             # Start index = 0 for each block
             for index, token, value in current_lexer.get_tokens_unprocessed(text):
                 fmt = self.formats.get(token, None)
                 # Try parent tokens if specific token has no format (e.g., Name.Function)
                 while fmt is None and token.parent:
                     token = token.parent
                     fmt = self.formats.get(token, None)

                 if fmt:
                     self.setFormat(index, len(value), fmt)
                 # Optional: Highlight error tokens specifically
                 elif token is Error:
                     error_fmt = QTextCharFormat()
                     error_fmt.setForeground(Qt.GlobalColor.red)
                     error_fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
                     self.setFormat(index, len(value), error_fmt)

        except Exception as e:
             # Log errors during highlighting of a specific block
             logger.error(f"Error during syntax highlighting block: {e} (Lexer: {current_lexer.name})")
             # Optional: Apply a default format to the whole block on error?
             # self.setFormat(0, len(text), self.formats.get(Token, QTextCharFormat()))


    def set_language(self, language: Optional[str]):
         """Public method to change the language and update the lexer."""
         self._update_lexer(language)
         self.rehighlight() # Trigger re-highlighting of the entire document

    def set_style(self, style_name: str):
         """Public method to change the Pygments style."""
         self._set_style(style_name)
         self.rehighlight()