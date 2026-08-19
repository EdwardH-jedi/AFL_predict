# Archived documents

Everything in this directory is **historical**. These files record plans,
status snapshots, and exploratory designs from earlier stages of the project.

**They are not current specifications.** Where an archived document conflicts
with the code, the code is correct. Where it conflicts with the top-level
`README.md` or the current docs (`../architecture.md`, `../methodology.md`,
`../results.md`, `../operations.md`), the current docs are correct.

They are kept because they show how the system's design and priorities
evolved, which is often more informative than the end state alone.

| File | What it is | Why it is archived |
|---|---|---|
| `ACCURACY_PLAN.md` | Model-accuracy improvement plan with a 2026-04-10 benchmark table | The benchmark predates XGBoost/Poisson/ensemble training; its "P2/P3" gaps (XGBoost & Poisson never trained, ensemble never used in recommendations) have since been implemented. See `../results.md` for current verified metrics. |
| `PRD.md` | Original product requirements document | Superseded by the implemented system. |
| `PRD_value_betting_research_system.md` | Earlier/parallel PRD draft | Superseded, retained for provenance. |
| `SYSTEM_REPORT.md` | Point-in-time system report | Snapshot; superseded by `../architecture.md`. |
| `T6_MERGE_READINESS.md` | Merge-readiness checklist for an in-flight branch | Describes a dirty working tree and PR split that no longer exist. |
| `differentiation_plan.md` | Roadmap of candidate future improvements | Forward-looking wish list, not implemented scope. |
| `SKILLS.md` | Agent/skill harness notes | Internal tooling notes, not part of the runtime system. |
| `claude_stop_hook_PLAN.md`, `claude_stop_hook_TASK.md` | Claude Code `Stop`-hook workflow design | Local developer tooling, unrelated to the AFL system. |
| `PREVIEW_REVIEW_GENERATOR_TODO.md`, `preview_review_generator_readiness.md` | Design + readiness study for an LLM (QLoRA) match preview/review generator | **Explicitly out of scope.** No LLM, fine-tuning, or narrative-generation code exists in this repository, and none is planned for this release. Retained as a record of exploration only. |
