import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCard, ReportView, type Report } from "../app/report";

afterEach(cleanup);

const report: Report = {
  status: "completed",
  profile: "constrained",
  grounding: { requires_review: true },
  citations: [
    {
      id: "c1",
      source: "inventory-policy",
      text: "Keep at least twenty pallets.",
    },
  ],
  findings: [
    {
      step: "0",
      agent: "research",
      finding: {
        summary: "The policies conflict.",
        contradictions: ["twenty vs twelve"],
        claims: [
          { text: "Keep at least twenty pallets.", citations: ["c1"] },
          { text: "Owners should meet.", citations: ["c1"] },
        ],
      },
      grounding: {
        claims: [
          { index: 0, status: "supported", reason: "exact_extractive_support" },
          {
            index: 1,
            status: "needs_review",
            reason: "paraphrase_entailment_not_deterministically_proven",
          },
        ],
      },
    },
    {
      step: "1",
      agent: "data",
      interpretation: { summary: "Revenue rose." },
      computed: {
        dataset: "sales",
        metrics: [
          {
            metric: "revenue",
            rows: [
              { month: "2026-02", value: 120000 },
              { month: "2026-03", value: 150000 },
            ],
            absolute_change: 30000,
            growth: 0.25,
          },
        ],
      },
    },
    {
      step: "2",
      agent: "data",
      interpretation: { summary: "One invoice is overdue." },
      computed: {
        as_of: "2026-04-01",
        rows: [
          { number: "INV-001", amount: 2500, paid: 0, due: "2026-03-31" },
          { number: "INV-002", amount: 1200, paid: 1, due: "2026-02-28" },
        ],
        overdue_rows: [
          { number: "INV-001", amount: 2500, paid: 0, due: "2026-03-31" },
        ],
      },
    },
  ],
};

describe("rendered verification report", () => {
  it("separates machine-verified claims from claims that need human review", () => {
    render(<ReportView report={report} />);
    expect(
      screen.getByText("1/2 claims machine-verified · 1 need human review"),
    ).toBeInTheDocument();
    expect(screen.getByText("✓ verified")).toBeInTheDocument();
    expect(screen.getByText("◐ review")).toBeInTheDocument();
    expect(
      screen.getByText(/Conflicting evidence detected/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("inventory-policy").length).toBe(2);
  });

  it("renders computed metrics and cutoff-aware invoice status", () => {
    render(<ReportView report={report} />);
    expect(screen.getByText("+25.00%")).toBeInTheDocument();
    expect(screen.getByText("30,000.00")).toBeInTheDocument();
    expect(screen.getByText("Status as of 2026-04-01")).toBeInTheDocument();
    expect(screen.getByText("overdue")).toBeInTheDocument();
    expect(screen.getByText("paid")).toBeInTheDocument();
  });

  it("shows exact approval arguments and reports the decision", async () => {
    const decide = vi.fn();
    render(
      <ApprovalCard
        proposal={{
          tool: "create_report",
          arguments: { title: "Overdue invoices" },
          digest: "abcdef0123456789ff",
        }}
        onDecide={decide}
      />,
    );
    expect(screen.getByText("create_report")).toBeInTheDocument();
    expect(screen.getByText('"Overdue invoices"')).toBeInTheDocument();
    expect(screen.getByText("abcdef0123456789…")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Decline" }));
    expect(decide).toHaveBeenCalledWith(false);
  });
});
