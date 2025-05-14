# PatchMind IDE - Roadmap TODO (Generated: 2025-04-18)

## ✅ Recently Addressed / Partially Implemented

*   **Settings Management:**
    *   Created centralized `SettingsService`. (DONE)
    *   Refactored `SettingsDialog` to handle global settings (API Keys, Global RAG Defaults, Features, Appearance). (DONE - Review Responsibilities vs ConfigDock)
    *   `ConfigDock` now handles project-specific LLM selection, RAG source *enablement*, and prompt selection. (DONE)
*   **UI / Core:**
    *   Implemented background fetching for model lists (`ModelListService`) with improved thread cleanup. (DONE)
    *   Implemented LLM service switching (`LLMServiceProvider`). (DONE)
    *   Implemented RAG fetching (DDG, Bing, ArXiv) and basic ranking (`rag_service.py`). (DONE - Needs Directory/Code support)
    *   Implemented token limit display and enforcement in `MainWindow`/`ConfigDock`. (DONE)
    *   Implemented unsaved changes confirmation for editor tabs. (DONE)
    *   Implemented dirty indicator (`*`) for editor tabs. (DONE)
    *   Implemented file tree context menu (Open, Check/Uncheck, Expand). (DONE)
    *   Implemented recursive check/uncheck for file tree directories. (DONE)
*   **Guidelines:**
    *   Applied `@Slot` decorators with type hints extensively in Handler classes. (DONE - Verify completeness)
    *   Standardized `Worker` thread cleanup pattern (Implemented in `ModelListService`, needs review in `TaskManager`). (PARTIAL)

---

## 🔥 Blockers & Critical Tasks (Bugs, Missing Core Features, Refactoring)

*   [ ] **Prompt Management:**
    *   [ ] Implement `PromptEditorDialog` for creating and editing prompts.
    *   [ ] Integrate `PromptEditorDialog` with `PromptActionHandler` (`handle_new_prompt`, `handle_edit_prompt`).
    *   [ ] Implement prompt storage/retrieval within `SettingsService` (currently only `selected_prompt_ids` seems managed).
    *   [ ] Implement prompt deletion logic in `SettingsService` and connect `PromptActionHandler.handle_delete_prompt`.
    *   [ ] Integrate selected prompts into `Worker`'s context preparation (`_prepare_final_prompt`). Consider how multiple prompts are combined.
*   [ ] **`MainWindow` Refactoring:**
    *   [ ] Break down `MainWindow` (still large) into smaller, more focused components/handlers (e.g., `MainUI`, `ChatUI`, `FileTreeUI`, `StatusBarController`, `ActionManager`). Follow SoC principles.
*   [ ] **Threading Robustness:**
    *   [ ] **Review `TaskManager` thread lifecycle:** Thoroughly audit the start/stop/cleanup logic (`_request_stop_and_wait`, `_on_thread_finished`, `_finalize_generation`) against `DEVELOPER_GUIDELINES.md`. Simplify if possible, ensure no race conditions or leaks.
    *   [ ] **Review `Worker` interruption pattern:** Simplify `background_tasks.Worker._is_interruption_requested()` to primarily rely on `QThread.currentThread().isInterruptionRequested()` as per guidelines, reducing internal flag complexity if feasible.
*   [ ] **RAG Enhancements:**
    *   [ ] Implement RAG directory walking/processing within `Worker` or `rag_service` (currently only handles files listed in `rag_local_sources` or checked files).
    *   [ ] Add settings (UI in `SettingsDialog`? `ConfigDock`?) for RAG directory crawling depth, file inclusion/exclusion patterns (beyond basic `IGNORE_DIRS`/`IGNORE_EXT`).
    *   [ ] Refactor file token estimation for accuracy and potentially speed (currently basic `tiktoken` count).
*   [ ] **Testing:**
    *   [ ] **Add Unit Tests (Pytest):** Prioritize core logic: `SettingsService`, `ChatManager`, `Worker` (mocked services), `rag_service`, `model_registry`.
    *   [ ] **Add Integration/UI Tests (QTest):** Cover key workflows: Open project, load file, edit+save, send chat, receive stream, change settings via dock, check/uncheck files, token limit enforcement.

---

## 🔁 Changes & Feature Enhancements

*   [ ] **Prompt Execution Modes:** (Design/Implement)
    *   [ ] **Automatic Mode:** Apply selected prompt(s) automatically to the currently active editor file.
    *   [ ] **Batch Mode:** Allow multi-select from file tree, apply prompt sequentially to files, show progress.
*   [ ] **Diff/Patch Improvements:**
    *   [ ] Implement "Apply Patch" functionality in `DiffDialog`.
    *   [ ] Integrate `DiffDialog` with LLM responses that generate patches.
    *   [ ] Consider Git integration for context-aware patching and diffing.
*   [ ] **File Tree:**
    *   [ ] Add settings (e.g., in `SettingsDialog` under Features/Appearance) to control visibility of hidden files/directories (`.*`).
    *   [ ] Implement confirmation dialogs for destructive actions (Rename/Delete - requires adding these actions first).
*   [ ] **UI/UX:**
    *   [ ] Improve chat input usability when LLM is busy (e.g., clearer visual indication beyond disabled button).
    *   [ ] Add UI feedback for background token estimation progress/status in status bar.
    *   [ ] Deduplicate send button logic/state management if possible (currently handled in `ChatActionHandler` and `MainWindow`).
    *   [ ] Review `ChatActionHandler`/`ChatMessageWidget` interaction for list item sizing stability (related to `fix.sh`).
*   [ ] **Configuration:**
    *   [ ] Add Import/Export functionality for project settings (`.patchmind.json`).
    *   [ ] Use Enums or Constants for dictionary keys used across modules (settings, message formats, etc.).
    *   [ ] Validate API Key / Model mismatches during provider/model selection (e.g., warn if Gemini selected but no key).
*   [ ] **Extensibility:**
    *   [ ] Design/Implement plugin registry for Summarizers (Factory Pattern).
    *   [ ] Modularize LLM task execution logic within `Worker` for easier addition of new task types (e.g., code completion, refactoring).

---

## 🧪 Testing Roadmap

*   [ ] **Unit Tests (Pytest):** (Cover items listed in Blockers section)
    *   [ ] `SettingsService` load/save/validation/get/set.
    *   [ ] `ChatManager` history manipulation, signals.
    *   [ ] `Worker` context gathering logic (mock file system/services).
    *   [ ] `rag_service` fetching and ranking logic (mock external APIs/models).
    *   [ ] `model_registry` listing and context limit resolution.
    *   [ ] `WorkspaceManager` file operations, editor tracking.
    *   [ ] Prompt template formatting logic.
*   [ ] **Integration/UI Tests (QTest):** (Cover items listed in Blockers section)
    *   [ ] Open project -> Tree populates -> File double-click -> Editor opens.
    *   [ ] Edit file -> Save action enables -> Save -> Dirty indicator clears.
    *   [ ] Type in chat -> Send -> AI response streams -> Edit/Delete message.
    *   [ ] Check/uncheck files -> Token count updates -> Limit enforces deselection.
    *   [ ] Change provider/model in dock -> Model list updates -> Context limit updates.
    *   [ ] Open Settings Dialog -> Change theme/font -> Changes apply.