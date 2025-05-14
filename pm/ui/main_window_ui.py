# pm/ui/main_window_ui.py
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QPlainTextEdit, QTreeWidget, QDockWidget,
                             QListWidget, QPushButton, QTabWidget, QLabel,
                             QHeaderView, QSizePolicy)
from PySide6.QtCore import Qt
from loguru import logger
import qtawesome as qta

# Import ConfigDock here
from .config_dock import ConfigDock
# Import ChangeQueueWidget for type hint/reference
from .change_queue_widget import ChangeQueueWidget

class MainWindowUI:
    """
    Responsible for building the main UI widgets and layout,
    but does not handle application logic or signals.
    """
    def __init__(self):
        logger.debug("Initializing MainWindowUI...")
        # Widgets that need to be accessed externally
        self.file_tree_widget: QTreeWidget = None
        self.editor_tab_widget: QTabWidget = None
        self.chat_list_widget: QListWidget = None
        self.chat_input_edit: QPlainTextEdit = None
        self.send_button: QPushButton = None
        self.config_dock: ConfigDock = None
        self.main_splitter: QSplitter = None
        self.select_all_button: QPushButton = None
        self.deselect_all_button: QPushButton = None
        # Reference to the change queue widget (added to ConfigDock UI)
        self.change_queue_widget: ChangeQueueWidget = None
        logger.debug("MainWindowUI initialized.")

    def setup_ui(self, main_window: QMainWindow, settings: dict):
        """Creates and arranges the main UI widgets."""
        logger.debug("MainWindowUI: Setting up UI...")

        # Column 1: File Tree & Controls
        self.file_tree_container = QWidget()
        file_tree_layout = QVBoxLayout(self.file_tree_container)
        file_tree_layout.setContentsMargins(0,0,0,0)
        file_tree_layout.setSpacing(2)
        self.file_tree_widget = QTreeWidget()
        self.file_tree_widget.setObjectName("file_tree")
        self.file_tree_widget.setColumnCount(2)
        self.file_tree_widget.setHeaderLabels(["Name", "Tokens"])
        self.file_tree_widget.header().setStretchLastSection(False)
        self.file_tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree_widget.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # --- ADJUSTED TOKEN COLUMN SIZE ---
        self.file_tree_widget.header().resizeSection(1, 65) # Reduced size
        self.file_tree_widget.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.file_tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        file_tree_layout.addWidget(self.file_tree_widget, 1)

        tree_button_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.deselect_all_button = QPushButton("Deselect All")
        tree_button_layout.addWidget(self.select_all_button)
        tree_button_layout.addWidget(self.deselect_all_button)
        file_tree_layout.addLayout(tree_button_layout)

        # Column 2: Editor Tabs
        self.editor_tab_widget = QTabWidget()
        self.editor_tab_widget.setObjectName("editor_tabs")
        self.editor_tab_widget.setTabsClosable(True)
        self.editor_tab_widget.setMovable(True)
        self.editor_tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Column 3: Chat Area
        self.chat_area_widget = QWidget()
        chat_layout = QVBoxLayout(self.chat_area_widget)
        chat_layout.setContentsMargins(5,5,5,5)
        chat_layout.setSpacing(5)
        self.chat_list_widget = QListWidget()
        self.chat_list_widget.setObjectName("chat_list_widget")
        self.chat_list_widget.setAlternatingRowColors(True)
        self.chat_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        chat_layout.addWidget(self.chat_list_widget, 1)

        chat_input_layout = QHBoxLayout()
        chat_input_layout.setSpacing(5)
        self.chat_input_edit = QPlainTextEdit()
        self.chat_input_edit.setObjectName("chat_input")
        self.chat_input_edit.setPlaceholderText("Enter your message or /command...")
        self.chat_input_edit.setFixedHeight(60)
        self.chat_input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        chat_input_layout.addWidget(self.chat_input_edit, 1)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("send_btn")
        self.send_button.setIcon(qta.icon('fa5s.paper-plane', color='white'))
        self.send_button.setFixedHeight(60)
        self.send_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        chat_input_layout.addWidget(self.send_button)
        chat_layout.addLayout(chat_input_layout)
        self.chat_area_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Column 4: Config Dock (Widget)
        # ConfigDock is passed the current effective settings
        # It now internally creates the ChangeQueueWidget as well
        self.config_dock = ConfigDock(settings, main_window) # Pass main_window as parent
        self.config_dock.setObjectName("config_dock")
        self.config_dock.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        # --- Store reference to the change queue widget created inside ConfigDock ---
        self.change_queue_widget = self.config_dock.change_queue_widget

        # Main Horizontal Splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, main_window)
        self.main_splitter.addWidget(self.file_tree_container)
        self.main_splitter.addWidget(self.editor_tab_widget)
        self.main_splitter.addWidget(self.chat_area_widget)
        self.main_splitter.addWidget(self.config_dock) # Add the dock widget itself
        main_window.setCentralWidget(self.main_splitter)

        # Initial Splitter Sizes (Consider moving sizes to settings?)
        tree_width = 200
        editor_width = 400
        chat_width = 400
        config_width = 280 # Slightly wider to accommodate change queue
        self.main_splitter.setSizes([tree_width, editor_width, chat_width, config_width])
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setCollapsible(3, False)
        self.main_splitter.setStretchFactor(1, 1) # Editor tab area
        self.main_splitter.setStretchFactor(2, 1) # Chat area

        logger.debug("MainWindowUI: UI setup complete.")

    # --- Add Getters for key widgets ---
    @property
    def file_tree(self) -> QTreeWidget: return self.file_tree_widget
    @property
    def tab_widget(self) -> QTabWidget: return self.editor_tab_widget
    @property
    def chat_list(self) -> QListWidget: return self.chat_list_widget
    @property
    def chat_input(self) -> QPlainTextEdit: return self.chat_input_edit
    @property
    def send_btn(self) -> QPushButton: return self.send_button
    @property
    def config_dock_widget(self) -> ConfigDock: return self.config_dock
    @property
    def tree_select_all_btn(self) -> QPushButton: return self.select_all_button
    @property
    def tree_deselect_all_btn(self) -> QPushButton: return self.deselect_all_button
    # Getter for the change queue widget (referenced from ConfigDock)
    # @property
    # def change_queue(self) -> ChangeQueueWidget: return self.config_dock_widget.change_queue_widget

