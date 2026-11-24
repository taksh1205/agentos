"""Database-backed atomic reservations shared by parallel graph branches."""

import os

from sqlalchemy import text

from .models import BudgetExceeded


class Ledger:
    def __init__(self, store, workspace, run_id):
        self.store = store
        self.workspace = workspace
        self.run_id = run_id
        self.maximum = int(os.getenv("MAX_TOKENS", "120000"))
        self.dollars = float(os.getenv("MAX_COST_USD", "0"))
        store.execute(
            "INSERT INTO budgets(workspace,run_id,tokens,cost) VALUES(:w,:r,0,0) ON CONFLICT(workspace,run_id) DO NOTHING",
            {"w": workspace, "r": run_id},
        )

    def reserve(self, tokens, prices):
        if self.dollars and not prices:
            raise BudgetExceeded("Dollar budget needs configured model prices")
        cost = tokens * max(prices.values()) / 1e6 if prices else 0
        with self.store.engine.begin() as c:
            result = c.execute(
                text(
                    "UPDATE budgets SET tokens=tokens+:n,cost=cost+:c WHERE workspace=:w AND run_id=:r AND tokens+:n<=:limit AND (:d=0 OR cost+:c<=:d)"
                ),
                dict(
                    w=self.workspace,
                    r=self.run_id,
                    n=tokens,
                    c=cost,
                    limit=self.maximum,
                    d=self.dollars,
                ),
            )
            if result.rowcount != 1:
                raise BudgetExceeded("Run budget exhausted before request")
        return (tokens, cost)

    def settle(self, reservation, tokens, cost):
        old_tokens, old_cost = reservation
        self.store.execute(
            "UPDATE budgets SET tokens=tokens+:delta,cost=cost+:dc WHERE workspace=:w AND run_id=:r",
            dict(
                w=self.workspace,
                r=self.run_id,
                delta=tokens - old_tokens,
                dc=(cost or 0) - old_cost,
            ),
        )

    def uncertain(self, reservation):
        # Keep ceiling reserved after timeouts because provider billing is unknown.
        return {
            "reserved_tokens": reservation[0],
            "reserved_cost_usd": reservation[1],
            "usage_uncertain": True,
        }
