# PatchMind IDE - Roadmap TODO

## ✅ Completed

- v0.1

---

## 🔥 Blockers (Bugs & Structural Deficiencies)

- [ ] Refactor Settings Dialog (`pm/ui/settings_dialog.py`)
  - [ ] Remove widgets now handled by `ConfigDock`
  - [ ] Keep widgets for API Keys, RAG Defaults, Appearance Defaults
  - [ ] Update `SettingsDialog._populate_all_fields()` and `_on_accept()`
  - [ ] Update `MainWindow._open_settings()` logic to handle settings copy/merge/save
- [ ] Update `DEFAULT_CONFIG` with `prompts` and `selected_prompt_ids`
- [ ] Validate `prompts` and `selected_prompt_ids` in `load_project_config`
- [ ] Update `save_project_config` to include prompt data
- [ ] Create and integrate `PromptEditorDialog`
- [ ] Implement `_new_prompt`, `_edit_prompt`, `_delete_prompts` in `MainWindow`
- [ ] Integrate prompt logic with `Worker.__init__`
- [ ] Modify `Worker._prepare_final_prompt` for prompt ID lookup
- [ ] Ensure prompt data is passed in `MainWindow._initiate_llm_stream`
- [ ] Update context estimation and truncation logic
- [ ] Implement RAG directory walking using `walk`/`rglob`
- [ ] Add RAG max results/ranking settings to UI and logic
- [ ] Refactor file token estimation for speed and accuracy
- [ ] Improve Diff dialog integration with inline apply logic
- [ ] Refactor `MainWindow` (>3000 LOC compressed) into modular components
- [ ] Create centralized `SettingsService` to replace raw dict access
- [ ] Move constants to a centralized config/constants module
- [ ] Add `@Slot(...)` decorators to all signal receivers
- [ ] Standardize `Worker` thread cleanup pattern with `deleteLater`
- [ ] Confirm unsaved changes before tab/window close
- [ ] Add dirty indicator to file tabs in `WorkspaceManager`
- [ ] Confirm before destructive actions in file tree (rename/delete)
- [ ] Integrate Git awareness and patching in DiffDialog
- [ ] Validate API key/model mismatch in provider selection
- [ ] Add import/export for project settings
- [ ] Add unit tests with Pytest for core components
- [ ] Improve chat input usability when LLM is busy
- [ ] Add inline feedback for signal/slot validation
- [ ] Preview theme/font changes before saving
- [ ] Use enums/constants for keys like `provider`, `model`, `theme`
- [ ] Ensure signal-slot disconnection where needed (dynamic objects)
- [ ] Create summarizer plugin registry (factory-based)
- [ ] Modularize LLM task execution for extensibility
- [ ] Add UI feedback for token estimation accuracy in status bar

---

## 🔁 Changes (New Features, Design Goals)

### ✨ Prompt Execution Modes

- [ ] **Automatic Mode**
  - [ ] Detect currently open/active file
  - [ ] Apply prompt to open file and edit inline with streaming updates
  - [ ] Add toggle in ConfigDock or toolbar

- [ ] **Batch Mode**
  - [ ] Allow multi-select from file tree
  - [ ] Apply prompt one-by-one to files
  - [ ] Show progress per file, allow cancel/skip

### 🧠 Architectural Enhancements

- [ ] Introduce `SettingsService` with defaults, validation, mutation
- [ ] Refactor `MainWindow` into modular subcomponents:
  - [ ] `MainUI`
  - [ ] `ChatHandlers`
  - [ ] `PromptHandlers`
  - [ ] `FileTreeHandlers`
  - [ ] `SettingsHandlers`
- [ ] Add factory and registry support for LLM providers/summarizers
- [ ] Encapsulate all dialogs and connect lazily via factory
- [ ] Add RAG & summarizer support indicators in UI
- [ ] Deduplicate send button logic and improve tooltips
- [ ] Add appearance test (light/dark, syntax highlighting)

---

## 🧪 Testing Roadmap

- [ ] Add Pytest-based unit tests
- [ ] Test prompt management logic
- [ ] Test `Worker` signal flow
- [ ] Test file manager CRUD ops
- [ ] Test configuration load/save accuracy
- [ ] Add QTest-based UI integration tests (edit/save/stream)

Notes:
The tree view does not show hidden (.file) files. We should surface any extensions/dirs/nice-to-be-able-tochange things that are being excluded in an 'advanced' section of the settings. Give me a plan for this.