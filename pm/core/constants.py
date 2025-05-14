# pm/core/constants.py
from PySide6.QtCore import Qt

# Role for storing token count in QTreeWidgetItems
TOKEN_COUNT_ROLE = Qt.UserRole + 1

# Size limit for calculating tokens automatically in file tree (in bytes)
# Keep this consistent with WorkspaceManager or move that one here too
TREE_TOKEN_SIZE_LIMIT = 100 * 1024

# You could move other shared constants here if needed