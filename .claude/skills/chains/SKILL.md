---
name: chains
description: Resume the mic -> preamp chain build-out (docs/CHAINS_PLAN.md). Use when the user says "/chains", "pick up the chains where we left off", or asks to continue building mics, preamps or chains for the Room view.
---

# Resume the chains build-out

`docs/CHAINS_PLAN.md` is the source of truth: its **Status** says where the last session
stopped, its **How a session runs** is the procedure. Follow it; this skill only starts it.

1. Read `docs/CHAINS_PLAN.md` (Status, How a session runs, What "done" means, and the
   section of the WP that Status names, with its Notes).
2. If `scripts/chain_status.py` exists, run `uv run python scripts/chain_status.py`.
3. Run `git status`. The work is on main and every session commits, so uncommitted
   changes are another session's: leave them alone and never stage them.
4. Tell the user in one or two lines: chains available, the WP and step this session
   takes, anything waiting on them. Then do the work.
   **The user is often away from the computer during these sessions: don't stop early.**
   Keep working, WP after WP, until context becomes an issue. A missing source file is not a
   reason to stop: note what the user must fetch (each URL alone in a code block) in the
   plan's Status and in your final message, skip to the next WP whose sources are open, and
   go back after the user supplies it. Don't ask questions you can decide (record the call
   under the WP's Decisions); stop only for a physics refit that moves existing renders
   (bring options) or true context exhaustion.
5. Before stopping (WP done, or context running low: stop at a clean step), do the plan's
   **End** steps: tests, Status with the exact next step, the WP's Notes, a Session log
   line, CLAUDE.md's chains paragraph, then commit on main only this session's changes
   (the plan's End, step 5).
