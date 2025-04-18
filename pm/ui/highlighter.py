from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from pygments import lex
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.token import Token

class PygmentsHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language: str | None = None):
        super().__init__(document)
        self.language = language

    def highlightBlock(self, text: str):
        try:
            lexer = get_lexer_by_name(self.language) if self.language else guess_lexer(text)
        except Exception:
            return
        for token, content in lex(text, lexer):
            length = len(content)
            if length == 0:
                continue
            fmt = QTextCharFormat()
            if token in Token.Keyword:
                fmt.setForeground(QColor('#c586c0'))
            elif token in Token.String:
                fmt.setForeground(QColor('#ce9178'))
            elif token in Token.Comment:
                fmt.setForeground(QColor('#6a9955'))
            elif token in Token.Number:
                fmt.setForeground(QColor('#b5cea8'))
            elif token in Token.Operator:
                fmt.setForeground(QColor('#d4d4d4'))
            self.setFormat(0, length, fmt)
