# PatchMind IDE - TODO & Roadmap (Generated: 2025-04-19)

*This list reflects the current state based on code analysis and previous TODOs. Priorities may need adjustment.*

## ✅ Recently Addressed / Partially Implemented

*   **Settings Management:** Centralized `SettingsService` handles loading/saving project config (`.patchmind.json`); `SettingsDialog` handles global settings; `ConfigDock` handles project LLM/RAG enablement/Prompts. UI persistence uses `QSettings`. Prompt CRUD implemented via `PromptEditorDialog` and `SettingsService`. (DONE)
*   **LLM/RAG:** Background model list fetching (`ModelListService`), LLM provider switching (`LLMServiceProvider`), basic RAG fetching (`rag_service`), token limit display/basic enforcement. (DONE)
*   **UI / Core:** Editor tab dirty state/close confirmation, File tree context menu/recursive check, Basic Change Queue UI/workflow structure, Improved worker interruption (`isInterruptionRequested`). (DONE)
*   **Guidelines:** `@pyqtSlot` usage improved, Worker cleanup pattern reviewed. (DONE)
*   **Initial Layout:** Splitter sizes are now set via `QTimer` after initial show, using `QSettings` for persistence. (DONE)

---

## 🚨 Critical Blockers / High Priority (Technical Debt, Risks, Core Functionality)

*(These items represent significant risks to stability, maintainability, or core feature reliability. Addressing these should be prioritized.)*

1.  [ ] **Refactor `MainWindow` Complexity:** `MainWindow` remains a large orchestrator, coupling many components and handlers. Break down further (e.g., `MainUIManager`, `ChatUIManager`, `WorkspaceUIManager`, `StatusBarController`, specific event routers) to improve SoC and reduce complexity. (Was: `MainWindow` Refactoring)
2.  [ ] **Refactor `Worker` (background_tasks.py):** The current `Worker` handles *multiple* LLM workflows (Direct, Plan/Critic/Execute) and complex context gathering. This violates SRP and makes it hard to maintain/extend. Refactor into smaller, focused worker classes or strategies per task type.
3.  [ ] **Improve `SettingsService` State Management:** Eliminate passing the mutable `settings` dictionary directly. Implement safer patterns: Use pyqtSignals for all updates, pass copies, or create dedicated data classes/accessors managed by `SettingsService` to prevent unintended side-effects across components (especially `ConfigDock`, `Worker`). (Was: Shared Mutable State Conflicts)
4.  [ ] **Robust Error Handling & Reporting:** Systematically improve error handling, especially for background tasks (LLM calls, RAG fetches, file I/O). Define clear error states, provide informative user feedback (dialogs, status bar), and ensure consistent logging for easier debugging.
5.  [ ] **Testing - Unit Tests:** Implement comprehensive unit tests (Pytest) for core logic: `SettingsService`, `ChatManager`, `LLMServiceProvider`, `model_registry`, `rag_service`, `TaskManager`, `Worker` refactors (mocked services), `ChangeQueueHandler` logic (esp. `_find_original_block`), `project_config` helpers. (Was: Testing)
6.  [ ] **Testing - Integration/UI Tests:** Implement integration tests (QTest) covering key workflows: Project load, file open/edit/save, chat send/receive/stream, config changes (dock/dialog), RAG context selection/limit, change queue interaction (view/apply/reject), prompt management. (Was: Testing)
7.  [ ] **Robust Patch Application:** Integrate `python-patch` reliably into `ChangeQueueHandler`. Handle various patch scenarios (hunk failures, offsets, context changes), provide clear feedback on success/failure, and implement safe fallback mechanisms (e.g., offer manual copy). (Was: Patch Application)
8.  [ ] **`ChangeQueueHandler` Matching Reliability:** Enhance `_find_original_block`. Current `SequenceMatcher` + regex approach can be fragile. Explore more robust diffing/matching algorithms or libraries tolerant to surrounding code changes. Consider fallback to manual selection if confidence is low.
9.  [ ] **Threading Robustness (`TaskManager`):** Thoroughly review and test the `TaskManager` thread lifecycle, especially `_request_stop_and_wait`, `_disconnect_pyqtSignals`, `_finalize_generation`. Ensure it handles rapid start/stop cycles, errors during worker execution, and potential race conditions reliably. (Was: Threading Robustness)
10. [ ] **State Synchronization Issues:** Audit pyqtSignal/pyqtSlot connections related to state updates between core services (`SettingsService`, `LLMServiceProvider`, `WorkspaceManager`) and UI elements (`ConfigDock`, `StatusBarController`, editor states). Ensure UI consistently reflects the underlying state, especially after async operations or settings changes.
11. [ ] **RAG Token Estimation Accuracy:** Refactor token counting for RAG context files (`_add_file_context` in `Worker`). Current `tiktoken` count might be inaccurate for some Ollama models. Consider: a) using model-specific tokenizers if feasible, b) sampling large files, c) caching token counts, d) clearer UI feedback on estimation progress/accuracy. (Was: RAG Enhancements)
12. [ ] **Context Limit Resolution Robustness:** The `resolve_context_limit` logic relies heavily on parsing `ollama show` or heuristics. This can break with new models or Ollama updates. Implement more robust error handling, potentially allow manual override, and ensure graceful failure if limit cannot be determined.
13. [ ] **Security - API Key Storage:** API keys currently stored potentially in plain text within `.patchmind.json` via `SettingsService`. This is insecure. Investigate using platform-specific secure storage (Keychain on macOS, Credential Manager on Windows, Secret Service/KWallet on Linux) or secure environment variable handling.
14. [ ] **Memory Usage Monitoring/Optimization:** Profile memory usage, especially related to embedding models (`sentence-transformers`), large file contexts, and chat history. Implement strategies to mitigate high usage if necessary (e.g., unloading models, context pruning, caching optimizations).
15. [ ] **Handler Interdependencies & Coupling:** Review how handlers (`ChatActionHandler`, `WorkspaceActionHandler`, `SettingsActionHandler`, etc.) interact. Minimize direct dependencies between them. Prefer communication via `MainWindow` orchestration or core service pyqtSignals to reduce coupling.
16. [ ] **RAG Service Reliability:** Improve resilience of `rag_service.py` against external API failures (timeouts, rate limits, unexpected responses from DDG/Bing/ArXiv). Implement retries, better error reporting, and potential caching.
17. [ ] **Optional Dependency Handling (`python-patch`):** Ensure features degrade gracefully if optional dependencies like `python-patch` are not installed. Provide clear UI indication when a feature is unavailable due to missing dependencies.
18. [ ] **Startup Performance Optimization:** Profile application startup time. Identify bottlenecks (e.g., initial model loading, settings parsing, file tree scan) and optimize where possible (e.g., deferred loading, caching).
19. [ ] **UI Responsiveness (Non-LLM):** Profile UI responsiveness during potentially long operations like large file tree population, opening very large files, or complex syntax highlighting. Move blocking operations off the main thread if necessary.
20. [ ] **Code/Architecture Documentation:** Improve inline code comments, especially for complex logic (threading, context gathering, state management). Consider generating architecture diagrams or higher-level documentation to supplement `DEVELOPER_GUIDELINES.md`.

---

## 📈 Core Feature Gaps / Refactoring

*   [ ] **Refactor `rag_service.py`:** Improve structure, error handling, and potentially add more sources or configuration options.
*   [ ] **Modularize LLM Workflows:** Refactor `Worker.process` logic to separate Plan/Critic/Execute and Direct Execution into distinct, testable functions or strategy classes.
*   [ ] **Configuration Validation:** Enhance validation within `SettingsService` (`_validate_config`, `set_setting`) to catch more edge cases and provide clearer warnings/errors. Use Enums/Constants for setting keys.
*   [ ] **Token Counting Abstraction:** Abstract the token counting logic (`token_utils.py`) to potentially support different tokenizers based on the selected LLM model/provider in the future.

---

## ✨ Feature Enhancements / UX

*   [ ] **Prompt Execution Modes:** Implement Automatic and Batch prompt application modes as outlined in the old TODO.
*   [ ] **Diff/Patch Improvements:** Consider Git integration for better context-aware diffing/patching. Improve `DiffDialog` presentation.
*   [ ] **File Tree Enhancements:** Add settings for hidden file visibility. Implement file/directory rename and delete actions (with confirmations). Add filtering/searching.
*   [ ] **UI/UX Improvements:**
    *   Clearer visual indication when LLM is busy (beyond disabled button).
    *   Progress indication for background token estimation/RAG fetching in status bar.
    *   Review/refine `ChatActionHandler`/`ChatMessageWidget` size hint stability.
    *   Improve focus management between input fields and lists.
*   [ ] **Configuration Import/Export:** Add functionality to import/export project settings (`.patchmind.json`).
*   [ ] **Extensibility:** Design plugin system for Summarizers, LLM task types, RAG sources.

## 📋 Additional Items for TODO.md

1.  [ ] **Guideline Violation: Semicolons:** Widespread use of semicolons for multiple statements per line across many files (e.g., `change_queue_handler.py`, `chat_action_handler.py`, etc.), violating Guideline 2. Refactor to adhere to one statement per line. (Addressed by refactor script)
2.  [ ] **Initialization Order/Timing:** Potential timing issues related to UI initialization and state population, hinted at by deferred calls (`QTimer.singleShot(0, ...)`) in `PromptActionHandler`[cite: 355, 356], `MainWindow` splitter sizing[cite: 627, 629], and model updates[cite: 652, 656]. Review and simplify initialization sequence.
3.  [ ] **pyqtSignal Management Complexity:** Disconnecting/reconnecting pyqtSignals for the Send/Stop button in `MainWindow` during LLM generation is complex and potentially fragile. Investigate alternative state management for the button.
4.  [ ] **Performance: Tree Token Calculation:** Iterating through potentially large file trees to sum tokens in `MainWindow._get_checked_tokens` could be slow. Profile and optimize if necessary (e.g., caching, background calculation).
5.  [ ] **Performance: Token Limit Enforcement:** Iterating through the tree to enforce token limits in `MainWindow._check_and_enforce_token_limit` could be slow. Profile and optimize enforcement logic.
6.  [ ] **Performance/Robustness: RAG Crawling:** Directory crawling logic in `background_tasks.py` using `fnmatch` might be slow or fragile for complex include/exclude patterns or deep directory structures set in settings. Evaluate performance and robustness.
7.  [ ] **Robustness: Ollama Model Unloading:** Unloading previous Ollama models via `QTimer` in `LLMServiceProvider` [cite: 932, 940] might not complete if the application closes quickly after switching models. Ensure unload completes reliably on exit.
8.  [ ] **Robustness: Stale Model Cache:** The `model_registry` list cache is only cleared at startup[cite: 974]. It could become stale if external models (e.g., Ollama pulls/removes) change while the application is running. Implement a cache refresh mechanism or reduce TTL.
9.  [ ] **Accuracy: Binary File Detection:** The heuristic used in `model_registry._is_likely_binary` to exclude files from context gathering is basic and might misclassify files (e.g., certain data formats, non-UTF8 text files). Improve detection logic.
10. [ ] **Dependency Declaration Inconsistency:** `sentence-transformers` is listed in `requirements.txt` but not in `pyproject.toml`, leading to potential installation issues depending on the method used. Unify dependency declarations.
11. [ ] **Inconsistency: Search API Calls:** Search function signatures differ; `search_ddg` uses a positional query argument[cite: 1129], while `search_bing` uses a keyword argument `query=`[cite: 1132]. Standardize function signatures.
12. [ ] **API Consistency/Missing Methods:** Use of `hasattr` checks in `PromptActionHandler` when calling `ConfigDock` methods [cite: 368] suggests potential for missing methods or inconsistent APIs between components. Review component interactions.

---

## 🧪 Testing Roadmap

*   *(Cover items listed in the `🚨 Critical Blockers` section)*
*   **Unit Tests:** `SettingsService`, `ChatManager`, `LLMServiceProvider`, `model_registry`, `rag_service`, `TaskManager`, `Worker` refactors, `ChangeQueueHandler`, `token_utils`, `project_config` helpers.
*   **Integration/UI Tests:** Core workflows (Project Load/Save, Chat, RAG Context, Change Queue, Settings Dialog, Prompt Mgmt). Test interactions between handlers and core services. Test threading scenarios under load.
