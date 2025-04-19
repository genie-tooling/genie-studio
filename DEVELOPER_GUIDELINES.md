# PatchMind IDE - Developer Guidelines & Best Practices

## 1. Introduction

This document outlines coding standards, architectural principles, and best practices for developing the PatchMind IDE. Adhering to these guidelines aims to:

*   Improve code consistency and readability.
*   Reduce bugs, especially those related to threading and UI updates.
*   Enhance maintainability and scalability.
*   Facilitate collaboration (even if currently solo).

This is a living document and should be updated as the project evolves.

## 2. General Python Style

*   **PEP 8:** Strictly adhere to [PEP 8](https://www.python.org/dev/peps/pep-0008/).
*   **Tooling:** Use `black` for code formatting and `ruff` for linting (as configured in `pyproject.toml`). Run these tools before committing code.
*   **Imports:** Organize imports according to PEP 8 (standard library, third-party, local application). Use absolute imports for local modules where possible (e.g., `from pm.core.chat_manager import ChatManager`).
*   **Long lines:** DO NOT use excessive amounts of semi-colons on a line. PEP8 standards.
*   **Colons:** NEVER EVER put colons on a line with another colon or semi-colon. NEVER put if/def/class/when/try/except/finally on a line with any other statement that would require a semicolon. If you come across this *FIX IT*.

## 3. Qt / PyQt6 Specific Guidelines

### 3.1. Naming Conventions

*   **Classes:** `UpperCamelCase` (e.g., `MainWindow`, `ConfigDock`, `ChatMessageWidget`).
*   **Methods & Functions:** `snake_case` (e.g., `_build_ui`, `populate_file_tree`).
*   **Internal/Private Methods:** `_leading_underscore_snake_case` (e.g., `_handle_provider_change`, `_update_token_count`). Use this for methods not intended to be called directly from outside the class.
*   **pyqtSignals:** `snake_case_pyqtSignal = pyqtSignal(...)` (e.g., `history_changed = pyqtSignal()`, `provider_changed = pyqtSignal(str)`). While Qt C++ uses camelCase, `snake_case` aligns better with Python conventions. Be consistent.
*   **pyqtSlots:**
    *   Use descriptive `snake_case` names, often prefixed with `_handle_` (for direct user actions) or `_on_` (reacting to pyqtSignals or events). Examples: `_handle_send_button_click`, `_on_worker_finished`, `_handle_provider_change_from_dock`.
    *   **Crucially:** Decorate pyqtSlots intended to be called via pyqtSignals (especially across threads) with `@pyqtSlot(...)` from `PyQt6.QtCore`, including type hints (e.g., `@pyqtSlot(str)`, `@pyqtSlot(int, int)`).
*   **UI Element Variables:** `self.descriptive_name_widget_type` (e.g., `self.send_button`, `self.chat_input_edit`, `self.provider_combo`).

### 3.2. pyqtSignals & pyqtSlots (PyQt6 Specifics)

*   **Purpose:** The primary mechanism for communication between `QObject`s, especially across threads and between loosely coupled components.
*   **Definition:** Define pyqtSignals at the class level using `pyqtSignal()`. Include type hints for parameters (`pyqtSignal(str, bool)`).
*   **Emission:** Emit pyqtSignals using `self.pyqtSignal_name.emit(value1, value2)`. Keep the logic within the emitting method minimal; the pyqtSignal is just a notification.
*   **Connection:** Connect pyqtSignals to pyqtSlots in the component that *owns* the pyqtSlot or orchestrates the interaction (often `MainWindow` or a parent widget). Example: `self.config_dock.provider_changed.connect(self._handle_provider_change_from_dock)`. The modern PyQt6 `connect` syntax is the same as PyQt6 (`pyqtSignal.connect(pyqtSlot)`).
*   **Disconnection:** Usually handled automatically by Qt's parent-child object destruction. Manually disconnect (`pyqtSignal.disconnect(pyqtSlot)`) only if explicitly needed (e.g., dynamically created connections that outlive the emitter or receiver in specific ways).
*   **Type Safety:** Ensure the types defined in the `pyqtSignal(...)` match the types in the `@pyqtSlot(...)` decorator and the pyqtSlot method signature. Mismatches can lead to runtime errors or silent failures.
*   **Avoid Logic in Emitters:** The method that *emits* a pyqtSignal should ideally just emit it. The *pyqtSlot* that *receives* the pyqtSignal should contain the handling logic.

### 3.3. Threading (`QThread` and Worker Objects)

*   **Problem:** Long-running tasks (network requests, LLM inference, file I/O, complex computations) **must not** block the main GUI thread, otherwise the application freezes.
*   **Solution:** Use the **Worker-Object-Moved-to-Thread** pattern:
    1.  Create a worker class inheriting from `QObject`.
    2.  Implement the long-running task logic inside a method of the worker (e.g., `process()`).
    3.  Define pyqtSignals in the worker class to report progress, results, or errors (e.g., `progress = pyqtSignal(int)`, `finished = pyqtSignal(result_type)`, `error = pyqtSignal(str)`).
    4.  In the main GUI thread (e.g., `MainWindow`):
        *   Create a `QThread` instance: `self.worker_thread = QThread(self)` (parent it).
        *   Create a worker instance: `self.worker = Worker(...)`.
        *   **Crucially:** Move the worker to the thread: `self.worker.moveToThread(self.worker_thread)`.
        *   Connect worker pyqtSignals to main thread pyqtSlots (`@pyqtSlot`-decorated) for UI updates.
        *   Connect thread pyqtSignals: `self.worker_thread.started.connect(self.worker.process)`.
        *   **Mandatory Cleanup:** Connect pyqtSignals for proper teardown:
            *   `self.worker.finished.connect(self.worker_thread.quit)`
            *   `self.worker.finished.connect(self.worker.deleteLater)`
            *   `self.worker_thread.finished.connect(self.worker_thread.deleteLater)`
        *   Start the thread: `self.worker_thread.start()`.
*   **Communication:**
    *   **Worker -> Main Thread:** Only via pyqtSignals emitted by the worker, connected to pyqtSlots in the main thread.
    *   **Main Thread -> Worker:** Only via pyqtSignals emitted by the main thread connected to worker pyqtSlots, OR by calling worker methods *before* starting the thread (e.g., passing data in `__init__`). **Never call worker methods directly from the main thread after `moveToThread` has been called.**
*   **Data Sharing:** Pass necessary data to the worker via its `__init__`. Avoid shared mutable state where possible. If complex state is needed, consider thread-safe mechanisms or passing copies.
*   **GUI Access:** **Never** access or modify GUI elements (`QWidget` subclasses or properties) directly from the worker thread. Use pyqtSignals to ask the main thread to perform the update.
*   **Interruption:** Provide a mechanism to stop long-running tasks gracefully.
    *   In the main thread, call `self.worker_thread.requestInterruption()`.
    *   Inside the worker's long loops or blocking operations, frequently check `QThread.currentThread().isInterruptionRequested()` and exit cleanly if `True`.

### 3.4. UI Updates

*   **Rule:** All updates to `QWidget` properties (text, visibility, enabled state, etc.) **must** happen on the main GUI thread.
*   **Mechanism:** Use pyqtSignals from worker threads or manager classes connected to pyqtSlots in the relevant UI class (`MainWindow`, `ConfigDock`, `ChatMessageWidget`, etc.) that perform the actual widget modification.

### 3.5. Widget Management

*   **Layouts:** Use Qt layout managers (`QVBoxLayout`, `QHBoxLayout`, `QGridLayout`, `QFormLayout`) extensively. Avoid fixed widget sizes and positions (`setGeometry`, `setFixedSize`) unless absolutely necessary. Layouts handle resizing and platform differences gracefully.
*   **Parenting:** Assign a `parent` widget when creating child widgets (`widget = QPushButton("Click", self)`). Qt's object tree handles memory management; child widgets are typically deleted when their parent is deleted. This simplifies cleanup, especially for complex UIs.
*   **Custom Widgets:** Encapsulate reusable UI elements with their logic into custom widgets (like `ChatMessageWidget`). This promotes modularity.

## 4. Architectural Principles

### 4.1. Separation of Concerns (SoC)

*   **UI Layer (`pm.ui`):** Contains `QWidget` subclasses (`MainWindow`, `ConfigDock`, Dialogs, Custom Widgets). Responsible for:
    *   Displaying data.
    *   Handling user input *events* (button clicks, text changes).
    *   Emitting pyqtSignals based on user actions.
    *   Receiving pyqtSignals to update the display.
    *   *Minimal* business logic.
*   **Core/Logic Layer (`pm.core`):** Contains non-UI classes (`ChatManager`, `WorkspaceManager`, Services like `OllamaService`, `Worker`, utility functions). Responsible for:
    *   Managing application state (chat history, open files, settings data).
    *   Implementing business rules and logic.
    *   Interacting with external services or APIs.
    *   Performing background tasks.
    *   Communicating with the UI layer via pyqtSignals/pyqtSlots.
*   **Goal:** Keep UI classes focused on presentation and event handling. Keep core classes independent of specific UI implementations.

### 4.2. State Management

*   **Configuration (`settings`):** The dictionary loaded/saved via `project_config.py` holds persistent configuration.
    *   `MainWindow` typically owns the master copy (`self.settings`).
    *   **Shared State Warning:** Passing `self.settings` directly to other components (like `ConfigDock`) creates shared mutable state. Be disciplined:
        *   Components receiving the reference should primarily *read* from it for initial population.
        *   Changes should be pyqtSignaled back to `MainWindow` to update the master copy.
        *   Direct modification should only occur in designated places (e.g., `MainWindow` pyqtSignal handlers, `ConfigDock.update_settings_from_ui` just before saving).
        *   Consider passing *copies* (`settings.copy()`) to components that don't need to modify the original, especially background workers.
*   **Runtime State:** Use dedicated manager classes (`ChatManager`, `WorkspaceManager`) to handle dynamic state like chat history, open editor widgets, file tree status.

### 4.3. Communication Patterns

*   **Orchestration:** `MainWindow` often acts as the central orchestrator, connecting components:
    *   User interacts with `ConfigDock` -> `ConfigDock` emits pyqtSignal -> `MainWindow` pyqtSlot handles pyqtSignal, updates `self.settings`, possibly calls a Manager or Service -> Service/Manager/Worker eventually emits pyqtSignal -> `MainWindow` pyqtSlot updates UI (maybe `ConfigDock` or `ChatMessageWidget`).
*   **Managers:** Managers (`ChatManager`, `WorkspaceManager`) encapsulate state and logic for a specific domain. They emit pyqtSignals when their state changes, which `MainWindow` (or other relevant UI components) can connect to for updates.

## 5. Common Pitfalls & How to Avoid Them

*   **GUI Freeze:** **Cause:** Performing long-running operations on the main thread. **Solution:** Use the `QThread`/Worker pattern (Section 3.3).
*   **Threading Errors (`AttributeError: 'builtin_function_or_method' object has no attribute`, Crashes):** **Cause:** Often related to incorrect thread affinity (accessing GUI from worker), premature object deletion (worker/thread deleted before finished), or race conditions. **Solution:** Strictly follow the Worker pattern, ensure `deleteLater` is used, connect pyqtSignals/pyqtSlots correctly, avoid direct cross-thread method calls after `moveToThread`. Use assertions or logging to check object validity (`self.thread is not None`, `isinstance(self.thread, QThread)`).
*   **Shared Mutable State Conflicts:** **Cause:** Multiple components modifying the same dictionary (`settings`) without clear ownership or synchronization. **Solution:** Follow disciplined access patterns (Section 4.2), use pyqtSignals for updates, pass copies where appropriate.
*   **pyqtSignal/pyqtSlot Mismatches:** **Cause:** Connecting pyqtSignals/pyqtSlots with incompatible parameter types or counts. Forgetting `@pyqtSlot`. **Solution:** Use type hints in `pyqtSignal(...)` and `@pyqtSlot(...)`, double-check connections. Qt often prints warnings to the console for connection errors.
*   **Callback Hell / Complex `MainWindow`:** **Cause:** `MainWindow` becomes overly burdened with handling all logic and connections. **Solution:** Extract functionality into dedicated UI components (`ConfigDock`), manager classes, and services. Keep `MainWindow` focused on orchestrating these components.
*   **Memory Leaks:** **Cause:** `QObject`s not being deleted, often due to missing parent assignments or improper thread cleanup. **Solution:** Use parent-child relationships, follow the `deleteLater` pattern for worker threads.

## 6. Documentation & Typing

*   **Docstrings:** Write clear docstrings for all classes and non-trivial methods/functions (e.g., Google style). Explain *what* the code does and *why*.
*   **Type Hints:** Use Python's type hints (`typing` module) extensively for function signatures, variables, and class attributes. This improves code clarity, enables static analysis, and helps prevent type-related errors.

## 7. Conclusion

Consistency and adherence to these principles, especially regarding threading and separation of concerns, are vital for building a robust and maintainable PatchMind IDE. When unsure, prioritize clarity, simplicity, and the Qt best practices outlined here.
