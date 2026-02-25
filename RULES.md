# RULES.md — Coding Rules

Non-negotiable rules for every file in this project.
All changes must pass all checks before being considered done.

---

## Lint gates

```bash
python3 -m py_compile <file>          # zero syntax errors
python3 -m pylint ... --disable=C,R0801  # exactly 10.00/10
python3 -m pyflakes <file>            # zero warnings
```

`--disable=C` suppresses convention messages (docstring style, naming).
`--disable=R0801` suppresses duplicate-code detection across collectors (expected structural similarity).
All other pylint categories — E, W, R — must be clean or explicitly suppressed with an inline comment.

---

## Subprocess

Every subprocess call goes through `run_command()` in `collectors/base.py`. No exceptions.

```python
# correct
output = run_command(["journalctl", "-k", "--since", since], timeout=30)

# forbidden — never do these
subprocess.run("journalctl -k", shell=True, ...)   # no shell=True
subprocess.run(["cmd"], ...)                        # no direct subprocess calls in collectors
os.system(...)                                      # never
```

`run_command()` guarantees: list-form args, `check=False`, explicit timeout, `encoding="utf-8"`, graceful handling of missing binaries and timeouts.

---

## Exceptions

```python
# correct — specific
except OSError:
except FileNotFoundError:
except subprocess.TimeoutExpired:

# correct — broad with justification
except Exception as e:  # pylint: disable=broad-except
    console.log(f"[red]...: {e}[/red]")

# forbidden
except:          # bare except
except Exception:  # broad without pylint disable comment
```

Never suppress exceptions silently. At minimum log them to `console.log`.

---

## File I/O

```python
# correct
with open(path, encoding="utf-8") as fh:
    ...

# for user-defined paths that may contain binary or mixed content
with open(path, encoding="utf-8", errors="replace") as fh:
    ...

# binary read — only permitted for /proc virtual files that use null-byte delimiters
with open(cmdline_path, "rb") as fh:
    raw_bytes = fh.read(512)
cmdline = raw_bytes.replace(b"\x00", b" ").decode("utf-8", errors="replace")

# forbidden
open(path)            # no encoding argument
open(path, "r")       # implicit encoding
```

---

## Type hints

All public functions and method signatures must have type hints.
Return types are required. `Optional[X]` is acceptable; `X | None` (Python 3.10+ union syntax) is also acceptable and preferred for new code.

```python
# correct
def collect(self, hours: int) -> list[LogEntry]:
def get_name(self) -> str:
def run_command(cmd: list[str], timeout: int = 30) -> str:

# forbidden
def collect(self, hours):
def get_name(self):
```

Private helpers (`_foo`) should have type hints unless the types are trivially obvious from context and pylint does not complain.

---

## Imports

No unused imports. Imports must be at the top of the file.
Exception: `import glob as globmod` inside a method is acceptable in `collector/nas.py` (avoids shadowing the builtin) but should not be replicated elsewhere.

Imports inside functions (`import outside toplevel`) are permitted only in `main.py` to avoid circular imports, and only where necessary.

---

## f-strings

Do not use f-strings that contain no interpolated variables.

```python
# forbidden
fh.write(f"LogLM Collector\n")

# correct
fh.write("LogLM Collector\n")
```

---

## Pylint inline suppressions

Use inline suppressions only when pylint is wrong and the code is correct.
Always include the reason as a comment.

```python
# correct — dataclass with intentionally few methods
@dataclass  # pylint: disable=too-few-public-methods

# correct — broad except is necessary here, all errors must not crash the collector
except Exception as e:  # pylint: disable=broad-except
```

Do not suppress E-level (error) warnings. If pylint raises an E, fix the code.

---

## LogLM output contract

Every dict written to a `loglm_output_*.json` file must have exactly these keys:

```python
{
    "Instruction": str,   # non-empty
    "Input": str,         # the raw log line — never empty
    "Response": str,      # "" at collection time; populated by labeler or API
}
```

No additional keys. No nested structures. This is the interface with LogLM.

---

## What is never added

- `shell=True` in any subprocess call
- Bare `except` clauses
- `print()` calls — use `console.print()` or `console.log()`
- File writes without explicit `encoding=`
- New third-party dependencies beyond `rich` and `requests`
- Global mutable state outside of module-level constants
