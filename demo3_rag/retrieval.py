"""Hybrid retrieval for Demo 3 RAG."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .ingest import BM25_PATH, CHROMA_DIR, CHUNKS_PATH, DOCS_INDEX_PATH, build_indexes, embed_texts, load_doc_store, tokenize
from .rerank_client import rerank


def ensure_indexes(*, allow_skip_chroma: bool = False) -> None:
    if not DOCS_INDEX_PATH.exists() or not CHUNKS_PATH.exists() or not BM25_PATH.exists():
        build_indexes(skip_chroma=allow_skip_chroma)


def _chunk_key(chunk: dict[str, Any]) -> str:
    return f"{chunk['doc_id']}:{chunk['chunk_id']}"


def _load_doc_map() -> dict[str, dict[str, Any]]:
    return {str(document.get("doc_id", "")): document for document in load_doc_store()}


def _get_chroma_collection() -> Any | None:
    try:
        import chromadb
    except ImportError:
        return None

    if not CHROMA_DIR.exists():
        return None
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return client.get_collection(name="demo3_docs")
    except Exception:
        return None


def _chunk_from_chroma_record(
    item_id: str,
    document: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not metadata:
        return None
    doc_id = str(metadata.get("doc_id") or "")
    chunk_id = str(metadata.get("chunk_id") or "")
    if not doc_id or not chunk_id:
        if ":" not in item_id:
            return None
        doc_id, chunk_id = item_id.rsplit(":", 1)
    return {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "title": metadata.get("title", ""),
        "section": metadata.get("section", ""),
        "source_path": metadata.get("source_path", ""),
        "category": metadata.get("category", ""),
        "content": document or "",
    }


def _hydrate_chunks_from_chroma(ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    collection = _get_chroma_collection()
    if collection is None:
        return {}
    try:
        raw = collection.get(ids=ids, include=["documents", "metadatas"])
    except Exception:
        return {}

    hydrated: dict[str, dict[str, Any]] = {}
    raw_ids = raw.get("ids", [])
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    for item_id, document, metadata in zip(raw_ids, documents, metadatas, strict=False):
        chunk = _chunk_from_chroma_record(str(item_id), document, metadata)
        if chunk:
            hydrated[str(item_id)] = chunk
    return hydrated


def bm25_search(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    payload = json.loads(Path(BM25_PATH).read_text(encoding="utf-8"))
    documents = payload.get("documents", [])
    tokenized_docs = [doc.get("tokens", []) for doc in documents]
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    try:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi(tokenized_docs)
        scores = bm25.get_scores(query_tokens)
    except Exception:
        scores = _simple_bm25_scores(tokenized_docs, query_tokens)

    ranked_indices = sorted(range(len(scores)), key=lambda index: float(scores[index]), reverse=True)[:top_k]
    scored_keys: list[tuple[str, float]] = []
    for index in ranked_indices:
        score = float(scores[index])
        if score <= 0:
            continue
        key = documents[index].get("key")
        scored_keys.append((str(key), score))

    hydrated = _hydrate_chunks_from_chroma([key for key, _ in scored_keys])
    results: list[dict[str, Any]] = []
    for key, score in scored_keys:
        item = hydrated.get(key)
        if not item:
            continue
        item = dict(item)
        item["bm25_score"] = score
        item["retrieval_score"] = score
        item["retrieval_source"] = "bm25"
        results.append(item)
    return results


def _simple_bm25_scores(tokenized_docs: list[list[str]], query_tokens: list[str]) -> list[float]:
    total_docs = len(tokenized_docs) or 1
    avg_len = sum(len(doc) for doc in tokenized_docs) / total_docs
    doc_freq: Counter[str] = Counter()
    for doc in tokenized_docs:
        for token in set(doc):
            doc_freq[token] += 1
    scores: list[float] = []
    k1 = 1.5
    b = 0.75
    for doc in tokenized_docs:
        counts = Counter(doc)
        doc_len = len(doc) or 1
        score = 0.0
        for token in query_tokens:
            if token not in counts:
                continue
            idf = math.log(1 + (total_docs - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
            tf = counts[token]
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / (avg_len or 1)))
        scores.append(score)
    return scores


def vector_search(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    collection = _get_chroma_collection()
    if collection is None:
        return []
    try:
        vector = embed_texts([query], text_type="query")[0]
        raw = collection.query(query_embeddings=[vector], n_results=top_k, include=["distances", "documents", "metadatas"])
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    ids = raw.get("ids", [[]])[0]
    distances = raw.get("distances", [[]])[0]
    documents = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    for item_id, distance, document, metadata in zip(ids, distances, documents, metadatas, strict=False):
        item = _chunk_from_chroma_record(str(item_id), document, metadata)
        if not item:
            continue
        item["vector_id"] = str(item_id)
        item["vector_distance"] = float(distance)
        item["retrieval_score"] = 1.0 / (1.0 + float(distance))
        item["retrieval_source"] = "vector"
        results.append(item)
    return results


def title_search(query: str, *, chunks_per_doc: int = 2) -> list[dict[str, Any]]:
    documents = _load_doc_map()
    bm25_payload = json.loads(Path(BM25_PATH).read_text(encoding="utf-8"))
    chunk_ids_by_doc: defaultdict[str, list[str]] = defaultdict(list)
    for item in bm25_payload.get("documents", []):
        key = str(item.get("key") or "")
        if ":" not in key:
            continue
        doc_id, _ = key.rsplit(":", 1)
        chunk_ids_by_doc[doc_id].append(key)
    phrases = _query_phrases(query)
    candidate_keys: list[str] = []
    for doc_id, document in documents.items():
        title = str(document.get("title", "")).replace("的做法", "")
        leaf = doc_id.split("/")[-1]
        haystack = f"{doc_id} {leaf} {title}"
        if not any(phrase in haystack for phrase in phrases):
            continue
        candidate_keys.extend(chunk_ids_by_doc.get(doc_id, [])[:chunks_per_doc])

    hydrated = _hydrate_chunks_from_chroma(candidate_keys)
    results: list[dict[str, Any]] = []
    for key in candidate_keys:
        item = hydrated.get(key)
        if not item:
            continue
        item = dict(item)
        item["retrieval_score"] = 2.0
        item["retrieval_source"] = "title"
        results.append(item)
    return results


def _merge_results(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    title_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    source_ranks: defaultdict[str, list[int]] = defaultdict(list)
    for source, results in (("title", title_results), ("vector", vector_results), ("bm25", bm25_results)):
        for rank, item in enumerate(results, start=1):
            key = _chunk_key(item)
            if key not in merged:
                merged[key] = dict(item)
                merged[key]["retrieval_sources"] = []
            merged[key]["retrieval_sources"].append(source)
            source_ranks[key].append(rank)
            if "bm25_score" in item:
                merged[key]["bm25_score"] = item["bm25_score"]
            if "vector_distance" in item:
                merged[key]["vector_distance"] = item["vector_distance"]
    for key, item in merged.items():
        item["fusion_score"] = sum(1.0 / (60 + rank) for rank in source_ranks[key])
    return sorted(merged.values(), key=lambda item: item.get("fusion_score", 0.0), reverse=True)


def _evidence_status(query: str, ranked: list[dict[str, Any]]) -> str:
    if not ranked:
        return "none"
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return "weak"
    top_text = " ".join(item.get("content", "") for item in ranked[:3])
    if any(phrase in top_text for phrase in _query_phrases(query)):
        return "sufficient"
    top_tokens = set(tokenize(top_text))
    overlap = len(query_tokens & top_tokens)
    if overlap == 0:
        return "none"
    if overlap <= 1 and len(query_tokens) >= 4:
        return "weak"
    compare_tokens = {"比较", "区别", "差异", "不同", "联系", "分别", "都"}
    if not any(token in query for token in compare_tokens) and _specific_bigram_coverage(query, top_text) < 0.35:
        return "none"
    return "sufficient"


def _specific_bigram_coverage(query: str, evidence_text: str) -> float:
    generic = {
        "怎么",
        "做法",
        "需要",
        "哪些",
        "多少",
        "什么",
        "分别",
        "比较",
        "差异",
        "不同",
        "文档",
        "请给",
        "给出",
        "原料",
        "材料",
        "操作",
    }
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", query))
    if len(chinese) < 4:
        return 1.0
    bigrams = [chinese[index : index + 2] for index in range(len(chinese) - 1)]
    specific = [gram for gram in bigrams if gram not in generic]
    if len(specific) < 3:
        return 1.0
    matched = sum(1 for gram in specific if gram in evidence_text)
    return matched / len(specific)


def _ambiguity_status(query: str, ranked: list[dict[str, Any]]) -> dict[str, Any]:
    if len(ranked) < 2:
        return {"ambiguous": False, "candidate_doc_ids": []}
    compare_tokens = {"比较", "区别", "差异", "不同", "联系", "分别", "都"}
    asks_for_comparison = any(token in query for token in compare_tokens)
    if asks_for_comparison:
        return {"ambiguous": False, "candidate_doc_ids": []}

    phrase_candidates = _title_candidate_doc_ids(query, ranked)
    if len(phrase_candidates) >= 2 and _asks_for_recipe_method(query):
        return {"ambiguous": True, "candidate_doc_ids": phrase_candidates[:5]}

    first_doc_ids = [str(item.get("doc_id", "")) for item in ranked[:3]]
    if first_doc_ids and first_doc_ids.count(first_doc_ids[0]) >= 2:
        return {"ambiguous": False, "candidate_doc_ids": [first_doc_ids[0]]}

    query_tokens = set(tokenize(query))
    doc_ids: list[str] = []
    for item in ranked[:6]:
        doc_id = item.get("doc_id", "")
        title = item.get("title", "")
        title_tokens = set(tokenize(title))
        if query_tokens & title_tokens and doc_id not in doc_ids:
            doc_ids.append(doc_id)
    return {"ambiguous": len(doc_ids) >= 2 and not asks_for_comparison, "candidate_doc_ids": doc_ids[:5]}


def _asks_for_comparison(query: str) -> bool:
    return any(token in query for token in ("比较", "区别", "差异", "不同", "联系", "分别", "都"))


def _asks_for_recipe_method(query: str) -> bool:
    return any(marker in query for marker in ("怎么做", "如何做", "做法", "怎么", "如何"))


def _query_phrases(query: str) -> list[str]:
    phrases: set[str] = set()
    stop_phrases = (
        "怎么做",
        "如何做",
        "怎么",
        "如何",
        "做法",
        "需要哪些",
        "需要",
        "哪些",
        "什么",
        "多少",
        "分别",
        "比较",
        "区别",
        "差异",
        "不同",
        "联系",
        "文档里",
        "文档",
        "请给出",
        "给出",
        "必备原料",
        "原料",
        "材料",
        "操作",
    )
    for word in re.findall(r"[\u4e00-\u9fff]+", query):
        cleaned = word
        for stop in stop_phrases:
            cleaned = cleaned.replace(stop, "")
        if len(cleaned) >= 3:
            phrases.add(cleaned)
        for size in range(min(10, len(cleaned)), 2, -1):
            for index in range(len(cleaned) - size + 1):
                phrase = cleaned[index : index + size]
                if phrase:
                    phrases.add(phrase)
    return sorted(phrases, key=len, reverse=True)


def _title_candidate_doc_ids(query: str, ranked: list[dict[str, Any]]) -> list[str]:
    phrases = _query_phrases(query)
    doc_ids: list[str] = []
    for item in ranked[:8]:
        doc_id = str(item.get("doc_id", ""))
        title = str(item.get("title", "")).replace("的做法", "")
        leaf = doc_id.split("/")[-1]
        haystack = f"{doc_id} {leaf} {title}"
        if any(phrase in haystack for phrase in phrases) and doc_id not in doc_ids:
            doc_ids.append(doc_id)
    return doc_ids


def _source_documents(ranked: list[dict[str, Any]], *, max_documents: int = 5) -> list[dict[str, Any]]:
    doc_map = _load_doc_map()
    by_doc: dict[str, dict[str, Any]] = {}
    ordered_doc_ids: list[str] = []
    for item in ranked:
        doc_id = str(item.get("doc_id", ""))
        chunk_id = str(item.get("chunk_id", ""))
        if not doc_id or doc_id not in doc_map:
            continue
        if doc_id not in by_doc:
            if len(ordered_doc_ids) >= max_documents:
                continue
            document = doc_map[doc_id]
            by_doc[doc_id] = {
                "doc_id": doc_id,
                "title": document.get("title", ""),
                "source_path": document.get("source_path", ""),
                "category": document.get("category", ""),
                "content_hash": document.get("content_hash", ""),
                "content": document.get("content", ""),
                "matched_chunks": [],
            }
            ordered_doc_ids.append(doc_id)
        by_doc[doc_id]["matched_chunks"].append(
            {
                "chunk_id": chunk_id,
                "score": item.get("rerank_score", item.get("fusion_score", item.get("retrieval_score", 0.0))),
                "retrieval_sources": item.get("retrieval_sources", [item.get("retrieval_source", "")]),
            }
        )
    return [by_doc[doc_id] for doc_id in ordered_doc_ids[:max_documents]]


def retrieve(query: str, *, top_k_vector: int = 8, top_k_bm25: int = 8, top_n: int = 8) -> dict[str, Any]:
    ensure_indexes(allow_skip_chroma=True)
    vector_results = vector_search(query, top_k=top_k_vector)
    bm25_results = bm25_search(query, top_k=top_k_bm25)
    title_results = title_search(query) if _asks_for_recipe_method(query) or _asks_for_comparison(query) else []
    merged = _merge_results(vector_results, bm25_results, title_results)
    ranked = rerank(query, merged, top_n=top_n)
    evidence_status = _evidence_status(query, ranked)
    ambiguity = _ambiguity_status(query, ranked)
    source_documents = _source_documents(ranked)
    return {
        "query": query,
        "evidence_status": "ambiguous" if ambiguity["ambiguous"] else evidence_status,
        "vector_top_k": top_k_vector,
        "bm25_top_k": top_k_bm25,
        "returned": len(ranked),
        "returned_documents": len(source_documents),
        "candidate_doc_ids": ambiguity["candidate_doc_ids"],
        "chunks": [
            {
                "doc_id": item.get("doc_id", ""),
                "chunk_id": item.get("chunk_id", ""),
                "title": item.get("title", ""),
                "section": item.get("section", ""),
                "source_path": item.get("source_path", ""),
                "score": item.get("rerank_score", item.get("fusion_score", item.get("retrieval_score", 0.0))),
                "retrieval_sources": item.get("retrieval_sources", [item.get("retrieval_source", "")]),
                "content": item.get("content", ""),
            }
            for item in ranked
        ],
        "source_documents": source_documents,
    }
