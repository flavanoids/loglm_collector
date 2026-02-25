# CLAUDE.md — LogLM Collector

Working instructions for Claude Code on this project.

---

## Project purpose

`loglm_collector` collects Linux system logs, formats them as LogLM-native
`{Instruction, Input, Response}` JSON, and either sends them to a local LogLM
FastAPI server (`localhost:8000`) or saves them to file.

Companion tool to [LogLM](https://github.com/lunyiliu/LogLM).

---

## Verify before and after every change

```bash
# Syntax
python3 -m py_compile main.py detector.py log_formatter.py loglm_client.py \
    collectors/*.py templates/store.py ui/menu.py ui/template_builder.py

# Lint (must stay 10.00/10)
python3 -m pylint main.py detector.py log_formatter.py loglm_client.py \
    collectors/ templates/ ui/ --disable=C,R0801

# Import hygiene
python3 -m pyflakes main.py detector.py log_formatter.py loglm_client.py \
    collectors/*.py templates/store.py ui/menu.py ui/template_builder.py
```

All three must pass clean. A score below 10.00 on pylint is a failure.

---

## Running the tool

```bash
cd /root/claude_code/loglm_collector
python3 main.py
```

Interactive menus only — no CLI flags. Pipe input for non-interactive testing:

```bash
printf "1\n1\ny\nn\nn\n3\n" | python3 main.py 2>&1
```

---

## Architecture — read this before editing

```
main.py
  → SystemDetector.detect()          # detector.py
  → TemplateStore.all()              # templates/store.py
  → select_template()                # ui/template_builder.py
  → InteractiveMenu.run()            # ui/menu.py  → CollectionConfig
  → _collect_all(config, template)   # runs BaseCollector subclasses
  → format_entries(entries, template)# log_formatter.py
  → save_to_file() / send_entries()  # loglm_client.py
  → menu.show_summary()
```

The three action paths from the top menu:
- **1 — Collect logs**: full pipeline above
- **2 — Manage templates**: `TemplateManager(store).run()`
- **3 — Label responses**: `ResponseLabeler().run()`

---

## Adding a new collector

1. Create `collectors/<name>.py`, subclass `BaseCollector` from `collectors/base.py`
2. Implement all four abstract methods: `collect`, `get_name`, `get_description`, `get_log_sources`
3. Use `run_command()` for all subprocess calls — never call `subprocess` directly
4. Register in `collectors/__init__.py` → `COLLECTOR_REGISTRY`
5. Add detection logic to `SystemDetector._detect_<name>()` in `detector.py`
6. Run lint — must stay 10.00/10

---

## Key conventions

**Subprocess** — always via `run_command()` in `collectors/base.py`. Never use `shell=True`, never call `subprocess` directly from collector code.

**File reads** — always `encoding="utf-8"` or `encoding="utf-8", errors="replace"` (custom collector).

**Exceptions** — no bare `except`. Use `except OSError` for file ops, `except Exception as e` only where justified, with a `# pylint: disable=broad-except` comment.

**Module name** — the formatter is `log_formatter.py`, not `formatter.py` (stdlib name conflict).

**Template persistence** — `~/.config/loglm_collector/templates.json`. `TemplateStore` handles all reads/writes.

**LogLM format** — every output entry must be `{"Instruction": str, "Input": str, "Response": str}`. The `Response` field is always `""` at collection time; it is populated by the labeler or the API.

---

## Dependencies

```
rich>=13.0.0
requests>=2.28.0
```

No other third-party packages. `requests` is optional — `loglm_client.py` degrades gracefully if unavailable.
