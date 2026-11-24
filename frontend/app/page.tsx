"use client";
import React, { useState, useEffect, useCallback } from "react";
import { ApprovalCard, ReportView, type Report } from "./report";
type Run = {
  id?: string;
  goal?: string;
  status?: string;
  events?: { agent: string; summary: string; at: number }[];
  report?: Report;
  approval?: {
    proposal?: {
      id?: string;
      tool?: string;
      arguments?: Record<string, unknown>;
      digest?: string;
    };
  }[];
  error?: string;
  plan?: {
    id: string;
    agent: string;
    dependencies: string[];
    tool?: string;
    completion_criteria?: string[];
  }[];
  usage?: {
    tokens: number | null;
    calls: number;
    estimated_cost_usd: number | null;
  };
};
type RetrievalRun = {
  configuration: string;
  status: string;
  metrics?: {
    recall_at_1: number;
    recall_at_5: number;
    mrr: number;
    ndcg_at_5: number;
  };
  mean_query_seconds?: number;
};
type Experiment = {
  configuration: { mode: string; memory: boolean };
  scenarios: number;
  completed: number;
  routing_accuracy: number;
  recall_at_5: number | null;
  mrr: number | null;
  task_success_rate?: number;
  tool_selection_accuracy?: number;
  p95_seconds?: number;
  p50_seconds: number;
};
type LiveEval = {
  file: string;
  configuration: {
    dataset: string;
    model: string;
    planner_profile: string;
    repeats: number;
  };
  summary: {
    runs: number;
    pass_at_1: number;
    groups: Record<string, { pass_at_1: number; runs: number }>;
    p50_seconds: number;
    p95_seconds: number;
    mean_tokens_per_run: number | null;
    unapproved_effects: number;
  } & Record<string, unknown>;
};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export default function Home() {
  const [token, setToken] = useState("local-demo-token"),
    [workflow, setWorkflow] = useState("auto"),
    [mode, setMode] = useState("demo"),
    [goal, setGoal] = useState(
      "Analyze enterprise revenue and explain the business context.",
    ),
    [run, setRun] = useState<Run>({}),
    [id, setId] = useState(""),
    [history, setHistory] = useState<Run[]>([]),
    [experiments, setExperiments] = useState<Experiment[]>([]),
    [tab, setTab] = useState("Workspace"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [model, setModel] = useState(""),
    [memory, setMemory] = useState(true),
    [traces, setTraces] = useState<
      { kind: string; payload: Record<string, unknown>; created: number }[]
    >([]),
    [pollTick, setPollTick] = useState(0),
    [retrieval, setRetrieval] = useState<RetrievalRun[]>([]),
    [live, setLive] = useState<LiveEval[]>([]);
  const request = useCallback(
    async (path: string, method = "GET", body?: unknown) => {
      const r = await fetch(API + path, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body instanceof FormData
            ? {}
            : { "Content-Type": "application/json" }),
        },
        body:
          body instanceof FormData
            ? body
            : body
              ? JSON.stringify(body)
              : undefined,
      });
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      return r.json();
    },
    [token],
  );
  const refresh = useCallback(async () => {
    try {
      setHistory(await request("/runs"));
      setExperiments(await request("/experiments"));
      const measured = await request("/evaluations/retrieval");
      if (Array.isArray(measured?.data?.results))
        setRetrieval(measured.data.results);
      const liveRuns = await request("/evaluations/live");
      if (Array.isArray(liveRuns?.results)) setLive(liveRuns.results);
    } catch (e) {
      setError(String(e));
    }
  }, [request]);
  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    if (!id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await request("/runs/" + id);
        if (stopped) return;
        setRun(r);
        setTraces(await request("/runs/" + id + "/traces"));
        if (r.status === "running" || r.status === "queued") {
          timer = setTimeout(poll, 1200);
        } else {
          refresh();
        }
      } catch (e) {
        if (!stopped) setError(String(e));
      }
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, request, refresh, pollTick]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const r = await request("/runs", "POST", {
        goal,
        workflow,
        mode,
        model: model || null,
        memory_enabled: memory,
      });
      setRun({ status: "running" });
      setId(r.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function approve(approve: boolean) {
    try {
      await request(`/runs/${id}/approval`, "POST", {
        approve,
        proposal_id: run.approval?.[0]?.proposal?.id,
      });
      setRun({ ...run, status: "running" });
      setPollTick((t) => t + 1);
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <main className="shell">
      <aside>
        <div className="brand">
          <span className="brand-icon">a</span> AgentOS
          <span className="version">03</span>
        </div>
        <div className="workspace">
          <span className="avatar">TP</span>
          <div>
            Taksh’s workspace<small>AI engineering lab</small>
          </div>
        </div>
        <p className="nav-label">PLATFORM</p>
        {["Workspace", "Execution history", "Experiments", "Knowledge"].map(
          (x, i) => (
            <button
              key={x}
              className={"nav " + (tab === x ? "active" : "")}
              onClick={() => setTab(x)}
            >
              <span>{["◈", "◷", "⌁", "▤"][i]}</span>
              {x}
            </button>
          ),
        )}
        <div className="aside-bottom">
          <span className="dot" /> Local-first execution
          <small>Python · LangGraph · MCP</small>
        </div>
      </aside>
      <section className="main">
        <header>
          <div className="breadcrumb">
            Platform <span>/</span> {tab}
          </div>
          <span className="pill">
            {mode === "demo" ? "Deterministic demo" : "Live model inference"}
          </span>
        </header>
        <div className="content">
          <div className="eyebrow">INTELLIGENCE, ORCHESTRATED</div>
          <h1>
            {tab === "Workspace" ? "From intent to verified output." : tab}
          </h1>
          <p className="subtitle">
            Five specialized agents. Grounded evidence. Every action
            accountable.
          </p>
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          {tab === "Workspace" && (
            <>
              <div className="stats">
                {[
                  ["05", "Specialized agents"],
                  [
                    String(history.length).padStart(2, "0"),
                    "Recorded executions",
                  ],
                  ["HITL", "Approval protected"],
                  [mode === "demo" ? "$0" : "API", "Inference mode"],
                ].map(([n, l]) => (
                  <div key={l}>
                    <strong>{n}</strong>
                    <small>{l}</small>
                  </div>
                ))}
              </div>
              <div className="grid">
                <div className="panel composer">
                  <div className="panel-title">
                    <span>01 / Launch an execution</span>
                    <span className="muted">STATEFUL WORKFLOW</span>
                  </div>
                  <label htmlFor="goal">
                    What should your agents accomplish?
                  </label>
                  <textarea
                    id="goal"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                  />
                  <div className="controls">
                    <select
                      aria-label="Workflow"
                      value={workflow}
                      onChange={(e) => setWorkflow(e.target.value)}
                    >
                      <option value="auto">Auto · capability planning</option>
                      <option value="business">Legacy demo: business</option>
                      <option value="research">Legacy demo: research</option>
                      <option value="operations">
                        Legacy demo: operations
                      </option>
                    </select>
                    <select
                      aria-label="Provider"
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                    >
                      <option>demo</option>
                      <option>openai</option>
                      <option>anthropic</option>
                    </select>
                  </div>
                  <input
                    aria-label="Model ID"
                    placeholder="Model ID (provider default if blank)"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                  />
                  <div className="launch">
                    <label>
                      <input
                        type="checkbox"
                        checked={memory}
                        onChange={(e) => setMemory(e.target.checked)}
                      />{" "}
                      Workspace memory
                    </label>
                    <button
                      className="primary"
                      disabled={busy || run.status === "running"}
                      onClick={start}
                    >
                      {run.status === "running"
                        ? "Executing…"
                        : "Run workflow ↗"}
                    </button>
                  </div>
                  <p className="note">
                    Offline mode uses explicit rules. Live mode uses
                    model-driven capability planning and typed tools. Configure
                    neural retrieval on the server.
                  </p>
                </div>
                <div className="panel">
                  <div className="panel-title">
                    02 / Agent network <span className="dot" />
                  </div>
                  <div className="network">
                    {[
                      "planner",
                      "research",
                      "data",
                      "action",
                      "verification",
                    ].map((a, i) => (
                      <div
                        key={a}
                        className={
                          "agent " +
                          (run.events?.some((e) => e.agent === a) ? "done" : "")
                        }
                      >
                        <span className="agent-no">0{i + 1}</span>
                        <div>
                          {a[0].toUpperCase() + a.slice(1)}
                          <small>
                            {
                              [
                                "Decompose & route",
                                "Retrieve & ground",
                                "Compute & analyze",
                                "Approve & execute",
                                "Validate & recover",
                              ][i]
                            }
                          </small>
                        </div>
                        <span className="agent-status">
                          {run.events?.some((e) => e.agent === a) ? "✓" : "○"}
                        </span>
                      </div>
                    ))}
                  </div>
                  {run.plan && (
                    <div className="plan-steps">
                      <h3>Execution dependencies</h3>
                      {run.plan.map((step) => (
                        <div className="plan-step" key={step.id}>
                          <b>
                            {step.id} / {step.agent}
                          </b>
                          <small>
                            {step.tool || "Agent-selected tool"} ·{" "}
                            {step.dependencies.length
                              ? "After " + step.dependencies.join(", ")
                              : "Independent branch"}
                          </small>
                          <small>{step.completion_criteria?.join(" · ")}</small>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="panel trace">
                <div className="panel-title">
                  03 / Execution timeline{" "}
                  <span className="pill">{run.status || "Ready"}</span>
                </div>
                {!run.events?.length && (
                  <p className="empty">
                    Submit a goal to follow agent handoffs, tool outputs, and
                    evidence.
                  </p>
                )}
                {run.events?.map((e, i) => (
                  <div className="event" key={i}>
                    <time>{new Date(e.at * 1000).toLocaleTimeString()}</time>
                    <b>{e.agent}</b>
                    <span>{e.summary}</span>
                  </div>
                ))}
                {run.status === "awaiting_approval" && (
                  <ApprovalCard
                    proposal={run.approval?.[0]?.proposal}
                    onDecide={approve}
                  />
                )}
                {run.usage && (
                  <div className="usage">
                    <span>Tokens: {run.usage.tokens ?? "unreported"}</span>
                    <span>Model attempts: {run.usage.calls}</span>
                    <span>
                      Estimated API cost:{" "}
                      {run.usage.estimated_cost_usd == null
                        ? "unknown"
                        : `$${run.usage.estimated_cost_usd.toFixed(5)}`}
                    </span>
                  </div>
                )}
                {run.status === "running" && (
                  <button
                    onClick={async () => {
                      try {
                        await request("/runs/" + id + "/cancel", "POST");
                        setPollTick((t) => t + 1);
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    Cancel execution
                  </button>
                )}
                {run.report && (
                  <>
                    <h3>Workflow result</h3>
                    <ReportView report={run.report} />
                    {run.report.citations.length > 0 && <h3>Cited sources</h3>}
                    {run.report.citations.map((c) => (
                      <details key={c.id}>
                        <summary>
                          {c.source} · {c.id.slice(0, 8)}
                        </summary>
                        <p>{c.text}</p>
                      </details>
                    ))}
                  </>
                )}
                {traces.length > 0 && (
                  <details>
                    <summary>Inspect {traces.length} execution traces</summary>
                    {traces.map((t, i) => (
                      <pre key={i}>
                        {JSON.stringify(
                          { kind: t.kind, ...t.payload },
                          null,
                          2,
                        )}
                      </pre>
                    ))}
                  </details>
                )}
                {run.error && <p className="error">{run.error}</p>}
              </div>
            </>
          )}
          {tab === "Execution history" && (
            <div className="panel">
              {history.length === 0 ? (
                <p>No executions yet.</p>
              ) : (
                history.map((r) => (
                  <button
                    className="history"
                    key={r.id}
                    onClick={() => {
                      setId(r.id!);
                      setRun(r);
                      setTab("Workspace");
                    }}
                  >
                    <span>{r.goal}</span>
                    <span className="pill">{r.status}</span>
                  </button>
                ))
              )}
            </div>
          )}
          {tab === "Experiments" && live.length > 0 && (
            <div className="panel">
              <div className="panel-title">
                Live-model evaluation · frozen task sets
                <span className="muted">fresh workspace per run</span>
              </div>
              <table>
                <thead>
                  <tr>
                    {[
                      "Dataset",
                      "Model",
                      "Planner profile",
                      "Runs",
                      "pass@1",
                      "By group",
                      "pass^k",
                      "p50 / p95",
                      "Tokens / run",
                      "Unapproved writes",
                    ].map((x) => (
                      <th key={x}>{x}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {live.map((r) => {
                    const k = r.configuration.repeats;
                    const all = r.summary[`pass_all_${k}`] as
                      number | undefined;
                    return (
                      <tr key={r.file}>
                        <td>
                          {r.configuration.dataset.replace(
                            "agentos-live-frozen-",
                            "",
                          )}
                          {r.file.includes("postfix") ? " (post-fix)" : ""}
                        </td>
                        <td>{r.configuration.model}</td>
                        <td>{r.configuration.planner_profile}</td>
                        <td>{r.summary.runs}</td>
                        <td>{(r.summary.pass_at_1 * 100).toFixed(1)}%</td>
                        <td>
                          {Object.entries(r.summary.groups)
                            .map(
                              ([g, v]) =>
                                `${g} ${(v.pass_at_1 * 100).toFixed(0)}%`,
                            )
                            .join(" · ")}
                        </td>
                        <td>
                          {all == null
                            ? "—"
                            : `${(all * 100).toFixed(1)}% (k=${k})`}
                        </td>
                        <td>
                          {r.summary.p50_seconds.toFixed(1)}s /{" "}
                          {r.summary.p95_seconds.toFixed(1)}s
                        </td>
                        <td>
                          {r.summary.mean_tokens_per_run == null
                            ? "—"
                            : Math.round(
                                r.summary.mean_tokens_per_run,
                              ).toLocaleString()}
                        </td>
                        <td>{r.summary.unapproved_effects}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="note">
                Measured local runs bundled with the repository. A run passes
                only when every programmatic check passes: tool use, citations,
                computed values, approval outcome, committed effects and
                idempotent replay.
              </p>
            </div>
          )}
          {tab === "Experiments" && (
            <div className="panel">
              <div className="panel-title">
                Observed evaluation runs
                <button onClick={refresh}>Refresh</button>
              </div>
              {experiments.length === 0 ? (
                <p className="empty">
                  No benchmark results yet. Run python -m agentos.evaluate in
                  the backend to populate this view.
                </p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      {[
                        "Mode",
                        "Memory",
                        "Completed",
                        "Routing",
                        "Task success",
                        "Tools",
                        "Median / p95 latency",
                      ].map((x) => (
                        <th key={x}>{x}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {experiments.map((e, i) => (
                      <tr key={i}>
                        <td>{e.configuration.mode}</td>
                        <td>{String(e.configuration.memory)}</td>
                        <td>
                          {e.completed}/{e.scenarios}
                        </td>
                        <td>{e.routing_accuracy.toFixed(3)}</td>
                        <td>
                          {e.task_success_rate?.toFixed(3) ?? "unlabeled"}
                        </td>
                        <td>
                          {e.tool_selection_accuracy?.toFixed(3) ?? "unlabeled"}
                        </td>
                        <td>
                          {e.p50_seconds.toFixed(3)}s /{" "}
                          {e.p95_seconds?.toFixed(3) ?? "?"}s
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="note">
                Citation ID checks measure provenance, not semantic
                faithfulness. No paid-model scores are pre-populated.
              </p>
              {retrieval.length > 0 && (
                <>
                  <h3>Measured neural retrieval comparison</h3>
                  <p className="note">
                    Bundled measured local run · 46 synthetic documents, 14
                    held-out labeled queries per configuration. This is a
                    recorded artifact, not a new benchmark execution.
                  </p>
                  <table>
                    <thead>
                      <tr>
                        {[
                          "Configuration",
                          "Recall@1",
                          "Recall@5",
                          "MRR",
                          "nDCG@5",
                          "Mean query",
                        ].map((t) => (
                          <th key={t}>{t}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {retrieval.map((r) => (
                        <tr key={r.configuration}>
                          <td>{r.configuration}</td>
                          <td>
                            {r.metrics?.recall_at_1.toFixed(3) ?? "not run"}
                          </td>
                          <td>
                            {r.metrics?.recall_at_5.toFixed(3) ?? "not run"}
                          </td>
                          <td>{r.metrics?.mrr.toFixed(3) ?? "not run"}</td>
                          <td>
                            {r.metrics?.ndcg_at_5.toFixed(3) ?? "not run"}
                          </td>
                          <td>{r.mean_query_seconds?.toFixed(3) ?? "?"}s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
          {tab === "Knowledge" && (
            <div className="panel">
              <h3>Index your evidence</h3>
              <p>
                Upload UTF-8 text or PDF, up to 5 MB. Documents are isolated to
                your authenticated workspace.
              </p>
              <input
                type="file"
                accept=".txt,.md,.pdf"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const data = new FormData();
                  data.append("file", f);
                  try {
                    const out = await request(
                      "/documents/upload",
                      "POST",
                      data,
                    );
                    setError("");
                    alert(`Indexed ${out.ids.length} chunks`);
                  } catch (err) {
                    setError(String(err));
                  }
                }}
              />
              <hr />
              <h3>Connection</h3>
              <label>
                API bearer token
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </label>
              <button
                className="primary"
                onClick={async () => {
                  try {
                    await request("/demo/seed", "POST");
                    setError("");
                    alert("Synthetic demo dataset ready");
                  } catch (e) {
                    setError(String(e));
                  }
                }}
              >
                Load synthetic demo dataset
              </button>
            </div>
          )}
          <footer>
            AGENTOS / ENGINEERED BY TAKSH PATHAK
            <span>Evidence before action.</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
