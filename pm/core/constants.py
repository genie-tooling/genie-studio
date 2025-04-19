# pm/core/constants.py
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
# Attempt to get available styles, handle ImportError if pygments is not a direct dependency
# Keep this check and list, as it's still used in settings_service validation logic for 'syntax_highlighting_style'
# although we are introducing a new 'editor_theme' setting.
try:
    from pygments.styles import get_all_styles
    AVAILABLE_PYGMENTS_STYLES = list(get_all_styles())
except ImportError:
    # logger.warning("Pygments library not found. Syntax highlighting style selection may be limited. pip install pygments") # Logged in SettingsService
    AVAILABLE_PYGMENTS_STYLES = ["native"] # Provide a fallback

# Role for storing token count in QTreeWidgetItems
TOKEN_COUNT_ROLE = Qt.UserRole + 1

# Size limit for calculating tokens automatically in file tree (in bytes)
TREE_TOKEN_SIZE_LIMIT = 100 * 1024

# --- Editor Theme Definitions ---
# Define color palettes for different themes
# Use conceptual names that map to lexer styles
NATIVE_DARK_PALETTE = {
    'editor_paper': "#1E1E1E", # Background
    'editor_color': "#E0E0E0", # Default text
    'caret_line_bg': "#333333", # Current line background
    'margins_bg': "#303030", # Margin background
    'margins_fg': "#888888", # Margin foreground (line numbers)
    'comment': "#6A9955", # Green
    'keyword': "#569CD6", # Blue
    'string': "#CE9178", # Orange/brown
    'number': "#B5CEA8", # Light green
    'operator': "#D4D4D4", # Grey/White (often same as default text)
    'class': "#4EC9B0", # Teal
    'function': "#DCDCAA", # Yellow
    'identifier': "#E0E0E0", # Default text (often same as editor_color)

    # Specific common styles that might not fit general categories
    'constant': "#B5CEA8", # Numbers, Booleans (often same as number)
    'variable': "#E0E0E0", # Default text
    'builtin': "#569CD6", # Built-in functions/types (often same as keyword)
    'definition': "#4EC9B0", # Function/Class definition names (often same as class/function)
    'escape': "#B5CEA8", # Escape sequences in strings

    # Diff specific styles
    'diff_added': "#00A000",
    'diff_deleted': "#D00000",
    'diff_changed': "#A0A0FF",
    'diff_header': "#B0B0B0",
    'diff_position': "#B5CEA8",

    # Markdown specific styles (mapping to conceptual names)
    'markdown_header': "#569CD6",
    'markdown_code': "#B5CEA8",
    'markdown_link': "#CE9178",
    'markdown_emphasis': "#CE9178", # Often styled like strings
    'markdown_strongemphasis': "#B5CEA8", # Often styled like numbers or constants
}

VS_DARK_PALETTE = {
    # Core Editor Colors
    'editor_paper': "#1E1E1E",        # Editor background
    'editor_color': "#D4D4D4",        # Default foreground text color
    'caret_line_bg': "#2A2A2A",       # Background of the line containing the caret (subtle)
    'margins_bg': "#252525",         # Background of line number margin
    'margins_fg': "#858585",         # Foreground of line number margin (line numbers)

    # Common Syntax Elements
    'comment': "#6A9955",            # Comments (Green)
    'keyword': "#569CD6",            # Keywords (if, for, class, def, import, etc.) (Blue)
    'string': "#CE9178",            # Strings (Orange/Brown)
    'number': "#B5CEA8",            # Numbers (Light Green)
    'operator': "#D4D4D4",            # Operators (+, -, =, etc.) (Same as default text)
    'class': "#4EC9B0",              # Class names (Teal)
    'function': "#DCDCAA",           # Function/method names (Yellow)
    'identifier': "#D4D4D4",        # Default identifier color (variables, parameters) (Same as default text)

    # More Specific Mappings (map to common VS Code token types)
    'constant': "#569CD6",           # Constants (True, False, None), often colored like keywords in VS Code
    'variable': "#9CDCFE",           # Variables (sometimes a lighter blue in VS Code, distinct from keywords) - Using a light blue here
    'parameter': "#9CDCFE",         # Function/method parameters (often same as variables)
    'builtin': "#569CD6",            # Built-in functions/types (print, len, str) (Same as keywords)
    'definition': "#4EC9B0",         # Name in Class/Function definition (Same as class color)
    'escape': "#D7BA7D",             # Escape sequences (\n, \t) within strings (often yellowish/brown)
    'decorator': "#DCDCAA",          # Decorators (@...) (Same as function)
    'docstring': "#CE9178",         # Docstrings (often same as regular strings)

    # Diff specific styles (Keep existing or adjust as needed)
    'diff_added': "#487e02",
    'diff_deleted': "#a1260d",
    'diff_changed': "#2667a1",
    'diff_header': "#a0a0a0",
    'diff_position': "#b5cea8",      # Often green like numbers/constants

    # Markdown specific styles (map to reasonable defaults or keep existing)
    'markdown_header': "#569CD6",      # Headers (Blue, like keywords)
    'markdown_code': "#CE9178",       # Inline/block code (Orange/Brown, like strings)
    'markdown_link': "#CE9178",       # Links (Orange/Brown, like strings)
    'markdown_emphasis': "#569CD6",   # Emphasis/Italic (Blue, like keywords/builtins)
    'markdown_strongemphasis': "#4EC9B0", # Strong/Bold (Teal, like class names)
    'markdown_quote': "#6A9955",      # Blockquotes (Green, like comments)
    'markdown_list': "#D4D4D4",       # List markers (Default text color)
}

PM_DARK_PALETTE = {
    # Core Editor Colors
    'editor_paper': "#282C34",       # Background (One Dark)
    'editor_color': "#ABB2BF",       # Default foreground (One Dark)
    'caret_line_bg': "#3A3F4B",      # Caret line (Subtle grey/blue)
    'margins_bg': "#21252B",        # Margin background
    'margins_fg': "#636D83",        # Margin foreground (line numbers)

    # Common Syntax Elements
    'comment': "#5C6370",           # Comments (Muted Green/Grey)
    'keyword': "#C678DD",           # Keywords (Purple)
    'string': "#98C379",           # Strings (Green)
    'number': "#D19A66",           # Numbers (Orange)
    'operator': "#56B6C2",         # Operators (Cyan)

    # More Specific Mappings (One Dark style)
    'class': "#E5C07B",             # Class names (Yellow)
    'function': "#61AFEF",          # Function names (Light Blue)
    'identifier': "#ABB2BF",       # Default identifiers (variables not specifically styled)
    'constant': "#D19A66",         # Constants (True, False, None) (Orange)
    'variable': "#E06C75",         # Variables (Reddish)
    'parameter': "#E06C75",        # Parameters (Reddish)
    'builtin': "#E5C07B",           # Built-in types/functions (Yellow, like class names)
    'definition': "#61AFEF",       # Name in def/class (Light Blue, like function names)
    'escape': "#D19A66",           # Escape sequences (Orange)
    'decorator': "#61AFEF",        # Decorators (@...) (Light Blue)
    'docstring': "#5C6370",        # Docstrings (Muted Green/Grey, like comments)

    # Diff specific styles (adjust to fit palette)
    'diff_added': "#98C379",       # Added (Green)
    'diff_deleted': "#E06C75",     # Deleted (Reddish)
    'diff_changed': "#61AFEF",     # Changed (Light Blue)
    'diff_header': "#ABB2BF",      # Header (Default text)
    'diff_position': "#D19A66",    # @@ numbers (Orange)

    # Markdown specific styles (adjust to fit palette)
    'markdown_header': "#61AFEF",     # Headers (Light Blue)
    'markdown_code': "#98C379",      # Code (Green, like strings)
    'markdown_link': "#E06C75",      # Links (Reddish)
    'markdown_emphasis': "#C678DD",  # Italic (Purple)
    'markdown_strongemphasis': "#E5C07B", # Bold (Yellow)
    'markdown_quote': "#5C6370",     # Blockquotes (Comment color)
    'markdown_list': "#ABB2BF",     # List markers (Default text)
    'markdown_hr': "#5C6370",        # Horizontal Rule (Comment color)
}

# ==========
AVAILABLE_RAG_MODELS = [ 'all-MiniLM-L6-v2', 'msmarco-distilbert-base-v4', 'all-mpnet-base-v2', ]

# Mapping from QsciLexer *style attribute names* (as strings) to conceptual palette keys
# Not every lexer has every attribute, hence the hasattr() checks in WorkspaceManager
LEXER_STYLE_ATTRIBUTE_MAP = {
    'Comment': 'comment',
    'CommentDoc': 'comment',
    'CommentLine': 'comment',
    'CommentDocKeyword': 'comment',
    'CommentDocKeywordError': 'comment',

    'Keyword': 'keyword',
    'KeywordSet2': 'keyword',
    'KeywordSet3': 'keyword',
    'KeywordSet4': 'keyword', # Some lexers have more sets
    'KeywordSet5': 'keyword',
    'KeywordSet6': 'keyword',

    'String': 'string',
    'SingleQuotedString': 'string',
    'DoubleQuotedString': 'string',
    'UnclosedString': 'string', # Error style for unclosed string? Might need separate color
    'VerbatimString': 'string',
    'Regex': 'string',
    'Character': 'string',
    'RawString': 'string',
    'TripleSingleQuotedString': 'string',
    'TripleDoubleQuotedString': 'string',
    'StringEOL': 'diff_deleted', # Usually an error style

    'Number': 'number',
    'Float': 'number',
    'Octal': 'number',
    'Hexadecimal': 'number',

    'Operator': 'operator',
    'Operator2': 'operator',

    'Class': 'class',
    'ClassName': 'class', # Often used for class definitions
    'Type': 'class', # Data types

    'Function': 'function',
    'DefName': 'function', # Python function definition names
    'FunctionMethodName': 'function', # Method names

    'Identifier': 'identifier', # Default identifier color

    'Constant': 'constant', # Generic constants (e.g., True, False, None in Python)
    'Variable': 'variable', # Generic variables
    'Builtin': 'builtin', # Built-in functions/keywords (print, len, if, for)
    'Definition': 'definition', # Function/Class definition points
    'EscapeSequence': 'escape', # Like \n, \t in strings

    # Diff Lexer specifics
    'Added': 'diff_added',
    'Deleted': 'diff_deleted',
    'Changed': 'diff_changed',
    'Header': 'diff_header',
    'Position': 'diff_position', # @@ line numbers

    # Markdown Lexer specifics
    'Header1': 'markdown_header',
    'Header2': 'markdown_header',
    'Header3': 'markdown_header',
    'Header4': 'markdown_header',
    'Header5': 'markdown_header',
    'Header6': 'markdown_header',
    'Code': 'markdown_code',
    'CodeBackticks': 'markdown_code',
    'CodeBlock': 'markdown_code',
    'Link': 'markdown_link',
    'LinkDescription': 'markdown_link',
    'LinkURL': 'markdown_link',
    'Emphasis': 'markdown_emphasis',
    'StrongEmphasis': 'markdown_strongemphasis',
    'Prechar': 'operator', # ``` etc
    'BlockQuote': 'comment', # >
    'ListMarker': 'operator', # -, *, 1.
    'LineBreak': 'comment',
    'HorizontalRule': 'comment',
    'HTML': 'string', # Inline HTML

    # YAML Lexer specifics
    'Document': 'comment', # --- ...
    'BlockFold': 'operator', # > |
    'BlockScalar': 'string', # Multiline strings
    'BlockSequence': 'operator', # -
    'BlockMapping': 'operator', # :
    'Scalar': 'string', # Values
    'Key': 'keyword', # Keys
    'Anchor': 'number', # &alias
    'Alias': 'number', # *alias
    'Tag': 'class', # !tag
    'Directive': 'class', # %YAML
    'Error': 'diff_deleted', # Error style
    'Text': 'identifier', # Plain text

    # Add mappings for other lexers as they are configured...
}

# Dictionary storing all theme definitions
THEME_DEFINITIONS = {
    "Native Dark": {
        'palette': NATIVE_DARK_PALETTE,
        'mapping': LEXER_STYLE_ATTRIBUTE_MAP, # Use the generic mapping
        # Theme-specific Scintilla settings not tied to a specific lexer style number
        'editor_paper': QColor(NATIVE_DARK_PALETTE['editor_paper']),
        'editor_color': QColor(NATIVE_DARK_PALETTE['editor_color']),
        'caret_line_bg': QColor(NATIVE_DARK_PALETTE['caret_line_bg']),
        'margins_bg': QColor(NATIVE_DARK_PALETTE['margins_bg']),
        'margins_fg': QColor(NATIVE_DARK_PALETTE['margins_fg']),
        # Could add selection colors, folding colors etc. here if they vary by theme
    },
     "VS Dark": {
        'palette': VS_DARK_PALETTE, # Use the VS Code Dark+ inspired palette
        'mapping': LEXER_STYLE_ATTRIBUTE_MAP, # Use the generic mapping
        # Theme-specific Scintilla settings not tied to a specific lexer style number
        # These are applied directly to the editor widget.
        'editor_paper': QColor(VS_DARK_PALETTE['editor_paper']),
        'editor_color': QColor(VS_DARK_PALETTE['editor_color']),
        'caret_line_bg': QColor(VS_DARK_PALETTE['caret_line_bg']),
        'margins_bg': QColor(VS_DARK_PALETTE['margins_bg']),
        'margins_fg': QColor(VS_DARK_PALETTE['margins_fg']),
        # Could add selection colors, folding colors etc. here if they vary by theme
    },
    "PM-Dark": {
        'palette': PM_DARK_PALETTE, # Use the new palette
        'mapping': LEXER_STYLE_ATTRIBUTE_MAP, # Use the generic mapping
        # Theme-specific Scintilla settings (use QColor instances)
        'editor_paper': QColor(PM_DARK_PALETTE['editor_paper']),
        'editor_color': QColor(PM_DARK_PALETTE['editor_color']),
        'caret_line_bg': QColor(PM_DARK_PALETTE['caret_line_bg']),
        'margins_bg': QColor(PM_DARK_PALETTE['margins_bg']),
        'margins_fg': QColor(PM_DARK_PALETTE['margins_fg']),
        # Could add selection colors, folding colors etc. here if they vary by theme
    },
    # Example of another theme (colors are placeholders)
    # "Solarized Light": {
    #     'palette': {
    #         'editor_paper': "#FDF6E3", # Base background
    #         'editor_color': "#657B83", # Base text
    #         'comment': "#93A1A1",
    #         'keyword': "#859900",
    #         'string': "#2AA198",
    #         # ... other colors ...
    #         'diff_added': "#859900",
    #         'diff_deleted': "#DC322F",
    #         # ...
    #     },
    #     'mapping': LEXER_STYLE_ATTRIBUTE_MAP, # Can reuse the same mapping
    #     'editor_paper': QColor("#FDF6E3"),
    #     'editor_color': QColor("#657B83"),
    #     'caret_line_bg': QColor("#EEE8D5"),
    #     'margins_bg': QColor("#EEE8D5"),
    #     'margins_fg': QColor("#93A1A1"),
    # },
}

# List of theme names available in the UI dropdown
AVAILABLE_SCINTILLA_THEMES = list(THEME_DEFINITIONS.keys())