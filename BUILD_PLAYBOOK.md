# BUILD_PLAYBOOK.md — Working Method for AI-Assisted Builds

**Companion to `CODING_GUARDRAILS.md`. Where guardrails define what you must not do, this defines how we work together — the rhythm, the division of labour, where you decide alone, where you flag, where you stop and ask. Read at session start, after CODING_GUARDRAILS.**

This file is shared across all of Jaimie's projects. Recommended changes propagate — a change to the playbook means updating every project copy. If you spot something here that's stale, conflicts with current practice, or misses a transferable lesson observed in this session, mention it at session end so it can be added before the next quarterly review.

---

## 1. The three-actor model

Three actors collaborate on every project. Each is good at different things; the wins come from clean handoffs.

**Human (Jaimie)** — strategic direction, scope decisions, architectural pivots, verification of visual output, final approval on commits, all external-facing decisions, tier assessment override, the only actor who sees the rendered UI and the lived consequence of a commit.

**Claude.ai (chat)** — scope shaping, sprint planning, cross-project pattern recognition, retrospective analysis, ideation, comparing approaches, drafting planning docs (CLAUDE.md, SIGNAL files). Reads multi-doc contexts. Does not see the actual repo state and should not pretend to. Calendar-time estimates from chat run consistently long; multiply chat's estimates by ~0.1 for actual CC working time and pace by human attention windows instead.

**Claude Code (you, in-repo)** — execution against an agreed plan, file edits, build/lint/tests, surfacing implementation trade-offs that only become visible in the code, sprint discipline (small steps, commits between, one-concept-per-turn). Sees the repo, doesn't see the renders, doesn't see the calendar.

The failures come from each actor straying out of its lane: Claude Code making architectural pivots without flagging, chat estimating durations or tactical implementation calls without seeing the code, human bypassing tier rules under time pressure.

---

## 2. Decision authority — when to act, when to flag, when to stop

This is the core of how speed and safety get balanced. The principle: **autonomy scales inversely with reversibility cost.** A file edit before commit is fully reversible — high autonomy. A commit is reversible with effort — autonomy with end-of-session flag. A deploy or migration is hard to reverse — human approval required. A data deletion is irreversible — typed confirmation plus tier rules.

**Hard stops — never proceed regardless of approval:**
- Destructive operations on prod or shared state without confirmed backup
- Tier 3 auth/payment/PHI code without recommended human security review
- Silent loosening of CSRF/CORS/RLS/auth/types as a fix-the-symptom shortcut
- Bulk-delete, schema migration, force push without typed confirmation in the same turn
- Anything matching CODING_GUARDRAILS § "Refuse dangerous patterns"

**Stop and ask before proceeding:**
- Architectural pivots from the agreed plan
- Scope expansion outside the current sprint
- Adding npm packages or other dependencies
- Round 3+ on the same bug — revert and re-plan instead of iterating
- Tier escalation signals (signals shifted from Tier 1 → 2)
- Any "should I take this shortcut" question
- Editing files outside the planned change set

**Decide and flag at session end (autonomous, but visible in handoff):**
- Implementation patterns within the agreed plan (which abstraction, which library shape)
- File splits when crossing the ~300-line threshold (with documented rationale per CODING_GUARDRAILS § 8)
- Tactical fixes within current sprint scope
- Verification artefact choice (match the test type — see § 4)
- Style choices within stated conventions
- Equivalence-by-reference verification skips (with cited reference path so the human can confirm the equivalence claim)

**Decide silently (no flag needed):**
- Variable naming, function ordering, import ordering
- Test scaffolding for the feature being built
- Comment density matched to file context
- Type narrowing, refactoring within a function

The end-of-session flag list is the load-bearing piece here. It's what lets CC move fast inside a sprint while keeping a clean review surface for the human afterwards. Don't skip it because the session was uneventful — even "no autonomous decisions to flag" is useful information.

---

## 3. Working rhythm

**Pre-sprint (chat).** Scope discussion in Claude.ai. Trade-off framing. SIGNAL-ROADMAP entry drafted and human-approved. Open questions resolved or explicitly deferred.

**Sprint open (CC).** Read CLAUDE.md. Identify project tier per CODING_GUARDRAILS and state assessment in first response (default one tier higher when uncertain). Read referenced SIGNAL files in order. Confirm sprint scope from SIGNAL-ROADMAP. State the plan before executing.

**Sprint execute (CC).** Small steps. Commit between coherent changes. One concept per turn. Read diffs aloud before applying. Surface flagged decisions as they arise, not just at the end. Run tests/lint before declaring complete.

**Sprint close (CC).** End-of-session checkpoint. Three things stated explicitly:
1. **Done** — what's complete and verified
2. **Flagged for review** — autonomous decisions made (the "decide and flag" set above)
3. **Open / revisit later** — anything noticed but deferred

Update SIGNAL files. Push only after human review of the diff.

**Cross-sprint (chat).** Retrospective. Capture transferable lessons in the project's SIGNAL files. Roll genuinely cross-project patterns up to BUILD_PLAYBOOK at the next quarterly review.

The pacing constraint is human verification cycles + check-in turnarounds + genuine architectural decisions, not CC throughput. A "5-day sprint" estimated in chat usually completes in 30–90 minutes of focused CC time, paced by human attention.

---

## 4. Instructing the human — context labels and plain steps

When the human is asked to take a technical action, the instruction is labelled by **execution context** and written in plain language. This is independent of the decision-authority hierarchy in § 2 — adding clarity to instructions does not mean adding more checkpoints, more approvals, or longer planning conversations. It just means the steps are easier to execute when the human picks the work back up after a gap, and easier to execute correctly the first time.

The human moves between projects, returns to workflows after breaks, and is still learning the technical scaffolding (Git Bash, Vercel dashboard, environment variables, deployment verification, redeploys after env changes). Without context labels, "run this command" is ambiguous — which terminal? which folder? local or remote? With labels, the human can act without re-reading the surrounding paragraph or guessing.

**Standard labels for execution contexts:**

- **`[TO CC]`** — paste this content as your next message to Claude Code
- **`[GIT BASH — NEW]`** — open a new Git Bash terminal, navigate to the project folder, run this
- **`[GIT BASH — EXISTING]`** — in an existing Git Bash terminal already open in the project folder
- **`[BROWSER — VERIFY]`** — open this URL in a browser, confirm what you see, report back with screenshots and notes
- **`[BROWSER — DASHBOARD]`** — multi-step UI work in a service dashboard (Vercel / Supabase / Resend / GitHub)
- **`[FILE — UPDATE]`** — save this content to the named file in the project (CC will pick it up on next read)
- **`[MULTI-STEP]`** — sequence across two or more contexts; numbered substeps follow, each with its own label

**Plain-language requirements:**

- **One context per instruction block.** Don't mix "run this in CC terminal AND check the dashboard" in one block — split into sequential labelled blocks.
- **State the working assumption.** "This assumes the dev server is running at localhost:3000." Don't make the human guess.
- **Include a verification command where useful.** "To confirm the terminal is in the right folder, run `pwd` — output should end in `/job-radar`." Same pattern for "to confirm localhost is up", "to confirm the deploy is live", "to confirm the file is up to date" — bake the check into the instruction.
- **Numbered substeps for any sequence longer than one command.** Plain numbers (1, 2, 3), not nested bullets.
- **No jargon without a one-line gloss on first use.** "Force push (rewrite the remote branch with your local version, overwriting whatever is there)" once; subsequent uses can drop the gloss.
- **Patronise rather than be cryptic.** "Open Git Bash by typing 'Git Bash' in the Start menu" is fine; "spawn a shell" is not. The human has explicitly preferred clarity over conciseness for execution steps.

**What this does NOT mean:**

- Not more decisions surfaced for approval — decision authority is still § 2.
- Not longer planning conversations or more back-and-forth — rhythm is still § 3.
- Not splitting one decision into many — just splitting one *instruction block* by execution context.

**Worked example.**

Cryptic:

> Push the changes and check the deploy.

Clear:

> **`[GIT BASH — EXISTING]`** in the project folder. To confirm you're in the right folder first, run `pwd` — output should end in the project name.
>
> ```
> git status        # confirm only expected files are staged
> git push
> ```
>
> If `git status` shows unexpected files, stop and paste the output back here before pushing.
>
> **`[BROWSER — VERIFY]`** open https://your-project.vercel.app/health
>
> Confirm the page loads and shows "ok". If it shows a build error or 404, copy the error text back here.

This applies symmetrically to chat (which gives most cross-tool workflow instructions — Vercel + Git Bash + Resend + browser) and to CC (which gives most terminal-and-verification instructions inside a session). Both actors use the same labels.

---

## 5. Verification patterns — match the artefact to the test type

Don't reflexively reuse the previous sprint's verification pattern when the test class has changed.

**UX behaviour testing** (modal interactions, sync flows, tab states, retry endpoints) → screenshots, not JSON blobs. The thing being verified is something the user sees and clicks.

**Architectural regression testing** (does X still produce Y? does Z not over-index? does the data shape hold?) → JSON content blobs, not screenshots. The thing being verified is structural.

**Visual changes** → live UI confirmation by the human in browser dev tools first; CC then applies the proven change. Don't freestyle on visual tweaks. The human's eye is the verification instrument; CC's role is mechanical application of a confirmed change.

**Shared-arithmetic equivalence** → if the code path is provably equivalent to an independently-verified path (same input, same transformation, same render), document the equivalence in the verification report, cite the verified reference path, and proceed. Live verification not required. Flag the skip at session end.

**Surface-boundary filtering for upstream-fixable data quality** → where data quality is upstream-fixable but not yet fixed, the surface boundary filters silently AND the upstream work has the affected items listed concretely. Either half alone is incomplete: filtering without listing leaves the cleanup abstract; listing without filtering leaks dirty data to users.

---

## 6. Sprint discipline — patterns that have worked

**One concept per file.** ~300 lines is the trigger to propose a split. Two classes of legitimate exception: single-state-machine cohesion and shared-lifecycle cohesion. Each exception earns its own documented rationale in the file header at the time it's needed. Future files don't inherit the justification.

**Commit numbering convention.** Where a stretch enforces "no sub-commits unless verification surfaces a real bug," reserve `X.5` for *structural-discipline commits* — pre-emptive splits or rationale-explainers that precede new work — and `X.y` (y ≥ 1) for sub-commit follow-ups. X.5 is exempt from the no-sub-commit rule because it's load-bearing setup, not retroactive cleanup. Commit message starts with the parent number and explicitly labels the discipline (`B1.5.5 — structural component split`).

**Combined sprints — viable when component sprints have low coupling.** Two sprints can ship in one chat session when one is pure wiring against pre-extracted strings and the other is new architecture. NOT viable when both require deep architectural decisions in parallel — the decisions collide. When combining, always ship two separate commits at close (preserves clean blame trail).

**Directory moves — use `find . -type f`, not enumerated extensions.** Enumerated extensions (`.tsx`, `.ts`) miss `.md` and config files. Always eyeball the diff for unexpected delete-mode entries before commit.

**Round 3+ on the same bug → stop, revert, re-plan from scratch.** Iteration compounds vulnerabilities (IEEE-ISTAS 2025 measured a 37.6% increase in critical vulnerabilities after 5 rounds of AI refinement). Don't iterate; revert and replan.

---

## 7. Efficiency patterns

**Read SKILL.md files first.** In environments where they exist, before writing any code or running any bash command, call `view` on relevant SKILL.md files. The skills encode environment-specific constraints not in training data — available libraries, rendering quirks, output paths.

**Prompt caching for repeated context.** Where a prompt is large but stable across many calls (a profile prompt scored against many jobs, a system prompt across an interactive session), use ephemeral `cache_control` blocks. First call pays the write premium; subsequent calls read at ~10% input cost.

**Cost monitoring with thresholds.** Where AI calls are per-unit-of-work (per-job, per-report, per-language), instrument cost-per-call into the database and surface trends. Set explicit thresholds: surface to human if average per-unit cost exceeds X, or if a single unit exceeds Y.

**Skip scoring for hard-filter rejects.** Where AI scoring is the expensive operation, apply deterministic hard filters first (wrong country, wrong grade, expired deadline) and only score the survivors.

**Stateless wherever possible.** No saved state means no migration debt, no GDPR exposure, no "did we wipe the dev DB" question. Add persistence only when the use case demands it. Sprint 1 stateless is a feature, not a limitation.

---

## 8. Housekeeping — session handovers, file hygiene, decision capture

Long chats hit memory limits and force-end without warning. SIGNAL files multiply until navigation suffers. Env vars drift between environments. Decisions get re-litigated because the rationale wasn't captured. The patterns below are routine maintenance that prevents these failure modes — not new approval gates, just things to do at predictable intervals.

**Chat handover before memory limits.**

Symptoms that handover is due: response slowdowns; multiple large file or image attachments stacking in context; the conversation has covered several distinct topics with substantial prose; sense that earlier content is being referenced less well. Rough threshold: 30+ messages of substantial content, or any chat carrying multiple large attachments plus full document drafts.

The handover sequence — chat triggers this proactively when sensing approach to capacity, or when the human says "let's hand over":

1. Pause the current line of work — finish the smallest coherent unit, then stop.
2. List any updates to project knowledge files (CLAUDE.md, SIGNAL-*) that the human should refresh from the local repo before starting the new chat. Project knowledge in chat drifts behind local files when SIGNAL files are updated mid-sprint.
3. Produce a self-contained handover message containing: current state of work; most recent decisions in this thread not yet written into SIGNAL files; open questions; what the next chat needs to read first; pointer to the refreshed project files.
4. The human starts a new chat, refreshes project files, pastes the handover message as the opening prompt.
5. Confirm the new chat has read the project files. Resume work.

The cost of an early handover is one extra message. The cost of being force-ended is losing context that wasn't captured anywhere.

**CC session handover.**

CC sessions also have context limits, manifesting differently — at some point CC starts losing the thread, contradicting earlier decisions in the same session, or re-reading files it should remember. CC's tools consume context faster than chat-only conversations: file viewing, terminal output, test runs all eat into the window. A long debugging session burns through faster than a planning conversation.

Protocol:

1. End-of-session checkpoint per § 3 (Done / Flagged / Open).
2. Update SIGNAL files. Push to GitHub.
3. End the current CC session.
4. Open a fresh CC session. It reads CLAUDE.md → CODING_GUARDRAILS.md → BUILD_PLAYBOOK.md → SIGNAL files in order.

SIGNAL files plus git history are the handover medium between CC sessions. Unlike chat, CC doesn't carry personal thread context that benefits from a written handover — the discipline is "always update SIGNAL before ending" so the next session has what it needs.

**SIGNAL file consolidation.**

When the number of active SIGNAL files passes a threshold, navigability suffers. Rough threshold: 8–10 active files, varies by project complexity. Signs of trouble: file names overlap; files infrequently referenced; the human can't remember what's in which file; CLAUDE.md "read these in order" lists become unwieldy.

Consolidation actions, taken end-of-sprint when triggered:

- Merge files with overlapping concerns
- Archive files for completed phases into `docs/archive/` with a date prefix (`docs/archive/2026-04-NETWORK-DESIGN-NOTES.md`)
- Move feature-specific briefs into `docs/design/` or `docs/features/` subfolders
- Maintain a manifest in CLAUDE.md or `docs/INDEX.md` mapping files to purposes
- Mark superseded files explicitly (`SUPERSEDED by X on [date], retained for historical context`)

The Constellate split (SIGNAL / -DESIGN / -SOURCES / -ROADMAP / NETWORK-DESIGN-NOTES / NGO-REFERENCE / DONOR-REQUIREMENTS) sits at the upper end of manageable. Further additions consolidate first.

**Decisions Log discipline.**

Scope, architectural, and naming decisions accumulate fast. Without a deliberate log, the rationale is lost and decisions get re-litigated.

Convention: a Decisions Log section in SIGNAL-ROADMAP.md, format `Q[N]. Question / Decision / Rationale / Consequences`. Each entry dated. New decisions append with the next Q number. Old decisions are not edited — they're superseded by a new entry that points back.

Worked example from Constellate: Q1–Q10 captured Sprint 0 scoping (donor focus, AI mapping approach, tier classification, statelessness). A new chat or CC session can understand "why did we decide X" in 30 seconds without re-deriving the answer.

**Environment / config hygiene.**

Recurring failure mode: env var updated in a deployment dashboard, deployment not redeployed, errors that look like an outage but are stale env. (TRACE pattern: "a wrong tier looks identical to a real outage in the logs.")

Discipline:

- `.env.example` stays in sync with `.env.local` — every key listed with a comment on its purpose and source
- Env changes in any deployed environment trigger an explicit redeploy — env updates don't apply to existing deployments
- README section listing each env var, which environments it lives in, how to rotate it
- Quarterly check: every env var has a documented purpose and current source

**Documentation rot check.**

SIGNAL files drift from code. Small drift is acceptable (a file count off by one); large drift is corrosive (architecture documented in SIGNAL-ARCHITECTURE no longer matches how code works). End-of-sprint question, asked in chat retrospective: "Are there patterns in the work this sprint that contradict what's in the SIGNAL files?" If yes, update before next sprint opens, not later.

**Stale-feature pruning.**

Features built in early sprints sometimes don't earn their keep — placeholder UI from Sprint 1 still rendered in Sprint 5; an experimental endpoint nobody calls; a config option nobody uses. End-of-roadmap question: "is anything still here that no longer serves the use case?" Distinct from documentation rot — that's about docs vs code mismatch; this is about code that shouldn't be there at all. Action: list candidate-for-removal items, get human approval, ship a removal commit.

**Periodic dependency audit.**

Quarterly, or before any tier escalation: run `npm outdated` and `npm audit` (or the equivalent for the project's package manager). Flag major version gaps, fix high/critical security advisories, check weekly download counts on packages not updated in 12+ months to confirm they're still maintained. CODING_GUARDRAILS § 10 covers initial install; this catches packages that have rotted since. Document any package pinned against current best practice (compatibility constraints, etc.) with a comment in `package.json` or a `DEPENDENCIES.md`.

**Vendor / integration health check.**

Quarterly review of upstream APIs and platforms — Vercel plan limits, IATI Datastore quota tier, Anthropic SDK version, custodian or external API access tier, database vendor changes, breaking-change announcements. For each external dependency: confirm current API version is supported, current plan/tier still meets project needs, recent announcements reviewed. The TRACE pattern is instructive — a wrong subscription tier on the IATI Datastore looked identical to a real outage in the logs, diagnosable only because the team checked tier first. Same shape applies to any external service the project depends on.

**Tier reassessment trigger.**

CODING_GUARDRAILS § 1 says re-assess tier when signals shift, but in practice nobody's actively looking. Explicit end-of-sprint check: "have any tier signals shifted this sprint?"

Signals to scan:
- New data sources — any sensitive data added?
- New users — more than just the human + close friends?
- Public deployment — any URL going public the human doesn't personally control?
- Money or auth flows added
- External integrations with their own tier implications (Stripe → Tier 3 immediately; banking APIs → Tier 3; Auth0 with real users → Tier 2 minimum)

If a signal has shifted, re-state the tier in the next session and apply the higher rules.

**Branch / tag hygiene.**

For single-developer projects on `main`, branching is rarely needed — a clean linear history with sprint-tagged commits is more useful than a complex branch structure.

Tagging convention: tag the commit at every sprint end (`sprint-1-demo`, `sprint-3-stable`) and at any deployable milestone. Tags are cheap and make rollback or "what state was this on date X" queries trivial.

Branch when: experimental work that might not land (feature spike); structural rewrites that span multiple sprints; anything where the human wants working `main` preserved while exploring. In all cases, merge back fast — long-lived branches in solo projects accumulate conflicts.

**Cross-project consistency check.**

When BUILD_PLAYBOOK or CODING_GUARDRAILS is updated, all project copies need refreshing or projects start applying different versions of the rules.

Discipline:
- A master copy of each shared doc lives in a central location (e.g. `~/Projects/_playbook/`)
- Project copies are refreshed from master at the quarterly review or on demand
- Each project's CLAUDE.md states the version date of the playbook and guardrails copies in its root, so drift is visible (`Playbook: v2026-05-08 / Guardrails: v2026-05-08`)
- After any update to a master copy, the chat that produced the update lists the projects that need propagation, and the human propagates at next opportunity
- Natural cadence: quarterly review (early August, November, February, May)

---

## 9. Cross-project lessons ledger

Patterns initially captured in a project's SIGNAL files. If applicable to 2+ projects, promoted here at the quarterly review. Pruned if superseded.

*Last reviewed: 2026-05-08. Next review: early August 2026 (aligned with CODING_GUARDRAILS quarterly review).*

- **Three-actor model.** Human strategy + chat planning + CC execution. Pacing constraint is human attention windows, not CC throughput.
- **Reversibility-cost autonomy ladder.** Autonomy scales inversely with reversibility cost.
- **Sprint timing.** Chat estimates run calendar-conservative; multiply by ~0.1 for actual CC working time.
- **Verification artefact match.** UX → screenshots. Architecture → JSONs. Visual → live UI by human.
- **Skill files first.** Read SKILL.md before writing any code in environments where they exist.
- **End-of-session flag list.** Decide-and-flag autonomous decisions surface in a labelled list at sprint close, alongside Done and Open/Revisit.
- **Execution context labels.** Technical instructions to the human are labelled by execution context (`[GIT BASH — EXISTING]`, `[BROWSER — VERIFY]`, `[TO CC]`, etc.) so workflows are easier to resume after a break. Plain-language steps, verification commands baked in, one context per block. Adds clarity, not approval overhead.
- **Session handover before memory limits.** Chat: refresh project files + write self-contained handover message before being force-ended. CC: end-of-session checkpoint + SIGNAL update + git push is the handover. Trigger proactively at first symptoms, not at the cliff.
- **SIGNAL file consolidation triggered by count and overlap.** Threshold ~8–10 active files. Archive completed-phase files with date prefix; subfolder for feature briefs; manifest in CLAUDE.md or `docs/INDEX.md`.
- **Decisions Log convention.** `Q[N]. Question / Decision / Rationale / Consequences` in SIGNAL-ROADMAP.md. Append, don't edit. Supersede with a back-pointer. (Origin: Constellate Sprint 0.)
- **Quarterly external rot checks.** Dependency audit (npm outdated/audit, package age) + vendor/integration health (API versions, plan tiers, breaking changes). Catches rot since initial install.
- **Tier reassessment as end-of-sprint trigger.** Explicit "have signals shifted?" scan, not relying on session-start re-assessment alone. Signals: new data, new users, public deployment, money/auth, external integrations.
- **Cross-project playbook propagation.** Master copy in central location; project copies note version date in CLAUDE.md (`Playbook: v[date]`). Quarterly review propagates updates.
- **Donor / institutional name protection.** In any project where the codebase or git history will eventually transfer to a third party, write no donor / partner / institutional name into new content. Use neutral language. (Origin: TRACE.)
- **X.5 commit convention.** Reserve X.5 for structural-discipline commits; X.y for sub-commits. (Origin: Constellate Sprint 5.)
- **Surface-boundary filtering paired with upstream listing.** When filtering dirty data at a surface, list the affected upstream items concretely; either half alone is incomplete. (Origin: Constellate B1.4 / Phase 3 Step 5.)

---

## 10. Maintenance

This file is reviewed quarterly alongside CODING_GUARDRAILS.md. Next review: early August 2026.

Recommended changes require updating all project copies — the file is shared, not per-project. If you propose a change at session end, name the projects that will need the propagation so the human can sequence the updates.

If a user request conflicts with this doc, surface the conflict before acting. The user can override on a project basis (recorded in the project's CLAUDE.md), but the override should be explicit and reasoned, not silent.

If at session end you encountered a working-method failure or a transferable lesson this doc doesn't cover, mention it specifically — vague observations aren't actionable. Quote the worked example. The cross-project lessons ledger above grows from these moments.
