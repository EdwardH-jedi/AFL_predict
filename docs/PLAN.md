# PLAN — Claude Code Stop-hook Workflow

This repository runs Claude Code with an automated gate on the `Stop` event.
When Claude finishes an implementation turn, two hooks run in sequence before
the session is allowed to settle:

1. **Quality gate** — `.claude/hooks/stop-quality-gate.sh`
   Lightweight static checks on changed `*.py` files:
   - `ruff check` (if installed)
   - `python -m py_compile` (fallback syntax check)
   A failure returns a structured `{"decision": "block", ...}` JSON so Claude
   re-opens the task and fixes the issue before stopping.

2. **Codex diff review** — `.claude/hooks/codex-review.sh`
   Sends the full pending diff (staged + unstaged + untracked) to
   `codex exec` with a review prompt prioritising correctness, regressions,
   security, maintainability, and scope drift. The full report is saved under
   `reviews/<timestamp>-codex-review.md`. Claude is blocked **only** when
   Codex explicitly returns `VERDICT: CRITICAL`.

## Design rules

- **No infinite loops.** Both hooks read the `stop_hook_active` field from the
  stdin JSON Claude Code supplies. If it is `true`, the hook exits 0 immediately
  — a hook must never re-block a stop that was already triggered by a hook.
- **Graceful when tools are missing.** Absent `ruff`, `codex`, or even `python`
  is a soft-skip, not a crash. A `reviews/*-skipped.md` breadcrumb is written
  when Codex is unavailable.
- **Block sparingly.** The quality gate blocks only on real lint/syntax errors.
  Codex blocks only on an explicit `VERDICT: CRITICAL` line. Everything else
  is advisory and surfaces through the saved report.
- **Bash only.** Both scripts run under `bash` (git-bash on Windows, any POSIX
  bash elsewhere). Invoked via `bash .claude/hooks/...` in settings.json so
  executable bits are not required on Windows.
- **Diff cap.** Codex input is truncated at 4,000 diff lines to keep review
  latency and cost bounded; the full diff is always visible via `git`.
- **Reports are durable.** Everything Codex returns is saved to `reviews/`
  whether or not the verdict blocks — easy to audit later.

## Files owned by this workflow

- `.claude/settings.json` — registers the two Stop hooks.
- `.claude/hooks/stop-quality-gate.sh` — cheap lint/syntax gate.
- `.claude/hooks/codex-review.sh` — Codex review + block-on-critical logic.
- `reviews/` — generated; one markdown report per Stop event.
- `docs/PLAN.md` — this file.
- `docs/TASK.md` — operator-facing task / verification notes.
