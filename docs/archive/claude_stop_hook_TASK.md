# TASK — Stop-hook Setup

## Scope

Install a two-stage `Stop` hook for Claude Code in this repo:

1. **Quality gate** on changed Python files (ruff + py_compile).
2. **Codex diff review** with structured verdict, saved under `reviews/`.

Both hooks respect `stop_hook_active` to prevent infinite Stop loops and emit
a structured `{"decision":"block","reason":...}` JSON only when there is a
real reason to block.

## Deliverables

- [x] `.claude/settings.json` registers both hooks under the `Stop` event.
- [x] `.claude/hooks/stop-quality-gate.sh` — ruff + py_compile, block on failure.
- [x] `.claude/hooks/codex-review.sh` — codex exec, save to `reviews/`,
      block only on `VERDICT: CRITICAL`.
- [x] `docs/PLAN.md` describes the design.
- [x] `docs/TASK.md` (this file) describes the task and verification.

## Verification

Run these once to confirm the setup is wired correctly:

```bash
# 1. Scripts are present and parse cleanly under bash.
bash -n .claude/hooks/stop-quality-gate.sh
bash -n .claude/hooks/codex-review.sh

# 2. Dry-run the quality gate with an empty stdin payload (should exit 0
#    unless there are ruff errors in your working tree).
echo '{}' | bash .claude/hooks/stop-quality-gate.sh; echo "exit=$?"

# 3. Dry-run the Codex review. Produces a file under reviews/ unless there
#    are no changes or codex is absent.
echo '{}' | bash .claude/hooks/codex-review.sh; echo "exit=$?"
ls -1 reviews/ | tail -3

# 4. Confirm the recursion guard short-circuits cleanly.
echo '{"stop_hook_active": true}' | bash .claude/hooks/stop-quality-gate.sh; echo "exit=$?"
echo '{"stop_hook_active": true}' | bash .claude/hooks/codex-review.sh; echo "exit=$?"
```

All four commands should exit `0`. Command 3 should either write a new
`reviews/<timestamp>-codex-review.md` (or `*-skipped.md` if `codex` is not
installed) or exit silently if there is no diff.

## Notes

- `reviews/` is generated at runtime. Add it to `.gitignore` if you do not
  want review artefacts committed.
- To disable the Codex step temporarily, remove or comment out the second
  hook entry in `.claude/settings.json`.
- Both hooks are safe to re-run manually — they are idempotent and never
  mutate repo state.
