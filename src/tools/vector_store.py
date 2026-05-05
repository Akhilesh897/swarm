from collections import Counter, deque
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import chromadb

from src.config import get_config


@dataclass
class RetrievedDoc:
    content: str
    metadata: dict[str, Any]


@dataclass
class CacheEntry:
    embedding: list[float]
    response: str
    role: str | None


class RAGStore:
    def __init__(self, persist_path: str) -> None:
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self._docs: list[RetrievedDoc] = []
        self._use_embeddings = False
        self._bm25: BM25Index | None = None
        self._cache: SemanticCache | None = None
        self._embedder = None
        self._reranker = None

        config = get_config()
        self._openai_api_key = config.openai_api_key
        self._openai_embed_model = config.openai_embed_model
        self._embedding_provider = config.embedding_provider
        self._embedding_model = config.embedding_model
        self._reranker_model = config.reranker_model
        self._reranker_enabled = config.reranker_enabled
        self._cache = SemanticCache(config.semantic_cache_threshold, config.semantic_cache_size)

        self._client = chromadb.PersistentClient(path=str(self.persist_path))
        self._collection = self._client.get_or_create_collection("hr_docs")

        if self._embedding_provider == "sentence_transformers" and self._can_load_local_model(self._embedding_model):
            self._embedder = self._load_sentence_transformers(self._embedding_model)
            self._use_embeddings = self._embedder is not None
        elif self._openai_api_key and self._openai_sdk_available():
            self._use_embeddings = True

    def add_documents(self, docs: list[RetrievedDoc]) -> None:
        if not docs:
            return

        self._docs.extend(docs)
        self._bm25 = BM25Index(self._docs)
        if not self._use_embeddings:
            return

        try:
            embeddings = self._embed([doc.content for doc in docs])
        except Exception:
            self._use_embeddings = False
            return
        ids = [doc.metadata.get("doc_id") or uuid4().hex for doc in docs]
        metadatas = [doc.metadata for doc in docs]

        if hasattr(self._collection, "upsert"):
            self._collection.upsert(ids=ids, documents=[doc.content for doc in docs], embeddings=embeddings, metadatas=metadatas)
        else:
            self._collection.add(ids=ids, documents=[doc.content for doc in docs], embeddings=embeddings, metadatas=metadatas)

    def query(
        self,
        query: str,
        k: int = 3,
        role: str | None = None,
        topic_terms: list[str] | None = None,
        rerank: bool = True,
        rerank_k: int = 10,
    ) -> list[RetrievedDoc]:
        if self._use_embeddings:
            try:
                results = self._query_hybrid(query, k=max(k, rerank_k), role=role, topic_terms=topic_terms)
                return self._rerank(query, results, k) if rerank else results[:k]
            except Exception:
                self._use_embeddings = False
        results = self._query_keyword(query, k=max(k, rerank_k), role=role, topic_terms=topic_terms)
        return self._rerank(query, results, k) if rerank else results[:k]

    def expand_context(self, docs: list[RetrievedDoc], window: int = 1) -> list[RetrievedDoc]:
        if not docs or window <= 0:
            return docs
        by_position: dict[tuple[str, int], RetrievedDoc] = {}
        for doc in self._docs:
            path = str(doc.metadata.get("path", ""))
            chunk = doc.metadata.get("chunk")
            if path and isinstance(chunk, int):
                by_position[(path, chunk)] = doc

        expanded: list[RetrievedDoc] = []
        seen: set[str] = set()

        def add(doc: RetrievedDoc) -> None:
            key = _doc_key(doc)
            if key in seen:
                return
            seen.add(key)
            expanded.append(doc)

        for doc in docs:
            add(doc)
            path = str(doc.metadata.get("path", ""))
            chunk = doc.metadata.get("chunk")
            if not path or not isinstance(chunk, int):
                continue
            for offset in range(1, window + 1):
                previous_doc = by_position.get((path, chunk - offset))
                next_doc = by_position.get((path, chunk + offset))
                if previous_doc:
                    add(previous_doc)
                if next_doc:
                    add(next_doc)

        return expanded

    def _query_keyword(
        self, query: str, k: int, role: str | None, topic_terms: list[str] | None
    ) -> list[RetrievedDoc]:
        if self._bm25:
            scored = self._bm25.score(query)
        else:
            scored = [(0.0, doc) for doc in self._docs]

        filtered: list[tuple[float, RetrievedDoc]] = []
        for score, doc in scored:
            if role and doc.metadata.get("role") not in (None, role, "all", "general"):
                continue
            if topic_terms and not _topic_match(doc.metadata, topic_terms):
                continue
            if score <= 0:
                continue
            filtered.append((score, doc))
        filtered.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in filtered[:k]]

    def _query_embeddings(self, query: str, k: int, role: str | None, topic_terms: list[str] | None) -> list[RetrievedDoc]:
        filters = None
        if role:
            filters = {"role": {"$in": [role, "all", "general"]}}

        query_embedding = self._embed([query])[0]
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=filters,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        docs: list[RetrievedDoc] = []
        for doc, meta in zip(documents, metadatas):
            metadata = meta or {}
            if topic_terms and not _topic_match(metadata, topic_terms):
                continue
            docs.append(RetrievedDoc(content=doc, metadata=metadata))
        return docs

    def _query_hybrid(
        self,
        query: str,
        k: int,
        role: str | None,
        topic_terms: list[str] | None,
    ) -> list[RetrievedDoc]:
        keyword_docs = self._query_keyword(query, k=max(k, 12), role=role, topic_terms=topic_terms)
        keyword_scores = _score_map(keyword_docs, weight=1.0)

        embed_docs, embed_scores = self._query_embeddings_scored(
            query,
            k=max(k, 12),
            role=role,
            topic_terms=topic_terms,
        )

        combined: dict[str, float] = {}
        combined.update(_scale_scores(embed_scores, 0.55))
        for doc_id, score in _scale_scores(keyword_scores, 0.45).items():
            combined[doc_id] = combined.get(doc_id, 0.0) + score

        docs_by_id = {(_doc_key(doc)): doc for doc in embed_docs + keyword_docs}
        ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
        return [docs_by_id[doc_id] for doc_id, _ in ranked[:k] if doc_id in docs_by_id]

    def _query_embeddings_scored(
        self,
        query: str,
        k: int,
        role: str | None,
        topic_terms: list[str] | None,
    ) -> tuple[list[RetrievedDoc], dict[str, float]]:
        filters = None
        if role:
            filters = {"role": {"$in": [role, "all", "general"]}}
        query_embedding = self._embed([query])[0]
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=filters,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        docs: list[RetrievedDoc] = []
        scores: dict[str, float] = {}
        for doc, meta, distance in zip(documents, metadatas, distances):
            metadata = meta or {}
            if topic_terms and not _topic_match(metadata, topic_terms):
                continue
            retrieved = RetrievedDoc(content=doc, metadata=metadata)
            docs.append(retrieved)
            scores[_doc_key(retrieved)] = 1.0 / (1.0 + float(distance))
        return docs, scores

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedding_provider == "sentence_transformers" and self._embedder is not None:
            return [vec.tolist() for vec in self._embedder.encode(texts, normalize_embeddings=True)]
        from openai import OpenAI

        client = OpenAI(api_key=self._openai_api_key)
        response = client.embeddings.create(model=self._openai_embed_model, input=texts)
        return [item.embedding for item in response.data]

    def _openai_sdk_available(self) -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _sentence_transformers_available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load_sentence_transformers(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            return None
        try:
            allow_download = os.getenv("ALLOW_EMBEDDING_MODEL_DOWNLOAD", "false").lower() in {"1", "true", "yes"}
            if allow_download:
                return SentenceTransformer(model_name)
            return SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            return None

    def _can_load_local_model(self, model_name: str) -> bool:
        allow_download = os.getenv("ALLOW_EMBEDDING_MODEL_DOWNLOAD", "false").lower() in {"1", "true", "yes"}
        if allow_download or Path(model_name).exists():
            return self._sentence_transformers_available()
        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError:
            return False
        return try_to_load_from_cache(model_name, "config.json") is not None

    def _rerank(self, query: str, docs: list[RetrievedDoc], k: int) -> list[RetrievedDoc]:
        if not self._reranker_enabled or not docs:
            return docs[:k]
        reranker = self._get_reranker()
        if reranker is None:
            return docs[:k]
        pairs = [(query, doc.content) for doc in docs]
        try:
            scores = reranker.predict(pairs)
        except Exception:
            return docs[:k]
        ranked = sorted(zip(scores, docs), key=lambda item: float(item[0]), reverse=True)
        return [doc for _, doc in ranked[:k]]

    def _get_reranker(self):
        if self._reranker is not None:
            return self._reranker
        if not self._can_load_local_model(self._reranker_model):
            return None
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            return None
        try:
            allow_download = os.getenv("ALLOW_EMBEDDING_MODEL_DOWNLOAD", "false").lower() in {"1", "true", "yes"}
            if allow_download:
                self._reranker = CrossEncoder(self._reranker_model)
            else:
                self._reranker = CrossEncoder(self._reranker_model, local_files_only=True)
        except Exception:
            return None
        return self._reranker

    def embed_query(self, query: str) -> list[float] | None:
        if not self._use_embeddings:
            return None
        try:
            return self._embed([query])[0]
        except Exception:
            return None

    def cache_get(self, query: str, role: str | None) -> str | None:
        if not self._cache:
            return None
        embedding = self.embed_query(query)
        if not embedding:
            return None
        return self._cache.get(embedding, role)

    def cache_set(self, query: str, role: str | None, response: str) -> None:
        if not self._cache:
            return
        embedding = self.embed_query(query)
        if not embedding:
            return
        self._cache.set(embedding, response, role)


def _doc_key(doc: RetrievedDoc) -> str:
    return doc.metadata.get("doc_id") or doc.metadata.get("path") or doc.content[:100]


def _score_map(docs: list[RetrievedDoc], weight: float) -> dict[str, float]:
    scores: dict[str, float] = {}
    for idx, doc in enumerate(docs):
        scores[_doc_key(doc)] = max(scores.get(_doc_key(doc), 0.0), weight * (1.0 / (idx + 1)))
    return scores


def _scale_scores(scores: dict[str, float], weight: float) -> dict[str, float]:
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score <= 0:
        return {key: 0.0 for key in scores}
    return {key: (value / max_score) * weight for key, value in scores.items()}


def _topic_match(metadata: dict[str, Any], topic_terms: list[str]) -> bool:
    topic = str(metadata.get("topic", "")).lower()
    section = str(metadata.get("section", "")).lower()
    subtopic = str(metadata.get("subtopic", "")).lower()
    for term in topic_terms:
        if term and (term in topic or term in section or term in subtopic):
            return True
    return False


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25Index:
    def __init__(self, docs: list[RetrievedDoc]) -> None:
        self._docs = docs
        self._doc_tokens: list[list[str]] = [_tokenize(doc.content) for doc in docs]
        self._doc_freqs: list[Counter[str]] = [Counter(tokens) for tokens in self._doc_tokens]
        self._doc_lengths = [len(tokens) for tokens in self._doc_tokens]
        self._avg_len = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0
        self._idf = self._compute_idf()

    def _compute_idf(self) -> dict[str, float]:
        doc_count = len(self._doc_tokens)
        df: Counter[str] = Counter()
        for tokens in self._doc_tokens:
            df.update(set(tokens))
        idf: dict[str, float] = {}
        for term, freq in df.items():
            idf[term] = math.log((doc_count - freq + 0.5) / (freq + 0.5) + 1)
        return idf

    def score(self, query: str) -> list[tuple[float, RetrievedDoc]]:
        tokens = _tokenize(query)
        if not tokens or not self._docs:
            return []
        scores = [0.0 for _ in self._docs]
        k1 = 1.5
        b = 0.75
        for term in tokens:
            idf = self._idf.get(term, 0.0)
            if idf <= 0:
                continue
            for idx, freq_map in enumerate(self._doc_freqs):
                tf = freq_map.get(term, 0)
                if tf == 0:
                    continue
                denom = tf + k1 * (1 - b + b * (self._doc_lengths[idx] / (self._avg_len or 1)))
                scores[idx] += idf * ((tf * (k1 + 1)) / denom)
        return [(scores[idx], doc) for idx, doc in enumerate(self._docs)]


class SemanticCache:
    def __init__(self, threshold: float, max_size: int) -> None:
        self._threshold = threshold
        self._entries: deque[CacheEntry] = deque(maxlen=max_size)

    def get(self, embedding: list[float], role: str | None) -> str | None:
        best_score = 0.0
        best_response = None
        for entry in self._entries:
            if role and entry.role and entry.role != role:
                continue
            score = _cosine_similarity(embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_response = entry.response
        if best_score >= self._threshold:
            return best_response
        return None

    def set(self, embedding: list[float], response: str, role: str | None) -> None:
        self._entries.append(CacheEntry(embedding=embedding, response=response, role=role))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
