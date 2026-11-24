import React from "react";

type Source = { id: string; source: string; text: string };
type Claim = {
  text: string;
  quote?: string | null;
  citations?: string[];
  kind?: string;
};
type ClaimCheck = { index: number; status: string; reason: string };
type Metric = {
  metric: string;
  rows: { month: string; value: number | null }[];
  total?: number | null;
  absolute_change?: number | null;
  growth?: number | null;
};
type Invoice = {
  number: string;
  amount: number;
  paid: number | boolean;
  due: string;
};
export type Finding = {
  step: string;
  agent: string;
  ok?: boolean;
  denied?: boolean;
  tool?: string;
  receipt?: string;
  effect?: {
    stored?: boolean;
    external_message_sent?: boolean;
    payload?: Record<string, unknown>;
  };
  finding?: {
    summary: string;
    citations?: string[];
    contradictions?: string[];
    insufficient?: boolean;
    claims?: Claim[];
  };
  interpretation?: { summary: string };
  grounding?: {
    claims?: ClaimCheck[];
    errors?: string[];
    fully_checked?: boolean;
    requires_review?: boolean;
  };
  sources?: Source[];
  computed?: {
    dataset?: string;
    metrics?: Metric[];
    rows?: Invoice[] | { sku: string; quantity: number; threshold: number }[];
    overdue_rows?: Invoice[];
    overdue_total?: number;
    as_of?: string;
  };
};
export type Report = {
  status?: string;
  mode?: string;
  profile?: string;
  grounding?: { requires_review: boolean; fully_checked?: boolean };
  clarification?: string | null;
  refusal?: string | null;
  review?: { supported: boolean | null; issues?: string[] };
  errors?: string[];
  findings: Finding[];
  citations: Source[];
};

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;

const STATUS: Record<string, [string, string]> = {
  supported: [
    "verified",
    "Machine-verified against sources or computed records",
  ],
  needs_review: ["review", "Plausible, but requires human semantic review"],
  unsupported: ["rejected", "Not supported by the cited evidence"],
  contradicted: ["rejected", "Contradicted by the computed records"],
};

export function Badge({
  tone,
  children,
}: {
  tone: string;
  children: React.ReactNode;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}

function Claims({
  finding,
  sources,
}: {
  finding: Finding;
  sources: Map<string, Source>;
}) {
  const claims = finding.finding?.claims ?? [];
  const checks = finding.grounding?.claims ?? [];
  if (!claims.length) return null;
  return (
    <ul className="claims">
      {claims.map((claim, i) => {
        const check = checks.find((c) => c.index === i);
        const [tone, label] =
          STATUS[check?.status ?? "needs_review"] ?? STATUS.needs_review;
        return (
          <li key={i}>
            <Badge tone={tone}>
              {tone === "verified"
                ? "✓ verified"
                : tone === "review"
                  ? "◐ review"
                  : "✗ rejected"}
            </Badge>
            <span title={label}>“{claim.text}”</span>
            {(claim.citations ?? []).map((id) => (
              <span className="cite" key={id} title={sources.get(id)?.text}>
                {sources.get(id)?.source ?? id.slice(0, 8)}
              </span>
            ))}
            {check && check.status !== "supported" && (
              <small>{check.reason.replaceAll("_", " ")}</small>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function MetricsTable({ metrics }: { metrics: Metric[] }) {
  return (
    <table className="compact">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Period</th>
          <th>Start</th>
          <th>End</th>
          <th>Change</th>
          <th>Growth</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((m) => {
          const first = m.rows[0];
          const last = m.rows[m.rows.length - 1];
          const ratio = m.metric === "margin";
          return (
            <tr key={m.metric}>
              <td>{m.metric}</td>
              <td>
                {first?.month} → {last?.month}
              </td>
              <td>{ratio ? pct(first?.value) : fmt(first?.value)}</td>
              <td>{ratio ? pct(last?.value) : fmt(last?.value)}</td>
              <td>{ratio ? pct(m.absolute_change) : fmt(m.absolute_change)}</td>
              <td>{pct(m.growth)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RecordsTable({
  computed,
}: {
  computed: NonNullable<Finding["computed"]>;
}) {
  const rows = (computed.rows ?? []) as Record<string, unknown>[];
  if (!rows.length) return null;
  const overdue = new Set((computed.overdue_rows ?? []).map((r) => r.number));
  const invoices = "number" in rows[0];
  return (
    <table className="compact">
      <thead>
        <tr>
          {invoices ? (
            <>
              <th>Invoice</th>
              <th>Amount</th>
              <th>Due</th>
              <th>Status{computed.as_of ? ` as of ${computed.as_of}` : ""}</th>
            </>
          ) : (
            <>
              <th>SKU</th>
              <th>Quantity</th>
              <th>Reorder threshold</th>
              <th>Status</th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) =>
          invoices ? (
            <tr key={String(r.number)}>
              <td>{String(r.number)}</td>
              <td>${fmt(Number(r.amount))}</td>
              <td>{String(r.due)}</td>
              <td>
                {r.paid ? (
                  <Badge tone="muted">paid</Badge>
                ) : overdue.has(String(r.number)) ? (
                  <Badge tone="rejected">overdue</Badge>
                ) : (
                  <Badge tone="review">open</Badge>
                )}
              </td>
            </tr>
          ) : (
            <tr key={String(r.sku)}>
              <td>{String(r.sku)}</td>
              <td>{String(r.quantity)}</td>
              <td>{String(r.threshold)}</td>
              <td>
                {Number(r.quantity) < Number(r.threshold) ? (
                  <Badge tone="rejected">below</Badge>
                ) : (
                  <Badge tone="verified">ok</Badge>
                )}
              </td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  );
}

export function ReportView({ report }: { report: Report }) {
  const sources = new Map(report.citations.map((c) => [c.id, c]));
  for (const f of report.findings)
    for (const s of f.sources ?? [])
      if (!sources.has(s.id)) sources.set(s.id, s);
  const checks = report.findings.flatMap((f) => f.grounding?.claims ?? []);
  const verified = checks.filter((c) => c.status === "supported").length;
  const review = checks.filter((c) => c.status === "needs_review").length;
  const tone =
    report.status === "completed"
      ? "verified"
      : report.status === "failed"
        ? "rejected"
        : "review";
  return (
    <div className="report">
      <div className="report-head">
        <Badge tone={tone}>{report.status}</Badge>
        {report.profile && <Badge tone="muted">{report.profile}</Badge>}
        {checks.length > 0 && (
          <span className="muted">
            {verified}/{checks.length} claims machine-verified
            {review ? ` · ${review} need human review` : ""}
          </span>
        )}
      </div>
      {report.refusal && <p className="callout">Refused: {report.refusal}</p>}
      {report.clarification && (
        <p className="callout">Clarification needed: {report.clarification}</p>
      )}
      {report.grounding?.requires_review && (
        <p className="note">
          Deterministic checks verify quotes, citation IDs, numbers and
          receipts. Interpretation beyond those checks is marked for human
          review.
        </p>
      )}
      {(report.errors ?? []).length > 0 && (
        <p className="callout">
          Verification issues: {report.errors!.join(", ").replaceAll("_", " ")}
        </p>
      )}
      {report.findings.map((f) => (
        <section className="finding" key={f.step}>
          <h4>
            <span className="agent-tag">{f.agent}</span> step {f.step}
            {f.tool && <code>{f.tool}</code>}
          </h4>
          {f.agent === "action" ? (
            f.denied ? (
              <p>Proposal declined. No effect was written.</p>
            ) : (
              <p>
                <Badge tone="verified">committed</Badge> receipt{" "}
                <code>{f.receipt?.slice(0, 12)}</code>
                {f.effect?.external_message_sent === false && (
                  <span className="muted"> · no external message sent</span>
                )}
              </p>
            )
          ) : (
            <p className="summary">
              {f.finding?.summary ?? f.interpretation?.summary}
            </p>
          )}
          {(f.finding?.contradictions ?? []).length > 0 && (
            <p className="callout">
              ⚠ Conflicting evidence detected. Resolution is left to the policy
              owners.
            </p>
          )}
          <Claims finding={f} sources={sources} />
          {f.computed?.metrics && <MetricsTable metrics={f.computed.metrics} />}
          {f.computed?.rows && <RecordsTable computed={f.computed} />}
        </section>
      ))}
    </div>
  );
}

export function ApprovalCard({
  proposal,
  onDecide,
}: {
  proposal?: {
    id?: string;
    tool?: string;
    arguments?: Record<string, unknown>;
    digest?: string;
  };
  onDecide: (approve: boolean) => void;
}) {
  return (
    <div className="approval">
      <b>Approval requested</b>
      <p>
        Review the exact proposed tool and arguments. Approval is bound to this
        digest; changed arguments require a new approval.
      </p>
      <dl>
        <dt>Tool</dt>
        <dd>
          <code>{proposal?.tool}</code>
        </dd>
        {Object.entries(proposal?.arguments ?? {}).map(([k, v]) => (
          <React.Fragment key={k}>
            <dt>{k}</dt>
            <dd>
              {typeof v === "string" && v.length > 80 ? (
                <pre>{v}</pre>
              ) : (
                <code>{JSON.stringify(v)}</code>
              )}
            </dd>
          </React.Fragment>
        ))}
        {proposal?.digest && (
          <>
            <dt>Digest</dt>
            <dd>
              <code>{proposal.digest.slice(0, 16)}…</code>
            </dd>
          </>
        )}
      </dl>
      <button className="primary" onClick={() => onDecide(true)}>
        Approve action
      </button>
      <button onClick={() => onDecide(false)}>Decline</button>
    </div>
  );
}
