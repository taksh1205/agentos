"""Tenant-scoped persistence. SQLite demo and PostgreSQL production share a schema."""

import os
import time
import uuid

from sqlalchemy import create_engine, text


class Store:
    def __init__(self, url=None):
        self.engine = create_engine(url or os.getenv("DATABASE_URL", "sqlite:///agentos.db"))
        with self.engine.begin() as c:
            if self.engine.dialect.name == "postgresql":
                c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            for ddl in [
                "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, source TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, content TEXT NOT NULL, expires FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, state TEXT NOT NULL, created FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(workspace,run_id))",
                "CREATE TABLE IF NOT EXISTS sales (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, month TEXT NOT NULL, revenue FLOAT NOT NULL, costs FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, result TEXT NOT NULL, created FLOAT NOT NULL)",
            ]:
                c.execute(text(ddl))
            if self.engine.dialect.name == "postgresql":
                c.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS vec vector(384)"))
                c.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS documents_vec_hnsw ON documents USING hnsw (vec vector_cosine_ops)"
                    )
                )
                c.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS documents_lexical ON documents USING gin(to_tsvector('english',content))"
                    )
                )
            for ddl in [
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS budgets(workspace TEXT NOT NULL,run_id TEXT NOT NULL,tokens INTEGER NOT NULL,cost FLOAT NOT NULL,PRIMARY KEY(workspace,run_id))",
                "CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT NOT NULL,step TEXT NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,digest TEXT NOT NULL,status TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS effects(approval_id TEXT PRIMARY KEY,workspace TEXT NOT NULL,tool TEXT NOT NULL,result TEXT NOT NULL,created FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS inventory(workspace TEXT NOT NULL,sku TEXT NOT NULL,quantity INTEGER NOT NULL,threshold INTEGER NOT NULL,PRIMARY KEY(workspace,sku))",
                "CREATE TABLE IF NOT EXISTS invoices(workspace TEXT NOT NULL,number TEXT NOT NULL,amount FLOAT NOT NULL,paid INTEGER NOT NULL,due TEXT NOT NULL,PRIMARY KEY(workspace,number))",
                "CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,run_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL,created FLOAT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS rate_limits(id TEXT PRIMARY KEY,bucket INTEGER NOT NULL,count INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,input TEXT NOT NULL,status TEXT NOT NULL,lease FLOAT NOT NULL,attempts INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS rag_sources(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,source TEXT NOT NULL,content TEXT NOT NULL,digest TEXT NOT NULL,metadata TEXT NOT NULL,UNIQUE(workspace,source))",
                "CREATE TABLE IF NOT EXISTS rag_chunks(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,workspace TEXT NOT NULL,source TEXT NOT NULL,content TEXT NOT NULL,embedding TEXT NOT NULL,namespace TEXT NOT NULL,metadata TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS semantic_memory(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,content TEXT NOT NULL,embedding TEXT NOT NULL,namespace TEXT NOT NULL,provenance TEXT NOT NULL,expires FLOAT NOT NULL,UNIQUE(workspace,content))",
                "CREATE INDEX IF NOT EXISTS rag_chunks_tenant ON rag_chunks(workspace,namespace)",
                "CREATE INDEX IF NOT EXISTS memory_tenant ON semantic_memory(workspace,expires)",
            ]:
                c.execute(text(ddl))
            if self.engine.dialect.name == "postgresql":
                c.execute(text("ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS vec vector"))
                c.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS rag_chunks_lexical ON rag_chunks USING gin(to_tsvector('english',content))"
                    )
                )
            c.execute(
                text(
                    "INSERT INTO schema_migrations VALUES(2,:now) ON CONFLICT(version) DO NOTHING"
                ),
                {"now": time.time()},
            )

    def execute(self, sql, params=None):
        with self.engine.begin() as c:
            r = c.execute(text(sql), params or {})
            return [dict(x) for x in r.mappings()] if r.returns_rows else []

    def seed(self, workspace):
        for sku, q, t in [("WIDGET-A", 12, 20), ("SENSOR-B", 45, 15), ("CABLE-C", 5, 10)]:
            self.execute(
                "INSERT INTO inventory VALUES(:w,:s,:q,:t) ON CONFLICT(workspace,sku) DO NOTHING",
                dict(w=workspace, s=sku, q=q, t=t),
            )
        for number, amount, paid, due in [
            ("INV-001", 2500, 0, "2026-03-31"),
            ("INV-002", 1200, 1, "2026-02-28"),
            ("INV-003", 800, 0, "2026-04-15"),
        ]:
            self.execute(
                "INSERT INTO invoices VALUES(:w,:n,:a,:p,:d) ON CONFLICT(workspace,number) DO NOTHING",
                dict(w=workspace, n=number, a=amount, p=paid, d=due),
            )
        for month, rev, cost in [
            ("2026-01", 100000, 70000),
            ("2026-02", 120000, 78000),
            ("2026-03", 150000, 90000),
        ]:
            self.execute(
                "INSERT INTO sales(id,workspace,month,revenue,costs) VALUES(:id,:w,:m,:r,:c) ON CONFLICT(id) DO NOTHING",
                dict(id=workspace + month, w=workspace, m=month, r=rev, c=cost),
            )

    def analytics(self, workspace, metric="revenue"):
        if metric not in {"revenue", "profit", "margin", "costs"}:
            raise ValueError("Metric not approved")
        return self.analyze(workspace, {"metrics": [metric]})["metrics"][0]

    def analyze(self, workspace, intent):
        from .models import AnalyticsIntent

        intent = AnalyticsIntent.model_validate(intent) if isinstance(intent, dict) else intent
        if intent.dataset != "sales":
            raise ValueError("Use inventory_retrieval or invoice_analysis for these datasets")
        conditions = "workspace=:w"
        params = {"w": workspace}
        if intent.start:
            conditions += " AND month>=:start"
            params["start"] = intent.start
        if intent.end:
            conditions += " AND month<=:end"
            params["end"] = intent.end
        if intent.start and intent.end and intent.start > intent.end:
            raise ValueError("Reversed period")
        rows = self.execute(
            "SELECT month,revenue,costs FROM sales WHERE " + conditions + " ORDER BY month", params
        )
        results = []
        for metric in intent.metrics:
            values = [
                dict(
                    month=r["month"],
                    value=r["revenue"]
                    if metric == "revenue"
                    else r["costs"]
                    if metric == "costs"
                    else r["revenue"] - r["costs"]
                    if metric == "profit"
                    else ((r["revenue"] - r["costs"]) / r["revenue"] if r["revenue"] else None),
                )
                for r in rows
            ]
            total = (
                sum(r["value"] for r in values if r["value"] is not None)
                if metric != "margin"
                else (
                    sum(r["revenue"] - r["costs"] for r in rows) / sum(r["revenue"] for r in rows)
                    if sum(r["revenue"] for r in rows)
                    else None
                )
            )
            change = (
                values[-1]["value"] - values[0]["value"]
                if values and values[0]["value"] is not None and values[-1]["value"] is not None
                else None
            )
            changes = [
                dict(from_period=a["month"], to_period=b["month"], change=b["value"] - a["value"])
                for a, b in zip(values, values[1:])
                if a["value"] is not None and b["value"] is not None
            ]
            results.append(
                dict(
                    metric=metric,
                    rows=values,
                    total=total,
                    absolute_change=change,
                    growth=change / values[0]["value"]
                    if values and values[0]["value"] and change is not None
                    else None,
                    biggest_change=max(changes, key=lambda x: abs(x["change"]))
                    if changes
                    else None,
                )
            )
        comparison = None
        if intent.compare_previous and intent.start and intent.end:

            def ordinal(period):
                year, month = map(int, period.split("-"))
                if not 1 <= month <= 12:
                    raise ValueError("Invalid month")
                return year * 12 + month - 1

            def period(value):
                return f"{value // 12:04}-{value % 12 + 1:02}"

            start = ordinal(intent.start)
            width = ordinal(intent.end) - start + 1
            previous = self.analyze(
                workspace,
                AnalyticsIntent(
                    metrics=intent.metrics, start=period(start - width), end=period(start - 1)
                ),
            )
            comparison = [
                {
                    "metric": current["metric"],
                    "previous_total": old["total"],
                    "current_total": current["total"],
                    "absolute_change": current["total"] - old["total"]
                    if current["total"] is not None and old["total"] is not None
                    else None,
                }
                for current, old in zip(results, previous["metrics"])
            ]
        return {
            "dataset": "sales",
            "period": {"start": intent.start, "end": intent.end},
            "metrics": results,
            "raw_rows": rows,
            "comparison": comparison,
        }

    def trace(self, workspace, run_id, kind, payload):
        import json

        from .observability import emit

        emit(kind, workspace, run_id, payload)
        # Store metadata/IDs and structured outputs, never credentials or raw prompts.
        self.execute(
            "INSERT INTO traces VALUES(:id,:w,:r,:k,:p,:t)",
            dict(
                id=str(uuid.uuid4()),
                w=workspace,
                r=run_id,
                k=kind,
                p=json.dumps(payload, default=str),
                t=time.time(),
            ),
        )
