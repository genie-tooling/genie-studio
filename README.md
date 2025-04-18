# PatchMind IDE

PatchMind is an AI-enhanced code editor with inline LLM support, real-time prompt workflows, and RAG-based file context awareness.

## ✨ Features

- **LLM Chat Integration** — Chat with Gemini or Ollama-backed models
- **Inline Editing** — Apply prompts directly to open documents
- **Prompt Manager** — Save, reuse, and batch-apply prompts to files
- **Real-Time Context** — File tree with checkboxes for RAG context control
- **Token Awareness** — Visual context token tracking and budgeting
- **Themes & Fonts** — Customizable editor appearance
- **Multi-Provider Support** — Easily switch between LLMs

## 🔧 Requirements

- Python 3.11+
- PySide6

Install dependencies:

```bash
poetry install
# or
pip install -r requirements.txt
```

## 🚀 Running

```bash
poetry run patchmind
# or
python -m pm
```

## 🧠 Development

- Auto-format: `black .`
- Lint: `ruff .`

## 🗂 Project Structure

```
pm/
├── core/               # Logic, config, services
├── ui/                 # Qt widgets & dialogs
├── __main__.py         # Entry point
```

## 📋 Guidelines

- Follows [PEP8](https://peps.python.org/pep-0008/) with `black` & `ruff`
- Use `Signal/Slot` correctly with type annotations
- Never modify the GUI from non-main threads — use signals

## 📄 License

MIT © Kal Aeolian