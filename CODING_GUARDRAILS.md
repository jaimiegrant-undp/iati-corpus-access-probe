# Coding Guardrails — Claude Code Project Rules

**You are Claude Code working in this project. These rules govern your behaviour. They override defaults but defer to user instruction unless safety is at stake — when a user request conflicts with a rule, surface the conflict before acting.**

---

## 1. Identify the project tier first

At the start of every new session in this project, determine the tier and state it in your first response. **When uncertain, default one tier higher.**

**Tier 0 — Throwaway / Learning**
*Signals:* tutorial code, learning exercises, no users, no deployment, no sensitive data, README mentions "experiment" / "playground" / "tutorial".
*Apply:* Universal rules only.

**Tier 1 — Personal Tool / Hobby**
*Signals:* personal automation, hobby webapp, used by you and maybe a few friends, no sensitive data flows, runs locally or on personal hosting.
*Apply:* Universal + Tier 1.

**Tier 2 — Real Users / Production**
*Signals:* public-facing app, users the owner doesn't personally know, real data flows, downtime has consequences, paid product, internal tool deployed across an organisation.
*Apply:* Universal + Tier 1 + Tier 2.

**Tier 3 — Sensitive / Regulated**
*Signals:* handles money (Stripe, Plaid, banking), health data, government IDs, biometrics, children's data, vulnerable populations, anything under GDPR / HIPAA / PCI-DSS, expected user base above ~5,000.
*Apply:* All rules + special precautions.

State the tier and your reasoning in your first response of every session. If signals shift mid-project, re-assess and announce.

---

## 2. Universal rules (all tiers)

1. **Git is required.** If `.git` is absent, run `git init` and propose an initial commit before any code change. Never run destructive commands (`rm -rf`, `git reset --hard`, branch deletion, force push) without explicit user confirmation in the same turn.
2. **No secrets in code, ever.** Inspect every file you create or edit for hardcoded API keys, tokens, passwords, connection strings. If found, refuse to commit and propose `.env` migration.
3. **`.gitignore` must include** at minimum: `.env`, `.env.local`, `node_modules/`, build outputs, IDE files, OS files (`.DS_Store`). Verify before any commit.
4. **Read diffs aloud before applying.** Summarise what you're changing and why; let the user review before committing.
5. **Small steps.** One coherent change per turn. If a request is large, propose a plan first, execute step-by-step, commit between steps.
6. **No silent loosening.** Never disable CSRF, CORS, RLS, security headers, type checks, or auth as a fix for a symptom. Surface why the legitimate path is failing.

---

## 3. Tier 1+ rules

7. **Project structure.** Keep `src/`, `tests/`, `docs/`, `scripts/`, `.env.example`, `README.md`, `CLAUDE.md` at root. Don't create new top-level directories without asking.
8. **One concept per file.** When a file passes ~300 lines, propose a split.
9. **Lockfiles committed.** `package-lock.json`, `pnpm-lock.yaml`, `Pipfile.lock`, `Cargo.lock`, `uv.lock` etc. tracked in git.
10. **Verify packages exist** before installing. Slopsquatting (typo-squat packages exploiting AI hallucinations) is an active attack class. Reject suggestions for packages with under ~100 weekly downloads, no GitHub link, or names suspiciously close to popular packages.
11. **Static analysis on.** ESLint / TypeScript / ruff / mypy / clippy as appropriate. Don't disable rules to silence errors without justifying.
12. **Pre-commit secret scan.** Recommend `gitleaks` or `trufflehog` if absent.

---

## 4. Tier 2+ rules

13. **Authentication is server-side.** Never put password validation, role checks, or admission decisions in client code. Use Supabase Auth, Auth0, Clerk, Cognito, or NextAuth.
14. **Authorisation defaults closed.** RLS enabled on every Supabase/Postgres table holding user data. Firebase rules explicit and deny-by-default. No `USING (true)`. No "allow public access" policies.
15. **Secrets only via environment variables in production.** Use a vault (Doppler, AWS Secrets Manager, GitHub Actions secrets, Vercel env). No keys checked into deployed bundles.
16. **API keys never in client-side code.** Proxy third-party APIs through backend functions (Supabase Edge, Cloudflare Workers, Express). If you find a key in a frontend file, treat it as compromised — flag rotation.
17. **Separate environments.** Dev / staging / prod with separate databases and credentials. Migrations run on staging first.
18. **Refuse dangerous patterns:**
    - `dangerouslySetInnerHTML` without DOMPurify or equivalent
    - `eval()` / `exec()` / `subprocess(... shell=True)` on user input
    - URL-fetching endpoints with no allowlist (especially block `169.254.169.254`)
    - IAM with `s3:*` or `Resource: "*"` — scope down
    - Hardcoded admin passwords or "magic" bypass user IDs
19. **Tests for new features.** At least smoke tests. Run them before declaring complete.
20. **Backups before destructive ops.** Confirm backup exists before any migration, mass delete, or schema change.
21. **Cost caps.** Recommend hard spending limits on AI APIs and cloud services.

---

## 5. Tier 3 rules

22. **Pause before any auth or sensitive-data code.** State that AI-generated auth, payment, or PHI code is high-risk and recommend human security review before launch.
23. **No autonomous destructive operations.** Even with confirmation, require human-in-the-loop with explicit typed confirmation for any DROP, DELETE, mass UPDATE, schema migration, or production deploy.
24. **Use vetted vendors.** Auth: Auth0 / Clerk / Cognito. Payments: Stripe Checkout (not custom). PHI: established healthcare frameworks. Don't roll custom crypto, custom auth, or custom payment handling.
25. **Compliance check.** Name relevant regulations (GDPR data residency, HIPAA BAAs, PCI-DSS scope). If unclear, recommend the user consult counsel before launch.
26. **No prod data in prompts or local dev.** Use synthetic data only. Add a `seeds/` directory.
27. **Logging without leaking.** Log enough to debug but never full tokens, passwords, or full PII. Recommend a structured logger with redaction.
28. **Pen test before launch.** Recommend a paid pen test, or at minimum the free Wiz / Snyk / OWASP ZAP scanners, before going live.

---

## 6. Working pattern

- **Plan first.** For any non-trivial task, propose a plan and wait for user approval before executing.
- **Iterate small.** One method, one component, one fix per turn.
- **If round 3+ on the same bug:** stop. Revert. Re-plan from scratch. Iteration compounds vulnerabilities — a 2025 IEEE-ISTAS study measured a 37.6% increase in critical vulnerabilities after 5 rounds of AI refinement.
- **For UI nudges:** ask the user to test the change in browser dev tools first; you apply the proven change. Don't freestyle on visual tweaks.
- **Refuse to bypass tier rules** even if asked. Surface the conflict; let the user explicitly downgrade tier if they choose.

---

## 7. Maintenance

This file is reviewed quarterly. The user has set a recurring reminder; next review is early August 2026. If you encounter a failure mode this doc doesn't cover, mention it at session end so it can be added.

*Sources include Wiz Research (Sept 2025), Veracode GenAI Security Report 2025, GitClear's 211M-line analysis, the Tenzai SSRF study (Dec 2025), Georgetown CSET XSS research, GitGuardian 2025 secrets report, IEEE-ISTAS arXiv 2506.11022, and incident postmortems from Tea App, Lovable, Replit, Moltbook, and Nx.*
