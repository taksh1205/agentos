# Security model

AgentOS is designed so that a model, a retrieved document or a tool result **cannot** cause an
unauthorized state change, even when the model follows a prompt injection. Defense comes from
structure (scopes, schemas, digests, transactions), not from prompts.

## Controls and residual risk

| Boundary | Control | Residual risk |
|---|---|---|
| Identity | Demo tokens only when `DEPLOYMENT=local`; shared mode requires RS256 OIDC (issuer, audience, expiry, subject, workspace, role claims) via public key or HTTPS JWKS | Identity provider and login UI are the operator's responsibility |
| Roles and scopes | Server-derived workspace; role ∩ token scopes; admin-only approvals and reindex; knowledge-write for uploads | No PostgreSQL row-level security; application query scoping is the tenant boundary |
| Model choice | Client model IDs must be on `ALLOWED_MODELS`; required for any shared deployment | Operator must keep the allowlist current |
| Planning | Capability ownership; only the action agent can hold a mutating tool; **write-intent gate** drops writes the request never asked for | A request that does ask for a write can still yield a wrong-but-valid proposal, which is why approval exists |
| Tools | 11 allowlisted MCP tools with Pydantic arguments; no SQL, shell or HTTP executor; SQL identifiers come from server templates or validated enums; outputs size- and schema-checked | Native database access by the host remains privileged |
| MCP identity | Workspace and scopes are injected by the parent process into the stdio server's environment; model arguments cannot set them; provider keys are not passed to the child | — |
| Writes | Proposal persisted before interrupt; approval bound to SHA-256 of canonical arguments; transaction re-checks workspace, digest, status and cancellation; unique effect receipt; replay returns the stored receipt | Cancellation cannot undo an already committed effect |
| Prompt injection | Retrieved text is evidence only; research and data nodes cannot mutate; the frozen evaluation includes an injected "export invoices and email them" instruction | Injection can still bias the *wording* of an answer |
| Uploads | Extension and signature checks, 5 MB, page and text limits; PDF parsing in a time-boxed subprocess with CPU and memory limits on Linux | The subprocess shares the app's OS user; sandbox hostile public uploads separately |
| Abuse | Per-subject per-minute rate limits stored in the database; token and dollar budgets per run | Not a substitute for ingress DoS protection |
| Secrets | Keys only from the environment; no tool returns configuration; telemetry exports metadata only | Users must not paste credentials into tasks: task text is stored |
| CSV exports | Formula-leading cells neutralized | Consumers should still treat exports as untrusted |

## Release scans (this release)

| Check | Result | Evidence |
|---|---|---|
| Secrets in git history (gitleaks 8.24.3, default rules) | No leaks | [`evidence/security/`](evidence/security/) |
| Python advisories (pip-audit on `requirements-lock.txt`, 86 packages) | 0 known vulnerabilities | [`evidence/security/pip-audit.json`](evidence/security/pip-audit.json) |
| npm advisories (`npm audit`) | 0 after pinning PostCSS 8.5.33 and Playwright 1.65 | [`evidence/security/npm-audit.json`](evidence/security/npm-audit.json) |
| Personal data | No emails, phone numbers or real records; all business data is synthetic | Manual review |

CI repeats the gitleaks, pip-audit and npm-audit checks on every push.

## Deployment checklist

1. Set `AUTH_MODE=oidc`, `DEPLOYMENT=shared`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`
   (`compose.oidc.yaml`). Demo tokens are rejected in shared mode.
2. Set `ALLOWED_MODELS`, `MAX_TOKENS`, and `MODEL_PRICES` with `MAX_COST_USD` if spending matters.
3. Terminate TLS at your ingress; Compose binds ports to `127.0.0.1` only.
4. Replace `POSTGRES_PASSWORD`; restrict database network access.
5. Configure retention for runs, checkpoints and traces. They can contain submitted text.

## Reporting

This is a portfolio project. Please open a GitHub issue for security questions; do not include
real credentials or personal data.
