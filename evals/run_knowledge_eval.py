from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

from travel_agent.tools.knowledge import (
    DEFAULT_CORPUS_PATH,
    DEFAULT_DENSE_MIN_SCORE,
    DEFAULT_EMBEDDING_MODEL,
    FastEmbedDenseEmbedder,
    LocalTravelKnowledgeTool,
)

ROOT = Path(__file__).parents[1]
DEFAULT_CASES = ROOT / "evals" / "knowledge_cases.jsonl"
DEFAULT_REJECTION_CASES = ROOT / "evals" / "knowledge_rejection_cases.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(
    cases_path: Path = DEFAULT_CASES,
    rejection_cases_path: Path = DEFAULT_REJECTION_CASES,
    *,
    top_k: int = 3,
    retrieval_method: str = "bm25",
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    dense_min_score: float = DEFAULT_DENSE_MIN_SCORE,
) -> dict[str, Any]:
    cases_path = cases_path.resolve()
    rejection_cases_path = rejection_cases_path.resolve()
    initialization_started = time.perf_counter()
    embedder = (
        FastEmbedDenseEmbedder(model_name=embedding_model)
        if retrieval_method in {"dense", "hybrid"}
        else None
    )
    tool = LocalTravelKnowledgeTool(
        retrieval_method=retrieval_method,
        embedder=embedder,
        dense_min_score=dense_min_score,
    )
    initialization_ms = (time.perf_counter() - initialization_started) * 1000
    cases = load_cases(cases_path)
    rows: list[dict[str, Any]] = []
    query_latencies_ms: list[float] = []
    reciprocal_rank_total = 0.0
    hit_at_1_total = 0
    hit_at_k_total = 0
    recall_at_k_total = 0.0
    for case in cases:
        query_started = time.perf_counter()
        result = tool.invoke({"query": case["query"], "top_k": top_k})
        query_latencies_ms.append((time.perf_counter() - query_started) * 1000)
        retrieved = [passage["id"] for passage in result["passages"]]
        relevant = set(case["relevant_ids"])
        first_relevant_rank = next(
            (rank for rank, doc_id in enumerate(retrieved, start=1) if doc_id in relevant),
            None,
        )
        hit_at_1 = bool(retrieved and retrieved[0] in relevant)
        retrieved_relevant = relevant.intersection(retrieved)
        hit_at_k = bool(retrieved_relevant)
        recall_at_k = len(retrieved_relevant) / len(relevant)
        hit_at_1_total += int(hit_at_1)
        hit_at_k_total += int(hit_at_k)
        recall_at_k_total += recall_at_k
        reciprocal_rank_total += 0.0 if first_relevant_rank is None else 1 / first_relevant_rank
        rows.append(
            {
                "id": case["id"],
                "retrieved_ids": retrieved,
                "relevant_ids": sorted(relevant),
                "hit_at_1": hit_at_1,
                "hit_at_k": hit_at_k,
                "recall_at_k": recall_at_k,
                "first_relevant_rank": first_relevant_rank,
            }
        )
    count = len(cases)
    rejection_rows: list[dict[str, Any]] = []
    for case in load_cases(rejection_cases_path):
        query_started = time.perf_counter()
        result = tool.invoke({"query": case["query"], "top_k": top_k})
        query_latencies_ms.append((time.perf_counter() - query_started) * 1000)
        retrieved = [passage["id"] for passage in result["passages"]]
        rejection_rows.append(
            {
                "id": case["id"],
                "retrieved_ids": retrieved,
                "correctly_rejected": not retrieved,
            }
        )
    rejection_count = len(rejection_rows)
    return {
        "retrieval_method": retrieval_method,
        "embedding_model": (
            embedding_model if retrieval_method in {"dense", "hybrid"} else None
        ),
        "embedding_backend": (
            "fastembed" if retrieval_method in {"dense", "hybrid"} else None
        ),
        "embedding_backend_version": (
            version("fastembed")
            if retrieval_method in {"dense", "hybrid"}
            else None
        ),
        "bm25_minimum_score": 1.0,
        "dense_minimum_score": (
            dense_min_score if retrieval_method in {"dense", "hybrid"} else None
        ),
        "initialization_ms": round(initialization_ms, 3),
        "query_latency_ms": {
            "p50": round(_percentile(query_latencies_ms, 0.50), 3),
            "p95": round(_percentile(query_latencies_ms, 0.95), 3),
        },
        "cases_path": str(cases_path.relative_to(ROOT)),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "rejection_cases_path": str(rejection_cases_path.relative_to(ROOT)),
        "rejection_cases_sha256": hashlib.sha256(
            rejection_cases_path.read_bytes()
        ).hexdigest(),
        "corpus_path": str(DEFAULT_CORPUS_PATH.relative_to(ROOT)),
        "corpus_sha256": hashlib.sha256(DEFAULT_CORPUS_PATH.read_bytes()).hexdigest(),
        "case_count": count,
        "top_k": top_k,
        "hit_at_1": hit_at_1_total / count,
        "hit_at_k": hit_at_k_total / count,
        "recall_at_k": recall_at_k_total / count,
        "mrr_at_k": reciprocal_rank_total / count,
        "rejection_case_count": rejection_count,
        "rejection_accuracy": sum(
            int(row["correctly_rejected"]) for row in rejection_rows
        )
        / rejection_count,
        "cases": rows,
        "rejection_cases": rejection_rows,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate travel-knowledge retrieval.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--rejection-cases", type=Path, default=DEFAULT_REJECTION_CASES
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--retrieval-method",
        choices=["bm25", "dense", "hybrid"],
        default="bm25",
    )
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--dense-min-score", type=float, default=DEFAULT_DENSE_MIN_SCORE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(
        args.cases,
        args.rejection_cases,
        top_k=args.top_k,
        retrieval_method=args.retrieval_method,
        embedding_model=args.embedding_model,
        dense_min_score=args.dense_min_score,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
