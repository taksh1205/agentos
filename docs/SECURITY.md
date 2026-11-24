# Security controls and residual risks

| Boundary | Implemented control | Remaining risk |
|---|---|---|
| Identity | Separate demo and OIDC modes; RS256 signature, issuer, audience, expiry, and required claims | Identity-provider configuration/login UI and real JWKS deployment are operator responsibilities |
| Roles/scopes | Server-derived workspace; role/scope intersection; admin approvals; knowledge-write checks | No PostgreSQL RLS; application query scoping remains a critical boundary |
| Model tools | Capability allowlists, Pydantic arguments, no arbitrary SQL/shell/HTTP executor | Models can still propose bad but syntactically valid local actions; review exact arguments |
| Actions | Exact persisted digest approval, workspace match, transaction, unique receipt, cancellation check | Cancellation does not roll back a committed action; no external effects are implemented |
| Source injection | Source text confined to evidence; research/data nodes cannot mutate; separate approval authorization | Semantic prompt injection can influence answers; prompts alone are not a guarantee |
| File ingestion | Extension/signature, byte/page/text limits, extraction errors, format validation | PDF parsing runs in a thread; timeout does not kill the thread. Sandbox public hostile uploads before deployment |
| API abuse | Per-authenticated-subject minute buckets in the database | Rate limits are coarse and do not replace ingress/DoS controls |
| Secrets | Environment-only provider keys; no secret-returning tools; metadata-only telemetry | Task/state content may contain user-entered secrets; users must not submit credentials as tasks |
| Tenant data | Parameterized tenant predicates, bound MCP process identity, isolated checkpoint IDs | Trusted host code and database administrators can access records |
| CSV | Neutralize formula-leading textual cells | Consumers must still handle exports as untrusted input |

Shared mode rejects demo authentication. Do not set DEPLOYMENT=local when exposing the API publicly. API_KEYS is only a local registry, not enterprise authentication. Configure HTTPS ingress, a trusted OIDC issuer, and signed workspace/role claims before sharing. JWKS URLs are host configuration, not user task parameters.

The stdio MCP server is not an unauthenticated network endpoint. Its workspace/scopes come from the trusted parent process. Mutating tools additionally query the persisted exact approval; supplying an arbitrary approval string does not grant permission. Native access to the host database remains privileged.

V2 tests include malicious uploaded SQL instructions, forbidden tools routed through read agents, changed action arguments after approval, missing scopes, cross-workspace access, invalid signed claims, rate limiting, and canceled pending actions. This is representative coverage, not a comprehensive red-team evaluation of live models.

Memory expiration is separate from historical run/checkpoint retention. Deleting a document does not currently erase historical answers, memories, exports, or traces. Do not use sensitive production data without a comprehensive retention and deletion policy.


### V3 controls

The API requires workspace read scope and checks narrower privileges for writes. The MCP child receives allowlisted runtime and database settings. Model API keys and OIDC signing configuration are excluded. The server persists run status and its job in one transaction. The approval job captures its exact proposal ID and verifies the pending checkpoint before resuming. Shared deployments require an ID in the approval request. A stale job restores the pending approval for a fresh decision. A cancelled run cannot resume.

PDF parsing uses a disposable subprocess with a wall-clock timeout; Linux also bounds CPU time and address space. This worker shares the application's OS user and filesystem permissions. It is not a separately sandboxed document-processing service. Run private demonstrations with synthetic data. Checkpoints, proposals and workspace-visible traces may contain submitted text or tool arguments. Secure the database, configure retention and arrange identity provisioning before shared use.
