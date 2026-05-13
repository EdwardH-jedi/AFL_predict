"""
orchestration/jobs/roles/
--------------------------
Role-level audit jobs — one per orchestration role defined in .claude/agents/.

Each module is read-only: it inspects DB state, feature parquets, and model
artifacts, then writes a JSON artifact to
    storage/daily_summaries/roles/{role_name}/{YYYY-MM-DD}.json

These jobs run last in the daily pipeline (soft, never block). Their outputs
are the source of truth for both the matching Claude subagent and the
upcoming stats UI.
"""
