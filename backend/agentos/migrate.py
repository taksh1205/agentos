"""Idempotent schema bootstrap and explicit migration of V1 document chunks."""

import argparse
from collections import defaultdict

from .rag import Retrieval
from .store import Store


def migrate_legacy(store, rag):
    rows = store.execute(
        "SELECT workspace,source,content FROM documents ORDER BY workspace,source,id"
    )
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["workspace"], row["source"])].append(row["content"])
    count = 0
    for (workspace, source), chunks in grouped.items():
        if store.execute(
            "SELECT id FROM rag_sources WHERE workspace=:w AND source=:s",
            dict(w=workspace, s=source),
        ):
            continue
        rag.ingest(workspace, source, "\n\n".join(chunks), {"migrated_from": "v1_chunks"})
        count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-documents", action="store_true")
    args = parser.parse_args()
    store = Store()
    print(
        {
            "schema_version": 2,
            "legacy_documents_imported": migrate_legacy(store, Retrieval(store))
            if args.legacy_documents
            else 0,
        }
    )
