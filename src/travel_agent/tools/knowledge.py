from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "knowledge"
    / "japan_travel_safety.json"
)

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
    rank: int


class KnowledgeSearchResult(BaseModel):
    query: str
    provider: str = "local-official-snapshot"
    retrieval_method: str = "bm25"
    minimum_score: float = MIN_BM25_SCORE
    snapshot_date: str
    passages: list[KnowledgePassage]


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

    def __init__(self, corpus_path: Path | None = None) -> None:
        self.corpus_path = corpus_path or DEFAULT_CORPUS_PATH
        payload = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        self.corpus = KnowledgeCorpus.model_validate(payload)
        self._document_tokens = [
            _tokenize(
                " ".join(
                    [
                        document.title,
                        document.text,
                        *document.topics,
                        *document.keywords,
                    ]
                )
            )
            for document in self.corpus.documents
        ]

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("knowledge query must be a non-empty string")
        top_k = arguments.get("top_k", 3)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 5:
            raise ValueError("top_k must be an integer between 1 and 5")

        query_tokens = _tokenize(query)
        scores = self._bm25_scores(query_tokens)
        ranked = sorted(
            enumerate(scores),
            key=lambda item: (-item[1], self.corpus.documents[item[0]].id),
        )[:top_k]
        passages = [
            KnowledgePassage(
                **self.corpus.documents[index].model_dump(exclude={"keywords"}),
                score=round(score, 6),
                rank=rank,
            )
            for rank, (index, score) in enumerate(ranked, start=1)
            if score >= MIN_BM25_SCORE
        ]
        return KnowledgeSearchResult(
            query=query.strip(),
            snapshot_date=self.corpus.snapshot_date,
            passages=passages,
        ).model_dump()

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


__all__ = [
    "KnowledgeCorpus",
    "KnowledgeDocument",
    "KnowledgePassage",
    "KnowledgeSearchResult",
    "LocalTravelKnowledgeTool",
]
