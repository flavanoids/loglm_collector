# Plan: Guiding Users to Fine-Tune an LLM via LogLM

This document outlines how **loglm_collector** can guide users from “I want to train a log model” to “I have clean LogLM-format data and know the next steps.” It covers the current flow, gaps, open-source options, and a streamlined direction.

---

## 1. Current state

### 1.1 End-to-end flow today

```
main.py
  → Detect profiles (General, GPU, NAS)
  → Top menu: [1] Collect logs | [2] Manage templates | [3] Label responses
  → If Collect: select template → confirm profiles → set time range per profile → output (file or API)
  → format_entries() → LogLM JSON {Instruction, Input, Response}
  → Optional: Label responses (annotate Response) → _labeled.json
```

- **Collect**: Template first, then profile confirmation, then time range per profile, then output mode. No single “issue type” shortcut (e.g. “only kernel panics”).
- **Templates**: Built-in presets (nvidia-training-cluster, amd-rocm-workstation, llm-inference-server, zfs-nas-server) + user templates with instruction rules and custom sources. Instruction rules match on source/pattern/level.
- **Labeling**: Load a `loglm_output_*.json`, walk entries one-by-one, type Response; save as `*_labeled.json`. No batch hints, no “issue category” filter to label only e.g. kernel or GPU.

### 1.2 Issue coverage (what we already collect)

| Issue category        | Where it comes from                    | Collector   |
|-----------------------|----------------------------------------|-------------|
| Kernel panics / oops   | journalctl -k (OOM/panic/oops filter)  | General     |
| OOM kills             | Same + General errors                  | General     |
| Auth failures         | auth.log / secure                      | General     |
| Systemd failed units   | systemctl --failed                     | General     |
| GPU (NVIDIA/AMD)       | journalctl -k, nvidia-smi, rocm-smi, Xorg, service journals | GPU    |
| Storage / NAS          | journalctl -k, zpool, mdadm, smartctl  | NAS         |
| Process activity       | Only indirectly (e.g. OOM victim, rocm-smi PIDs); no dedicated process log collector | — |

So today we already cover **kernel panics, GPU activity, memory (OOM), and storage** via profiles + templates. **Process activity** is partial (OOM, GPU PIDs) and could be expanded.

### 1.3 Gaps vs “menu to pinpoint issues and pipe to clean format”

- **No issue-centric menu**: Users pick “profiles” (General, GPU, NAS) and time range, not “I want kernel panics + GPU errors only.” Mapping from “issue type” to sources is in collector logic and templates, not in the UI.
- **Template-first is heavy**: To get the right instructions you must pick or create a template before collection. No “quick collect by issue type” with sensible default instructions.
- **Labeling is entry-by-entry**: No way to “label only kernel entries” or “label only GPU entries” to speed up training-data creation.
- **No explicit “fine-tuning path”**: README and UI don’t spell out: Collect → (optional) Label → feed to LogLM / your trainer. Users may not see the tool as the first step of a fine-tuning pipeline.

---

## 2. Target: streamlined “pinpoint issues → clean format” flow

Goals:

1. **Issue-centric options in the menu** — e.g. “What do you want to collect?” with shortcuts: Kernel panics & oops, GPU activity, Memory (OOM), Process/application, Storage/NAS, Auth failures, or “Everything (all profiles).”
2. **One-click-style defaults** — Choosing “Kernel panics” implies: General collector, journalctl -k + OOM/panic/oops filters, time range prompt, default instruction (e.g. “Interpret this kernel panic or oops…”). No requirement to create a template first.
3. **Clean, consistent output** — Already achieved: LogLM JSON + optional .txt bundle. Keep it; optionally add a “training-ready” hint (e.g. “Save as LogLM fine-tuning JSON”).
4. **Labeling by issue type** — Option to filter the loaded JSON by Instruction/source/pattern so users can “label only GPU entries” or “only kernel,” then merge back or save a subset.
5. **Clear fine-tuning story in UI and docs** — e.g. “Collect → Label (optional) → Use with LogLM” and a short “Next steps” (LogLM repo, dataset format, training commands if documented by LogLM).

---

## 3. Open-source landscape: what can streamline vs build from scratch

### 3.1 Log collection and structuring

| Tool / area            | Role | Use for loglm_collector |
|------------------------|------|---------------------------|
| **journalctl / systemd** | Already used | Keep as primary source; no replacement needed. |
| **Fluent Bit / Vector** | Ship logs to backends, optional JSON/OTLP | Could *consume* our JSON later in a pipeline; not a replacement for “collect + format for LogLM” in one menu. Use if we ever add “stream to Fluent Bit” as an output. |
| **OpenTelemetry (OTLP)** | Standard for traces/metrics/logs | LogLM format is instruction/input/response, not OTLP. We could map our output to OTLP for observability stacks, but for fine-tuning the current JSON is the right shape. |
| **Bakalog, LogDetective, LILAC, LogBatcher** | Log parsing, template extraction, sometimes LLM-based | Focus is parsing/template mining, not “collect from this machine + produce LogLM instruction dataset.” We already produce the right format; we could *optionally* call out to a parser (e.g. LILAC) to pre-process raw lines before wrapping in Instruction/Input/Response if we want structured fields later. Not required for “pinpoint issues → clean format.” |

**Conclusion**: For “menu-driven collect from this box → LogLM JSON,” building on the current design is correct. External tools can sit *around* the pipeline (e.g. Fluent Bit for shipping, LILAC for parsing experiments), not replace the collector/formatter.

### 3.2 LogLM and instruction-style datasets

- **LogLM** already uses instruction-response pairs; our JSON matches. The repo’s “Instruction Dataset of LogLM.json” is the same idea. We don’t need another format.
- **loghub-2.0, UNLEASH** — benchmarks and parsing; useful for research. Our value is “your machine, your logs, your instructions” in one tool.

**Conclusion**: Stay aligned with LogLM’s format and docs; add a “Next steps for fine-tuning” section that points to LogLM and, if available, their training instructions.

### 3.3 What to build vs reuse

- **Reuse**: journalctl, systemd, nvidia-smi, rocm-smi, zpool, smartctl, mdadm, existing collectors, TemplateStore, Rich UI.
- **Build (in loglm_collector)**:
  - **Issue-centric menu**: map “Kernel panics”, “GPU activity”, “Memory (OOM)”, “Process activity”, “Storage”, “Auth”, “All” to profile(s) + optional template or default instructions.
  - **Default instructions per issue type**: small in-code map (e.g. kernel_panic → “Interpret this kernel panic or oops…”) so “quick collect by issue” doesn’t require a template.
  - **Labeling filters**: filter loaded JSON by keyword/Instruction/source before entering the label loop; optional “save filtered subset” for training.
  - **Docs + in-app copy**: “Fine-tuning path” (Collect → Label → LogLM) in README and a short “Next steps” after save/label.

We do **not** need to replace our collectors with Fluent Bit/Vector or implement a full log parser; we only need to make the existing pipeline easier to drive by issue type and to document the path to fine-tuning.

---

## 4. Proposed streamlined flow

### 4.1 Top menu (unchanged, plus optional “Quick start”)

- **1. Collect logs** — enters the new flow below.
- **2. Manage templates** — unchanged.
- **3. Label responses** — unchanged, plus optional “Filter by issue type” (see 4.3).
- **q. Quit**

Optional later: “0. Quick start: collect for fine-tuning” that prints a one-liner (“We’ll collect logs, then you can label and feed to LogLM”) and then jumps into Collect with an “issue type” prompt.

### 4.2 Collect flow: issue-centric + template-optional

1. **Detect profiles** (as now).
2. **“What do you want to collect?”**
   - **Kernel panics & oops** → General, default instruction for kernel/panic/oops; time range.
   - **GPU activity (errors / diagnostics)** → GPU (+ General if desired); default GPU instructions; time range.
   - **Memory (OOM, high usage)** → General (OOM); default OOM instruction; time range.
   - **Process / application activity** → General + optional custom source; default “Analyze this process/system log”; time range. (Future: dedicated ProcessCollector if we add one.)
   - **Storage / NAS** → NAS; default storage instructions; time range.
   - **Auth failures** → General (auth); default auth instruction; time range.
   - **All (recommended)** → Current behavior: confirm all detected profiles, time range per profile, template selector.
3. **Time range**: single prompt for “quick” modes (1h / 6h / 24h / 7d); for “All”, keep per-profile if we want, or unify.
4. **Template**: For “All”, keep template selector. For issue-centric choices, use **default instructions** (no template required); optional “Apply a template anyway?” for power users.
5. **Output**: file vs API (unchanged). Optional copy: “Saved. Use **Label responses** to add Response text for fine-tuning, then see README for LogLM.”

This keeps “Manage templates” for advanced users while making the common case (“I want kernel + GPU”) a few choices.

### 4.3 Label flow: filter by issue type

- After loading `loglm_output_*.json`, optional step: **“Label only a subset?”** with filters:
  - By **keyword in Instruction** (e.g. “kernel”, “GPU”, “OOM”).
  - By **keyword in Input** (e.g. “amdgpu”, “oom_kill”).
  - By **source** if we persist it in JSON (currently we don’t; could add a non-invasive `_source` field for filtering).
- Then run the existing entry-by-entry label loop on the filtered list; save to `*_labeled.json` (full or subset). This reduces noise when building training data for a specific issue type.

### 4.4 “Process activity” and future collectors

- Today: OOM victim, GPU PIDs (rocm-smi), service unit names. No dedicated “process” log source.
- Option A: Add a **ProcessCollector** (e.g. journalctl by unit, or /var/log/app/*, or custom source only) and an issue shortcut “Process / application activity” that enables it + default instruction.
- Option B: Treat “Process” as “General + custom source” only; document “Add a custom source for your app logs” and keep one “Process / application” menu item that selects General + prompts for a custom path/glob. Option B is enough for “pinpoint issues” without new code; Option A improves one-stop coverage.

---

## 5. Implementation steps (priority order)

1. **Document the fine-tuning path**  
   - In README: “Workflow: Collect → (optional) Label → Use with LogLM.”  
   - Add a “Next steps for fine-tuning” section with link to LogLM and dataset format.  
   - Optional: after saving collection, print one line: “To build training data: run again → Label responses.”

2. **Add issue-type → profile + default instruction map**  
   - In code: e.g. `ISSUE_TYPE_CONFIG = {"kernel_panic": (["general"], "Interpret this kernel panic or oops…"), "gpu": (["gpu"], …), …}`.  
   - Use this when “What do you want to collect?” is not “All.”

3. **Implement “What do you want to collect?” menu**  
   - New step in collection flow (before or instead of “confirm profiles” when not “All”): choices Kernel, GPU, Memory, Process, Storage, Auth, All.  
   - For non-All: set profiles and default instructions from map; single time range; skip template unless “Apply template?” yes.  
   - For All: keep current confirm-profiles + per-profile time + template select.

4. **Optional: persist `_source` (or similar) in JSON**  
   - When formatting, add a field (e.g. `_source`) so Labeler can filter by source without parsing Input.  
   - Keep LogLM schema as Instruction/Input/Response for compatibility; extra field for tooling only.

5. **Labeler: filter by issue type / keyword**  
   - After load, prompt “Filter entries? (e.g. kernel, gpu, oom)” with optional keyword(s) or “no filter.”  
   - Run label loop on filtered list; save same format.  
   - If we added `_source`, offer “Filter by source” as well.

6. **Process / application**  
   - Short term: “Process / application” = General + prompt for one custom source (path/glob) and default instruction.  
   - Later: consider ProcessCollector if users need more (e.g. multiple app logs, unit-based).

7. **Optional: “Quick start” top-level entry**  
   - Single option that explains Collect → Label → LogLM and jumps into issue-centric collect.

---

## 6. Summary

- **Current tool** already covers kernel panics, GPU, memory (OOM), storage, auth via profiles and templates; process is partial.
- **Streamlining** = issue-centric menu (“pinpoint issues”) with default instructions and optional template, plus labeling by issue/keyword and clear “fine-tuning path” in docs and UI.
- **Open-source**: Keep using journalctl/systemd and current collectors; no need to replace them with Fluent Bit/Vector for this use case. LogLM format stays; optional integrations (Fluent Bit, parsers) can sit around the pipeline later.
- **Concrete work**: (1) Docs + next steps, (2) issue-type config and menu, (3) optional JSON `_source` and labeler filters, (4) process = General + custom source, then optional ProcessCollector and “Quick start” entry.

This plan keeps the codebase focused while making “collect by issue → clean LogLM JSON → label → fine-tune” obvious and easy from the menu.
