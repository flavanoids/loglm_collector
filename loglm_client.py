"""HTTP client for the LogLM API with file-output fallback."""

import json
from pathlib import Path

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

from rich.console import Console

console = Console(stderr=True)

_DEFAULT_BASE_URL = "http://localhost:8000"


def check_api_running(base_url: str = _DEFAULT_BASE_URL) -> bool:
    """Return True if the LogLM API is reachable at base_url."""
    if not _REQUESTS_AVAILABLE:
        return False
    try:
        response = requests.get(base_url + "/", timeout=2)
        return response.status_code < 500
    except Exception:  # pylint: disable=broad-except
        return False


def send_entries(entries: list[dict], base_url: str = _DEFAULT_BASE_URL) -> list[dict]:
    """POST each entry to the LogLM API, return list of response dicts."""
    if not _REQUESTS_AVAILABLE:
        console.print("[red]requests library not available; cannot send to API.[/red]")
        return []

    results = []
    for entry in entries:
        try:
            response = requests.post(
                base_url + "/analyze",
                json=entry,
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                results.append({**entry, "Response": data.get("response", data.get("Response", ""))})
            else:
                console.log(f"[yellow]API returned {response.status_code} for entry[/yellow]")
                results.append({**entry, "Response": f"API error: {response.status_code}"})
        except Exception as e:  # pylint: disable=broad-except
            console.log(f"[red]Failed to send entry to API: {e}[/red]")
            results.append({**entry, "Response": f"Send error: {e}"})

    return results


def save_to_file(entries: list[dict], output_path: Path) -> None:
    """Write LogLM entries as a JSON file."""
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
    console.print(f"[green]Saved {len(entries)} entries to {output_path}[/green]")
