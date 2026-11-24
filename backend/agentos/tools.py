"""Allowlisted tools. All mutations require an exact server-persisted approval."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import date
from typing import Literal

from pydantic import Field
from sqlalchemy import text

from .models import AnalyticsIntent, StrictModel


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)
    source: str | None = None


class MetricArgs(StrictModel):
    metric: Literal["revenue", "costs", "profit", "margin"] = "revenue"
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class EmptyArgs(StrictModel):
    """No user-controlled query strings or workspace IDs."""


class InvoiceArgs(StrictModel):
    as_of: date | None = None


class ReportArgs(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=20000)


class CSVArgs(StrictModel):
    dataset: Literal["sales", "inventory", "invoices"] = "sales"


class FollowupArgs(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)


class EmailArgs(StrictModel):
    to: str = Field(min_length=3, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=10000)


class InventoryArgs(StrictModel):
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=0, le=1000000)


class NoticeArgs(StrictModel):
    message: str = Field(min_length=1, max_length=1000)


SCHEMAS = {
    "document_search": SearchArgs,
    "business_metrics": MetricArgs,
    "dataset_schema": EmptyArgs,
    "inventory_retrieval": EmptyArgs,
    "invoice_analysis": InvoiceArgs,
    "create_report": ReportArgs,
    "export_csv": CSVArgs,
    "create_followup": FollowupArgs,
    "draft_email": EmailArgs,
    "update_inventory": InventoryArgs,
    "create_notification": NoticeArgs,
}
MUTATIONS = {
    "create_report",
    "export_csv",
    "create_followup",
    "draft_email",
    "update_inventory",
    "create_notification",
}
CAPABILITIES = {
    name: {
        "schema": schema.model_json_schema(),
        "scope": "action:write" if name in MUTATIONS else "data:read",
        "approval_required": name in MUTATIONS,
    }
    for name, schema in SCHEMAS.items()
}


def fingerprint(tool, args):
    return hashlib.sha256(
        json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def propose(store, w, run_id, step, tool, args):
    parsed = SCHEMAS[tool].model_validate(args).model_dump()
    digest = fingerprint(tool, parsed)
    key = hashlib.sha256(f"{w}:{run_id}:{digest}".encode()).hexdigest()
    store.execute(
        "INSERT INTO approvals(id,workspace,run_id,step,tool,args,digest,status) VALUES(:id,:w,:r,:s,:t,:a,:d,'pending') ON CONFLICT(id) DO NOTHING",
        dict(id=key, w=w, r=run_id, s=step, t=tool, a=json.dumps(parsed), d=digest),
    )
    return {"id": key, "tool": tool, "arguments": parsed, "digest": digest, "status": "pending"}


def approve_proposal(store, w, key, approve):
    store.execute(
        "UPDATE approvals SET status=:s WHERE id=:id AND workspace=:w AND status='pending'",
        dict(id=key, w=w, s="approved" if approve else "denied"),
    )


class ToolService:
    def __init__(self, store, rag):
        self.store = store
        self.rag = rag

    def invoke(self, w, tool, args, *, scopes=None, approval_id=None):
        if tool not in SCHEMAS:
            raise PermissionError("Unknown tool")
        scopes = set((["data:read"] if scopes is None else scopes))
        required = "action:write" if tool in MUTATIONS else "data:read"
        if required not in scopes:
            raise PermissionError("Missing tool scope")
        args = SCHEMAS[tool].model_validate(args).model_dump()
        start = time.perf_counter()
        if tool in MUTATIONS:
            result = self._mutate(w, tool, args, approval_id)
        elif tool == "document_search":
            result = {"sources": self.rag.search(w, args["query"], args["k"], args["source"])}
        elif tool == "dataset_schema":
            result = {
                "datasets": {
                    "sales": {
                        "columns": ["month", "revenue", "costs"],
                        "metrics": ["revenue", "costs", "profit", "margin"],
                        "period_format": "YYYY-MM",
                        "periods": [
                            r["month"]
                            for r in self.store.execute(
                                "SELECT DISTINCT month FROM sales WHERE workspace=:w ORDER BY month",
                                {"w": w},
                            )
                        ],
                    },
                    "inventory": {"columns": ["sku", "quantity", "threshold"]},
                    "invoices": {"columns": ["number", "amount", "paid", "due"]},
                }
            }
        elif tool == "business_metrics":
            # Keep the compatibility path used by the original transient-failure tests.
            result = (
                self.store.analytics(w, args["metric"])
                if args["start"] is None and args["end"] is None
                else self.store.analyze(
                    w,
                    AnalyticsIntent(metrics=[args["metric"]], start=args["start"], end=args["end"]),
                )["metrics"][0]
            )
        elif tool == "inventory_retrieval":
            result = {
                "rows": self.store.execute(
                    "SELECT sku,quantity,threshold FROM inventory WHERE workspace=:w ORDER BY sku",
                    {"w": w},
                )
            }
        else:
            rows = self.store.execute(
                "SELECT number,amount,paid,due FROM invoices WHERE workspace=:w ORDER BY number",
                {"w": w},
            )
            result = {"rows": rows, "unpaid_total": sum(r["amount"] for r in rows if not r["paid"])}
            cutoff = args.get("as_of") or date.today()
            overdue = [r for r in rows if not r["paid"] and date.fromisoformat(r["due"]) < cutoff]
            result.update(
                as_of=cutoff.isoformat(),
                overdue_rows=overdue,
                overdue_total=sum(r["amount"] for r in overdue),
            )
        self.store.trace(
            w,
            None,
            "tool",
            {
                "tool": tool,
                "argument_keys": sorted(args),
                "seconds": time.perf_counter() - start,
                "output_fields": sorted(result),
            },
        )
        return result

    def _mutate(self, w, tool, args, approval_id):
        if not approval_id:
            raise PermissionError("Exact approval required")
        with self.store.engine.begin() as c:
            suffix = " FOR UPDATE" if self.store.engine.dialect.name == "postgresql" else ""
            row = (
                c.execute(
                    text("SELECT * FROM approvals WHERE id=:id AND workspace=:w" + suffix),
                    dict(id=approval_id, w=w),
                )
                .mappings()
                .first()
            )
            if (
                not row
                or row["status"] not in {"approved", "executed"}
                or row["tool"] != tool
                or row["digest"] != fingerprint(tool, args)
            ):
                raise PermissionError("Approval does not authorize these arguments")
            run_state = c.execute(
                text("SELECT state FROM runs WHERE id=:id AND workspace=:w"),
                dict(id=row["run_id"], w=w),
            ).scalar()
            if run_state and json.loads(run_state).get("status") == "cancelled":
                raise PermissionError("Run was cancelled before the mutation")
            previous = c.execute(
                text("SELECT result FROM effects WHERE approval_id=:id"), {"id": approval_id}
            ).scalar()
            if previous:
                return json.loads(previous)
            # Serialize SQLite writers before checking/mutating the approved resource.
            claim = c.execute(
                text("UPDATE approvals SET status='executing' WHERE id=:id AND status='approved'"),
                {"id": approval_id},
            )
            if claim.rowcount != 1:
                raise RuntimeError("Approval already in progress")
            payload = dict(args)
            if tool == "export_csv":
                columns = {
                    "sales": ["month", "revenue", "costs"],
                    "inventory": ["sku", "quantity", "threshold"],
                    "invoices": ["number", "amount", "paid", "due"],
                }[args["dataset"]]
                table = args["dataset"]  # Literal validated; never arbitrary SQL identifiers.
                rows = (
                    c.execute(
                        text(f"SELECT {','.join(columns)} FROM {table} WHERE workspace=:w"),
                        {"w": w},
                    )
                    .mappings()
                    .all()
                )
                stream = io.StringIO()
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                for item in rows:
                    # Neutralize spreadsheet formula injection for textual values.
                    writer.writerow(
                        {
                            k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v)
                            for k, v in item.items()
                        }
                    )
                payload = {"filename": args["dataset"] + ".csv", "content": stream.getvalue()}
            elif tool == "update_inventory":
                update = c.execute(
                    text("UPDATE inventory SET quantity=:q WHERE workspace=:w AND sku=:sku"),
                    dict(w=w, sku=args["sku"], q=args["quantity"]),
                )
                if update.rowcount != 1:
                    raise ValueError("Unknown inventory SKU")
                payload = {
                    **args,
                    "verified_quantity": c.execute(
                        text("SELECT quantity FROM inventory WHERE workspace=:w AND sku=:sku"),
                        dict(w=w, sku=args["sku"]),
                    ).scalar(),
                }
            result = {
                "receipt": approval_id,
                "tool": tool,
                "stored": True,
                "payload": payload,
                "external_message_sent": False,
            }
            c.execute(
                text(
                    "INSERT INTO effects(approval_id,workspace,tool,result,created) VALUES(:id,:w,:t,:r,:now)"
                ),
                dict(id=approval_id, w=w, t=tool, r=json.dumps(result), now=time.time()),
            )
            c.execute(
                text("UPDATE approvals SET status='executed' WHERE id=:id"), {"id": approval_id}
            )
            # Retain the V1 action audit table, one aggregate record per run.
            c.execute(
                text(
                    "INSERT INTO actions(id,workspace,run_id,payload) VALUES(:id,:w,:r,:p) ON CONFLICT(workspace,run_id) DO NOTHING"
                ),
                dict(
                    id=hashlib.sha256(f"{w}:{row['run_id']}".encode()).hexdigest(),
                    w=w,
                    r=row["run_id"],
                    p=json.dumps(result),
                ),
            )
        return result
