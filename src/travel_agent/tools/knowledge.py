from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "knowledge"
    / "japan_travel_safety.json"
)
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_DENSE_MIN_SCORE = 0.60
DEFAULT_FASTEMBED_CACHE = Path(__file__).resolve().parents[3] / ".cache" / "fastembed"
RRF_K = 60

LATIN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "i",
    "in",
    "is",
    "my",
    "should",
    "the",
    "there",
    "to",
    "what",
}
CJK_STOPWORDS = {"日本", "什么", "怎么", "如何", "可以", "旅行", "游客"}
CJK_STOP_PHRASES = ("在日本", "应该", "怎么办", "怎么", "如何", "旅行", "游客")
MIN_BM25_SCORE = 1.0


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    text: str
    source: str
    publisher: str
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class KnowledgeCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_date: str
    documents: list[KnowledgeDocument] = Field(min_length=1)


class KnowledgePassage(BaseModel):
    id: str
    title: str
    text: str
    source: str
    publisher: str
    topics: list[str]
    score: float
    bm25_score: float | None = None
    dense_score: float | None = None
    rank: int


class KnowledgeSearchResult(BaseModel):
    query: str
    provider: str = "local-official-snapshot"
    retrieval_method: str = "bm25"
    minimum_score: float = MIN_BM25_SCORE
    bm25_minimum_score: float = MIN_BM25_SCORE
    dense_minimum_score: float | None = None
    embedding_model: str | None = None
    snapshot_date: str
    passages: list[KnowledgePassage]


class DenseEmbedder(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedDenseEmbedder:
    """Lazy optional FastEmbed adapter; constructing it may download the model."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: Path = DEFAULT_FASTEMBED_CACHE,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                'Dense retrieval requires the optional dependency: pip install -e ".[rag]"'
            ) from exc

        self.model_name = model_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self._model.embed(list(texts))]


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    latin_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in LATIN_STOPWORDS
    ]
    for phrase in CJK_STOP_PHRASES:
        normalized = normalized.replace(phrase, " ")
    cjk_sequences = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk_tokens: list[str] = []
    for sequence in cjk_sequences:
        tokens = (
            [sequence]
            if len(sequence) == 1
            else [sequence[index : index + 2] for index in range(len(sequence) - 1)]
        )
        cjk_tokens.extend(token for token in tokens if token not in CJK_STOPWORDS)
    return latin_tokens + cjk_tokens


class LocalTravelKnowledgeTool:
    name = "search_travel_knowledge"
    description = "Retrieve cited travel-safety guidance from an official-source snapshot."

    def __init__(
        self,
        corpus_path: Path | None = None,
        *,
        retrieval_method: Literal["bm25", "dense", "hybrid"] = "bm25",
        embedder: DenseEmbedder | None = None,
        dense_min_score: float = DEFAULT_DENSE_MIN_SCORE,
    ) -> None:
        if retrieval_method not in {"bm25", "dense", "hybrid"}:
            raise ValueError("retrieval_method must be bm25, dense, or hybrid")
        if not -1.0 <= dense_min_score <= 1.0:
            raise ValueError("dense_min_score must be between -1 and 1")
        self.corpus_path = corpus_path or DEFAULT_CORPUS_PATH
        self.retrieval_method = retrieval_method
        self.dense_min_score = dense_min_score
        payload = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        self.corpus = KnowledgeCorpus.model_validate(payload)
        self._document_texts = [
            " ".join(
                [
                    document.title,
                    document.text,
                    *document.topics,
                    *document.keywords,
                ]
            )
            for document in self.corpus.documents
        ]
        self._document_tokens = [
            _tokenize(document_text) for document_text in self._document_texts
        ]
        self._embedder = embedder
        self._document_embeddings: list[list[float]] | None = None
        if self.retrieval_method in {"dense", "hybrid"}:
            self._embedder = self._embedder or FastEmbedDenseEmbedder()
            document_embeddings = self._embedder.embed(self._document_texts)
            if len(document_embeddings) != len(self._document_texts):
                raise RuntimeError("embedder returned an unexpected document count")
            if not document_embeddings or not document_embeddings[0]:
                raise RuntimeError("embedder returned empty document vectors")
            dimension = len(document_embeddings[0])
            if any(len(vector) != dimension for vector in document_embeddings):
                raise RuntimeError("embedder returned inconsistent vector dimensions")
            self._document_embeddings = [
                _normalize(vector) for vector in document_embeddings
            ]

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("knowledge query must be a non-empty string")
        top_k = arguments.get("top_k", 3)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 5:
            raise ValueError("top_k must be an integer between 1 and 5")

        query_tokens = _tokenize(query)
        bm25_scores = self._bm25_scores(query_tokens)
        dense_scores = self._dense_scores(query.strip())
        scores = self._ranking_scores(bm25_scores, dense_scores)
        candidates = [
            (index, score)
            for index, score in enumerate(scores)
            if self._passes_threshold(index, bm25_scores, dense_scores)
        ]
        ranked = sorted(
            candidates,
            key=lambda item: (-item[1], self.corpus.documents[item[0]].id),
        )[:top_k]
        passages = [
            KnowledgePassage(
                **self.corpus.documents[index].model_dump(exclude={"keywords"}),
                score=round(score, 6),
                bm25_score=round(bm25_scores[index], 6),
                dense_score=(
                    None if dense_scores is None else round(dense_scores[index], 6)
                ),
                rank=rank,
            )
            for rank, (index, score) in enumerate(ranked, start=1)
        ]
        return KnowledgeSearchResult(
            query=query.strip(),
            retrieval_method=self.retrieval_method,
            minimum_score=(
                self.dense_min_score
                if self.retrieval_method == "dense"
                else MIN_BM25_SCORE
            ),
            dense_minimum_score=(
                self.dense_min_score
                if self.retrieval_method in {"dense", "hybrid"}
                else None
            ),
            embedding_model=(
                self._embedder.model_name if self._embedder is not None else None
            ),
            snapshot_date=self.corpus.snapshot_date,
            passages=passages,
        ).model_dump()

    def _dense_scores(self, query: str) -> list[float] | None:
        if self._embedder is None or self._document_embeddings is None:
            return None
        query_embeddings = self._embedder.embed([query])
        if len(query_embeddings) != 1:
            raise RuntimeError("embedder returned an unexpected query count")
        if len(query_embeddings[0]) != len(self._document_embeddings[0]):
            raise RuntimeError("query and document vector dimensions do not match")
        query_vector = _normalize(query_embeddings[0])
        return [
            sum(left * right for left, right in zip(query_vector, document_vector))
            for document_vector in self._document_embeddings
        ]

    def _ranking_scores(
        self,
        bm25_scores: list[float],
        dense_scores: list[float] | None,
    ) -> list[float]:
        if self.retrieval_method == "bm25":
            return bm25_scores
        if dense_scores is None:
            raise RuntimeError("dense embeddings were not initialized")
        if self.retrieval_method == "dense":
            return dense_scores

        bm25_ranks = _rank_positions(bm25_scores, self.corpus.documents)
        dense_ranks = _rank_positions(dense_scores, self.corpus.documents)
        return [
            1 / (RRF_K + bm25_ranks[index])
            + 1 / (RRF_K + dense_ranks[index])
            for index in range(len(self.corpus.documents))
        ]

    def _passes_threshold(
        self,
        index: int,
        bm25_scores: list[float],
        dense_scores: list[float] | None,
    ) -> bool:
        bm25_passes = bm25_scores[index] >= MIN_BM25_SCORE
        dense_passes = (
            dense_scores is not None and dense_scores[index] >= self.dense_min_score
        )
        if self.retrieval_method == "bm25":
            return bm25_passes
        if self.retrieval_method == "dense":
            return dense_passes
        return bm25_passes or dense_passes

    def _bm25_scores(self, query_tokens: list[str]) -> list[float]:
        document_count = len(self._document_tokens)
        average_length = sum(map(len, self._document_tokens)) / document_count
        document_frequency = Counter(
            token
            for tokens in self._document_tokens
            for token in set(tokens)
        )
        query_frequency = Counter(query_tokens)
        scores: list[float] = []
        k1 = 1.5
        b = 0.75
        for tokens in self._document_tokens:
            frequencies = Counter(tokens)
            document_length = len(tokens)
            score = 0.0
            for token, query_weight in query_frequency.items():
                frequency = frequencies[token]
                if not frequency:
                    continue
                inverse_document_frequency = math.log(
                    1
                    + (document_count - document_frequency[token] + 0.5)
                    / (document_frequency[token] + 0.5)
                )
                denominator = frequency + k1 * (
                    1 - b + b * document_length / average_length
                )
                score += (
                    inverse_document_frequency
                    * frequency
                    * (k1 + 1)
                    / denominator
                    * min(query_weight, 2)
                )
            scores.append(score)
        return scores


def _normalize(vector: Sequence[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return [0.0 for _ in vector]
    return [value / magnitude for value in vector]


def _rank_positions(
    scores: Sequence[float], documents: Sequence[KnowledgeDocument]
) -> list[int]:
    ranked_indices = sorted(
        range(len(scores)), key=lambda index: (-scores[index], documents[index].id)
    )
    positions = [0] * len(scores)
    for rank, index in enumerate(ranked_indices, start=1):
        positions[index] = rank
    return positions


def build_knowledge_tool_from_env() -> LocalTravelKnowledgeTool:
    retrieval_method = os.getenv("KNOWLEDGE_RETRIEVAL", "bm25").strip().lower()
    if retrieval_method not in {"bm25", "dense", "hybrid"}:
        raise ValueError("KNOWLEDGE_RETRIEVAL must be bm25, dense, or hybrid")
    dense_min_score = float(
        os.getenv("KNOWLEDGE_DENSE_MIN_SCORE", str(DEFAULT_DENSE_MIN_SCORE))
    )
    embedder = None
    if retrieval_method in {"dense", "hybrid"}:
        embedder = FastEmbedDenseEmbedder(
            model_name=os.getenv(
                "KNOWLEDGE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
            ).strip()
        )
    return LocalTravelKnowledgeTool(
        retrieval_method=retrieval_method,
        embedder=embedder,
        dense_min_score=dense_min_score,
    )


__all__ = [
    "DenseEmbedder",
    "FastEmbedDenseEmbedder",
    "KnowledgeCorpus",
    "KnowledgeDocument",
    "KnowledgePassage",
    "KnowledgeSearchResult",
    "LocalTravelKnowledgeTool",
    "build_knowledge_tool_from_env",
]
