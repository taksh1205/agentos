# Baseline audit and V2 change record

Input: exact supplied `AgentOS_Taksh_Pathak(1).zip`, SHA-256 `24f091a0d4119ea56bf4c627a698a23922c0fcfe06e6de74dd54f8bc5c699ee1`. Its bytes match the earlier AgentOS ZIP. The archive was extracted and modified in place; this is an upgrade of that repository. No Git history was created.

Baseline rerun: **19 passed, 1 skipped**. The skipped check needs PostgreSQL. Original source, architecture, tests, API, dashboard, dependencies, evaluation, and deployment configuration were inspected.

## Findings

1. Offline routing and analytics keyword matching were explicit rules, not inference. V2 preserves the regression mode while adding auto capability planning and typed live analytic intent.
2. Append-only graph reducers duplicate logical steps on replay. V2 merges by stable step identity and independently tests parallel execution.
3. Model usage omitted rewrite/review calls and failed attempts. V2 adds per-request records and atomic database reservations; cost limits fail closed without a supplied price table.
4. The action node can replay after interrupt. Calling a model again before the interrupt could change an already-reviewed action. V2 persists exact proposals before interruption and reuses them on resume.
5. Global action identity previously collided across tenants (fixed in V1). V2 extends approval/effect identities to workspace, run, and canonical tool arguments, including across replanning.
6. Replanning could repeat a completed mutation. Canonical approval identities and unique effect receipts make exact repeated proposals idempotent.
7. The old PostgreSQL path indexed 384-dimensional vectors but fetched all tenant rows. V2 adds versioned namespaces, dynamic dimension expression indexes, and candidate-only fetching.
8. Ingestion duplicated documents and could mix model vectors. V2 performs content-hash upserts, transactional replacement, explicit reindex, deletion, metadata filters, and model compatibility checks.
9. Legacy recall scores came from one trivial source and repetitive tasks. V2 retains those as historical baseline artifacts only; independent retrieval and labeled agent evaluation replace them as evidence.
10. Background tasks were process-local. V2 adds persisted jobs and restart recovery for the supported single-worker mode; horizontal multi-worker scheduling remains outside validated scope.

Read ENGINEERING_REPORT.md for executed checks and remaining limits. A code path being implemented is not evidence that a provider or infrastructure component was actually exercised.
