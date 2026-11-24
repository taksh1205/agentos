"""Versioned neural/hybrid retrieval; feature hashing is an explicit offline baseline."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sqlalchemy import text


@lru_cache(maxsize=4)
def neural_model(name, revision):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        name, revision=revision or None, device="cpu", trust_remote_code=False
    )


@lru_cache(maxsize=2)
def cross_model(name, revision):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name, revision=revision or None, device="cpu", trust_remote_code=False)


def tokens(value):
    return re.findall(r"\b\w+\b", value.lower())


def chunk_text(content, size=180, overlap=30, strategy="paragraph"):
    if not 20 <= size <= 1000 or not 0 <= overlap < size:
        raise ValueError("Invalid chunk configuration")
    if strategy == "fixed":
        words = content.split()
        return [" ".join(words[i : i + size]) for i in range(0, len(words), size - overlap)]
    if strategy != "paragraph":
        raise ValueError("Unknown chunking strategy")
    chunks = []
    current = []
    for paragraph in re.split(r"\n\s*\n", content.strip()):
        words = paragraph.split()
        while words:
            room = size - len(current)
            current.extend(words[:room])
            words = words[room:]
            if len(current) >= size:
                chunks.append(" ".join(current))
                current = current[-overlap:] if overlap else []
        if len(current) >= size // 2:
            chunks.append(" ".join(current))
            current = current[-overlap:] if overlap else []
    if current and (not chunks or " ".join(current) != chunks[-1]):
        chunks.append(" ".join(current))
    return chunks


def bm25(query, documents):
    qt = tokens(query)
    docs = [tokens(d) for d in documents]
    if not docs:
        return []
    average = sum(map(len, docs)) / len(docs) or 1
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for doc in docs:
        count = Counter(doc)
        score = 0
        for term in qt:
            tf = count[term]
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * len(doc) / average)) if tf else 0
        scores.append(score)
    return scores


class Retrieval:
    def __init__(self, store, *, backend=None, model=None, revision=None, rerank=None):
        self.store = store
        self.backend = backend or os.getenv(
            "EMBEDDING_BACKEND", "neural" if os.getenv("EMBEDDING_MODEL") else "hashing"
        )
        if self.backend not in {"neural", "hashing"}:
            raise ValueError("Unknown embedding backend")
        self.model_name = model or os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self.revision = revision or os.getenv("EMBEDDING_REVISION", "")
        self.encoder = (
            neural_model(self.model_name, self.revision) if self.backend == "neural" else None
        )
        if self.encoder:
            config = getattr(
                getattr(self.encoder._first_module(), "auto_model", None), "config", None
            )
            resolved = getattr(config, "_commit_hash", None)
            if not resolved:
                from pathlib import Path

                from huggingface_hub import try_to_load_from_cache

                cached = try_to_load_from_cache(
                    self.model_name, "config.json", revision=self.revision or "main"
                )
                if isinstance(cached, str) and re.fullmatch(
                    r"[0-9a-f]{40}", Path(cached).parent.name
                ):
                    resolved = Path(cached).parent.name
            if resolved:
                self.revision = str(resolved)
            if not self.revision:
                raise ValueError(
                    "Neural model revision could not be resolved; set EMBEDDING_REVISION explicitly"
                )
        self.dimension = (
            int(
                self.encoder.get_embedding_dimension()
                if hasattr(self.encoder, "get_embedding_dimension")
                else self.encoder.get_sentence_embedding_dimension()
            )
            if self.encoder
            else int(os.getenv("HASH_DIMENSION", "384"))
        )
        if not 1 <= self.dimension <= 4096:
            raise ValueError("Unsupported embedding dimension")
        descriptor = f"{self.backend}:{self.model_name if self.encoder else 'feature-hash'}:{self.revision}:{self.dimension}:l2:v2"
        self.namespace = hashlib.sha256(descriptor.encode()).hexdigest()
        self.descriptor = descriptor
        self.hash = HashingVectorizer(n_features=self.dimension, alternate_sign=False, norm="l2")
        name = rerank if rerank is not None else os.getenv("RERANK_MODEL", "")
        self.reranker = cross_model(name, os.getenv("RERANK_REVISION", "")) if name else None
        if store.engine.dialect.name == "postgresql":
            # Unbounded vector storage supports model dimensions; a namespace-specific
            # expression index avoids mixing incompatible vector spaces.
            store.execute(
                f"CREATE INDEX IF NOT EXISTS rag_ann_{self.namespace[:12]} ON rag_chunks USING hnsw ((vec::vector({self.dimension})) vector_cosine_ops) WHERE namespace='{self.namespace}'"
            )

    def embed(self, texts):
        result = (
            self.encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            if self.encoder
            else self.hash.transform(texts).toarray()
        )
        matrix = np.asarray(result, dtype=float)
        if matrix.shape != (len(texts), self.dimension) or not np.isfinite(matrix).all():
            raise ValueError("Invalid embeddings")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0).tolist()

    def ingest(
        self, w, source, content, metadata=None, *, size=180, overlap=30, strategy="paragraph"
    ):
        if not content.strip() or len(content) > 500000:
            raise ValueError("Empty or oversized document")
        if not source or len(source) > 200:
            raise ValueError("Invalid source name")
        metadata = metadata or {}
        digest = hashlib.sha256(
            (
                content + json.dumps(metadata, sort_keys=True) + f"{size}:{overlap}:{strategy}"
            ).encode()
        ).hexdigest()
        doc_id = hashlib.sha256((w + ":" + source).encode()).hexdigest()
        existing = self.store.execute(
            "SELECT digest FROM rag_sources WHERE workspace=:w AND source=:s", dict(w=w, s=source)
        )
        indexed = self.store.execute(
            "SELECT id,namespace FROM rag_chunks WHERE workspace=:w AND document_id=:id",
            dict(w=w, id=doc_id),
        )
        if (
            existing
            and existing[0]["digest"] == digest
            and indexed
            and all(r["namespace"] == self.namespace for r in indexed)
        ):
            return [r["id"] for r in indexed]
        chunks = chunk_text(content, size, overlap, strategy)
        embeddings = self.embed(chunks)
        ids = []
        with self.store.engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO rag_sources VALUES(:id,:w,:s,:c,:d,:m) ON CONFLICT(workspace,source) DO UPDATE SET content=:c,digest=:d,metadata=:m"
                ),
                dict(id=doc_id, w=w, s=source, c=content, d=digest, m=json.dumps(metadata)),
            )
            c.execute(
                text("DELETE FROM rag_chunks WHERE workspace=:w AND document_id=:id"),
                dict(w=w, id=doc_id),
            )
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                ident = hashlib.sha256(
                    f"{doc_id}:{digest}:{self.namespace}:{i}".encode()
                ).hexdigest()
                ids.append(ident)
                params = dict(
                    id=ident,
                    doc=doc_id,
                    w=w,
                    s=source,
                    c=chunk,
                    e=json.dumps(emb),
                    ns=self.namespace,
                    m=json.dumps(metadata),
                )
                c.execute(
                    text(
                        "INSERT INTO rag_chunks(id,document_id,workspace,source,content,embedding,namespace,metadata) VALUES(:id,:doc,:w,:s,:c,:e,:ns,:m)"
                    ),
                    params,
                )
                if self.store.engine.dialect.name == "postgresql":
                    c.execute(
                        text("UPDATE rag_chunks SET vec=CAST(:e AS vector) WHERE id=:id"), params
                    )
        self.store.trace(
            w,
            None,
            "ingestion",
            {
                "document_id": doc_id,
                "chunks": len(ids),
                "embedding_namespace": self.namespace,
                "strategy": strategy,
            },
        )
        return ids

    def delete(self, w, source):
        with self.store.engine.begin() as c:
            c.execute(
                text("DELETE FROM rag_chunks WHERE workspace=:w AND source=:s"), dict(w=w, s=source)
            )
            c.execute(
                text("DELETE FROM rag_sources WHERE workspace=:w AND source=:s"),
                dict(w=w, s=source),
            )

    def reindex(self, w):
        rows = self.store.execute("SELECT * FROM rag_sources WHERE workspace=:w", {"w": w})
        for r in rows:
            self.ingest(w, r["source"], r["content"], json.loads(r["metadata"]))
        return {"documents": len(rows), "namespace": self.namespace, "dimension": self.dimension}

    def search(self, w, query, k=5, source=None, *, method=None, metadata=None):
        if not 1 <= k <= 20:
            raise ValueError("k must be 1..20")
        method = method or os.getenv("RETRIEVAL_METHOD", "hybrid")
        if method not in {"lexical", "dense", "hybrid", "weighted", "rerank"}:
            raise ValueError("Unknown retrieval method")
        start = time.perf_counter()
        query = query[:2000]
        params = dict(w=w, ns=self.namespace, s=source, q=query, k=max(30, k * 4))
        filt = "workspace=:w AND namespace=:ns" + (" AND source=:s" if source else "")
        foreign = self.store.execute(
            "SELECT DISTINCT namespace FROM rag_chunks WHERE workspace=:w AND namespace<>:ns",
            params,
        )
        if foreign:
            raise ValueError("Embedding model changed; reindex workspace before searching")
        q = np.array(self.embed([query])[0])
        if self.store.engine.dialect.name == "postgresql":
            if metadata:
                filt += " AND CAST(metadata AS jsonb) @> CAST(:meta AS jsonb)"
                params["meta"] = json.dumps(metadata)
            params["e"] = json.dumps(q.tolist())
            vector_rows = self.store.execute(
                f"SELECT id FROM rag_chunks WHERE {filt} ORDER BY vec::vector({self.dimension}) <=> CAST(:e AS vector({self.dimension})) LIMIT :k",
                params,
            )
            lexical_rows = self.store.execute(
                f"SELECT id FROM rag_chunks WHERE {filt} AND to_tsvector('english',content) @@ plainto_tsquery('english',:q) ORDER BY ts_rank_cd(to_tsvector('english',content),plainto_tsquery('english',:q)) DESC LIMIT :k",
                params,
            )
            ids = {r["id"] for r in vector_rows + lexical_rows}
            if not ids:
                return []
            # Candidate-only fetch; no full-tenant document scan in PostgreSQL.
            placeholders = ",".join(":i" + str(i) for i in range(len(ids)))
            params.update({"i" + str(i): v for i, v in enumerate(ids)})
            rows = self.store.execute(
                f"SELECT * FROM rag_chunks WHERE {filt} AND id IN ({placeholders})", params
            )
            lexical_order = {r["id"]: i for i, r in enumerate(lexical_rows)}
        else:
            rows = self.store.execute("SELECT * FROM rag_chunks WHERE " + filt, params)
            lexical_order = None
        if metadata:
            rows = [
                r
                for r in rows
                if all(
                    json.loads(r["metadata"]).get(key) == value for key, value in metadata.items()
                )
            ]
        if not rows:
            return []
        dense = [float(q @ np.array(json.loads(r["embedding"]))) for r in rows]
        lexical = bm25(query, [r["content"] for r in rows])
        vd = sorted(range(len(rows)), key=lambda i: (-dense[i], rows[i]["id"]))
        vl = sorted(
            range(len(rows)),
            key=lambda i: (
                lexical_order.get(rows[i]["id"], 10000)
                if lexical_order is not None
                else -lexical[i],
                rows[i]["id"],
            ),
        )
        rrf = {i: 1 / (61 + rank) for rank, i in enumerate(vd)}
        for rank, i in enumerate([i for i in vl if lexical[i] > 0]):
            if lexical_order is None or rows[i]["id"] in lexical_order:
                rrf[i] += (0.25 if method == "weighted" else 1.0) / (61 + rank)
        ranked = (
            vl
            if method == "lexical"
            else vd
            if method == "dense"
            else sorted(rrf, key=lambda i: (-rrf[i], rows[i]["id"]))
        )
        ranked = ranked[: max(20, k * 4)]
        rr_scores = {}
        if (method == "rerank" or method == "hybrid") and self.reranker:
            values = self.reranker.predict(
                [(query, rows[i]["content"]) for i in ranked], show_progress_bar=False
            )
            rr_scores = {i: float(v) for i, v in zip(ranked, values)}
            ranked.sort(key=lambda i: -rr_scores[i])
        elif method == "rerank":
            raise ValueError("Reranker not configured")
        result = [
            dict(
                id=rows[i]["id"],
                document_id=rows[i]["document_id"],
                source=rows[i]["source"],
                text=rows[i]["content"],
                score=rrf[i],
                dense_score=dense[i],
                lexical_score=lexical[i],
                rerank_score=rr_scores.get(i),
                metadata=json.loads(rows[i]["metadata"]),
            )
            for i in ranked[:k]
            if method != "lexical" or lexical[i] > 0
        ]
        self.store.trace(
            w,
            None,
            "retrieval",
            {
                "query_hash": hashlib.sha256(query.encode()).hexdigest(),
                "document_ids": [r["id"] for r in result],
                "method": method,
                "seconds": time.perf_counter() - start,
                "namespace": self.namespace,
                "rerank_scores": [r["rerank_score"] for r in result],
            },
        )
        return result

    def memory_records(self, w, query, k=3):
        self.store.execute(
            "DELETE FROM semantic_memory WHERE workspace=:w AND expires<:now",
            dict(w=w, now=time.time()),
        )
        rows = self.store.execute(
            "SELECT * FROM semantic_memory WHERE workspace=:w AND namespace=:ns",
            dict(w=w, ns=self.namespace),
        )
        if not rows:
            return []
        q = np.array(self.embed([query])[0])
        ranked = sorted(
            [(float(q @ np.array(json.loads(r["embedding"]))), r) for r in rows],
            key=lambda x: -x[0],
        )
        return [
            dict(
                content=r["content"],
                id=r["id"],
                score=score,
                provenance=json.loads(r["provenance"]),
            )
            for score, r in ranked[:k]
            if score > 0.05
        ]

    def memory(self, w, query):
        return [r["content"] for r in self.memory_records(w, query)]

    def remember(self, w, content, provenance=None):
        content = " ".join(content.split())[:3000]
        ident = hashlib.sha256((w + ":" + content).encode()).hexdigest()
        self.store.execute(
            "INSERT INTO semantic_memory VALUES(:id,:w,:c,:e,:ns,:p,:t) ON CONFLICT(workspace,content) DO UPDATE SET expires=:t,embedding=:e,namespace=:ns,provenance=:p",
            dict(
                id=ident,
                w=w,
                c=content,
                e=json.dumps(self.embed([content])[0]),
                ns=self.namespace,
                p=json.dumps(provenance or {}),
                t=time.time() + int(os.getenv("MEMORY_TTL_DAYS", "30")) * 86400,
            ),
        )
        return ident

    def forget(self, w, ident):
        self.store.execute(
            "DELETE FROM semantic_memory WHERE workspace=:w AND id=:id", dict(w=w, id=ident)
        )
