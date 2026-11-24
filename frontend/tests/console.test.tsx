import React from "react";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "../app/page";
const requests: { url: string; body?: Record<string, unknown> }[] = [];
let approved = false;
beforeEach(() => {
  approved = false;
  requests.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      const body = options?.body ? JSON.parse(String(options.body)) : undefined;
      requests.push({ url, body });
      let value: unknown = [];
      if (url.endsWith("/runs") && options?.method === "POST")
        value = { id: "run-1" };
      else if (url.endsWith("/runs/run-1/approval")) {
        approved = true;
        value = { id: "run-1" };
      } else if (url.endsWith("/runs/run-1/traces"))
        value = [
          { kind: "tool_call", created: 1, payload: { tool: "export_csv" } },
        ];
      else if (url.endsWith("/runs/run-1"))
        value = {
          status: approved ? "completed" : "awaiting_approval",
          usage: { tokens: 0, calls: 0 },
          events: [
            {
              id: "planner",
              agent: "planner",
              summary: "Scheduled a model plan",
              at: 1,
            },
          ],
          plan: [
            {
              id: "export",
              agent: "action",
              tool: "export_csv",
              dependencies: [],
            },
          ],
          approval: [
            {
              proposal: { tool: "export_csv", arguments: { dataset: "sales" } },
            },
          ],
          ...(approved
            ? {
                report: { findings: [], citations: [] },
                usage: { tokens: 42, calls: 2, estimated_cost_usd: null },
              }
            : {}),
        };
      else if (url.endsWith("/experiments"))
        value = [
          {
            configuration: { mode: "demo", memory: false },
            scenarios: 24,
            completed: 24,
            routing_accuracy: 0.9,
            task_success_rate: 0.8,
            tool_selection_accuracy: 0.9,
            p50_seconds: 0.1,
            p95_seconds: 0.2,
            recall_at_5: null,
            mrr: null,
          },
        ];
      return { ok: true, json: async () => value };
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("AgentOS console interactions (mocked API, jsdom)", () => {
  it("submits auto-planned goals and shows exact approval arguments", async () => {
    const user = userEvent.setup();
    render(<Home />);
    expect(screen.getByLabelText("Workflow")).toHaveValue("auto");
    await user.selectOptions(screen.getByLabelText("Provider"), "openai");
    await user.click(screen.getByRole("button", { name: /Run workflow/ }));
    await screen.findByText("Approval requested");
    expect(requests.find((r) => r.body?.workflow)?.body).toMatchObject({
      workflow: "auto",
      mode: "openai",
    });
    expect(screen.getByText("Execution dependencies")).toBeInTheDocument();
    expect(screen.getAllByText(/export_csv/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Approve action" }));
    await screen.findByText("Workflow result");
    expect(screen.getByText("Tokens: 42")).toBeInTheDocument();
  });
  it("shows separately labeled agent experiment metrics without assuming RAG scores", async () => {
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByRole("button", { name: /Experiments/ }));
    await screen.findByRole("table");
    expect(screen.getByText("Task success")).toBeInTheDocument();
    expect(screen.getByText("0.800")).toBeInTheDocument();
  });
});
