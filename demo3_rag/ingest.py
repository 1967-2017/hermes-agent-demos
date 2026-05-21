"""Build Demo 3 document chunks and retrieval indexes."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import get_dashscope_api_key, get_dashscope_base_url, load_repo_env

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"
INDEX_DIR = DATA_DIR / "index"
CHROMA_DIR = INDEX_DIR / "chroma"
DOCS_INDEX_PATH = INDEX_DIR / "docs.jsonl"
CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
BM25_PATH = INDEX_DIR / "bm25.json"

TARGET_CHARS = 650
MAX_CHARS = 900
OVERLAP_CHARS = 100
DASHSCOPE_EMBED_BATCH_LIMIT = 10
DASHSCOPE_EMBED_MAX_ATTEMPTS = 3

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")


@dataclass
class DocumentRecord:
    doc_id: str
    source_path: str
    title: str
    category: str
    content: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "title": self.title,
            "category": self.category,
            "content": self.content,
            "content_hash": self.content_hash,
        }


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    source_path: str
    title: str
    section: str
    category: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "source_path": self.source_path,
            "title": self.title,
            "section": self.section,
            "category": self.category,
            "content": self.content,
        }


def ensure_index_dirs() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def _read_markdown(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _clean_markdown(text: str) -> str:
    text = IMAGE_RE.sub("", text)
    text = LINK_RE.sub(r"\1", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    compact: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def _doc_id_for(path: Path) -> str:
    relative = path.relative_to(DOCS_DIR).with_suffix("")
    return relative.as_posix()


def _stable_short_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _split_by_headings(text: str) -> tuple[str, list[tuple[str, str]]]:
    title = ""
    sections: list[tuple[str, list[str]]] = []
    current_name = "正文"
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        match = HEADING_RE.match(raw_line)
        if match:
            level = len(match.group(1))
            name = match.group(2).strip()
            if level == 1 and not title:
                title = name
                continue
            if level <= 3:
                if current_lines:
                    sections.append((current_name, current_lines))
                current_name = name
                current_lines = []
                continue
        current_lines.append(raw_line)

    if current_lines:
        sections.append((current_name, current_lines))
    return title, [(name, "\n".join(lines).strip()) for name, lines in sections if "\n".join(lines).strip()]


def _split_long_text(text: str) -> list[str]:
    stripped = text.strip()
    if len(stripped) <= MAX_CHARS:
        return [stripped]

    paragraphs = re.split(r"\n\s*\n", stripped)
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > MAX_CHARS:
            for line in paragraph.splitlines():
                line = line.strip()
                if not line:
                    continue
                if len(current) + len(line) + 1 > TARGET_CHARS and current:
                    pieces.append(current.strip())
                    current = current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else ""
                current = f"{current}\n{line}".strip()
            continue
        if len(current) + len(paragraph) + 2 > TARGET_CHARS and current:
            pieces.append(current.strip())
            current = current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else ""
        current = f"{current}\n\n{paragraph}".strip()
    if current:
        pieces.append(current.strip())
    return pieces


def load_corpus() -> tuple[list[DocumentRecord], list[Chunk]]:
    documents: list[DocumentRecord] = []
    chunks: list[Chunk] = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        raw = _read_markdown(path)
        cleaned = _clean_markdown(raw)
        if not cleaned:
            continue
        doc_id = _doc_id_for(path)
        relative_parts = path.relative_to(DOCS_DIR).parts
        category = relative_parts[0] if relative_parts else ""
        title, sections = _split_by_headings(cleaned)
        if not title:
            title = path.stem
        source_path = str(path.relative_to(BASE_DIR.parent))
        documents.append(
            DocumentRecord(
                doc_id=doc_id,
                source_path=source_path,
                title=title,
                category=category,
                content=cleaned,
                content_hash=hashlib.sha1(cleaned.encode("utf-8")).hexdigest(),
            )
        )
        chunk_index = 1
        for section_name, section_text in sections:
            for piece in _split_long_text(section_text):
                content = f"标题：{title}\n章节：{section_name}\n\n{piece}".strip()
                chunks.append(
                    Chunk(
                        doc_id=doc_id,
                        chunk_id=f"c{chunk_index:03d}",
                        source_path=source_path,
                        title=title,
                        section=section_name,
                        category=category,
                        content=content,
                    )
                )
                chunk_index += 1
    return documents, chunks


def load_documents() -> list[Chunk]:
    _, chunks = load_corpus()
    return chunks


def write_doc_store(documents: list[DocumentRecord]) -> Path:
    ensure_index_dirs()
    with DOCS_INDEX_PATH.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document.to_dict(), ensure_ascii=False) + "\n")
    return DOCS_INDEX_PATH


def load_doc_store() -> list[dict[str, Any]]:
    if not DOCS_INDEX_PATH.exists():
        return []
    documents: list[dict[str, Any]] = []
    for line in DOCS_INDEX_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            documents.append(json.loads(line))
    return documents


def write_chunks(chunks: list[Chunk]) -> Path:
    ensure_index_dirs()
    with CHUNKS_PATH.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    return CHUNKS_PATH


def load_chunks() -> list[dict[str, Any]]:
    if not CHUNKS_PATH.exists():
        return []
    chunks: list[dict[str, Any]] = []
    for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def tokenize(text: str) -> list[str]:
    try:
        import jieba

        jieba.setLogLevel(logging.ERROR)
        return [token.strip().lower() for token in jieba.lcut(text) if token.strip()]
    except Exception:
        return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", text.lower())


def write_bm25_index(chunks: list[Chunk]) -> Path:
    payload = {
        "version": 1,
        "documents": [
            {
                "key": f"{chunk.doc_id}:{chunk.chunk_id}",
                "tokens": tokenize(f"{chunk.title} {chunk.section} {chunk.content}"),
            }
            for chunk in chunks
        ],
    }
    BM25_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return BM25_PATH


def _embedding_config() -> tuple[str, str, str]:
    base_url = get_dashscope_base_url()
    api_key = get_dashscope_api_key()
    model = (os.getenv("DEMO3_EMBEDDING_MODEL") or "").strip()
    if not api_key or not model:
        raise RuntimeError(
            "DashScope embedding config missing. Set DASHSCOPE_API_KEY and DEMO3_EMBEDDING_MODEL."
        )
    return base_url, api_key, model


def _parse_embedding_vectors(raw: str, *, expected_count: int) -> list[list[float]]:
    parsed = json.loads(raw)
    output = parsed.get("output") or {}
    rows = sorted(
        output.get("embeddings", []),
        key=lambda item: int(item.get("text_index", item.get("index", 0))),
    )
    vectors = [row.get("embedding") for row in rows]
    if len(vectors) != expected_count or not all(isinstance(vector, list) for vector in vectors):
        raise RuntimeError("Embedding response did not contain one vector per input.")
    return vectors


def _embed_text_batch(texts: list[str], *, text_type: str) -> list[list[float]]:
    base_url, api_key, model = _embedding_config()
    url = f"{base_url}/services/embeddings/text-embedding/text-embedding"
    payload = {
        "model": model,
        "input": {"texts": texts},
        "parameters": {"text_type": text_type},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    batch_size = len(texts)

    for attempt in range(1, DASHSCOPE_EMBED_MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url=url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                try:
                    raw = response.read().decode("utf-8")
                except http.client.IncompleteRead as exc:
                    partial = exc.partial.decode("utf-8", errors="replace")
                    try:
                        return _parse_embedding_vectors(partial, expected_count=batch_size)
                    except (json.JSONDecodeError, RuntimeError) as parse_exc:
                        last_error = RuntimeError(
                            f"Incomplete embedding response on attempt {attempt}/{DASHSCOPE_EMBED_MAX_ATTEMPTS} "
                            f"for batch_size={batch_size} text_type={text_type}: {parse_exc}"
                        )
                else:
                    try:
                        return _parse_embedding_vectors(raw, expected_count=batch_size)
                    except (json.JSONDecodeError, RuntimeError) as parse_exc:
                        last_error = RuntimeError(
                            f"Invalid embedding response on attempt {attempt}/{DASHSCOPE_EMBED_MAX_ATTEMPTS} "
                            f"for batch_size={batch_size} text_type={text_type}: {parse_exc}"
                        )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding request failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(
                f"Embedding request network failure on attempt {attempt}/{DASHSCOPE_EMBED_MAX_ATTEMPTS} "
                f"for batch_size={batch_size} text_type={text_type}: {exc}"
            )
        except http.client.IncompleteRead as exc:
            partial = exc.partial.decode("utf-8", errors="replace")
            try:
                return _parse_embedding_vectors(partial, expected_count=batch_size)
            except (json.JSONDecodeError, RuntimeError) as parse_exc:
                last_error = RuntimeError(
                    f"Incomplete embedding response on attempt {attempt}/{DASHSCOPE_EMBED_MAX_ATTEMPTS} "
                    f"for batch_size={batch_size} text_type={text_type}: {parse_exc}"
                )

        if attempt < DASHSCOPE_EMBED_MAX_ATTEMPTS:
            time.sleep(attempt)

    raise RuntimeError(
        f"Embedding request failed after {DASHSCOPE_EMBED_MAX_ATTEMPTS} attempts "
        f"for batch_size={batch_size} text_type={text_type}: {last_error}"
    )


def embed_texts(texts: list[str], *, text_type: str = "document") -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), DASHSCOPE_EMBED_BATCH_LIMIT):
        batch = texts[start : start + DASHSCOPE_EMBED_BATCH_LIMIT]
        vectors.extend(_embed_text_batch(batch, text_type=text_type))
    return vectors


def build_chroma_index(chunks: list[Chunk], *, batch_size: int = 64) -> None:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("chromadb is required for Demo 3. Install chromadb before indexing.") from exc

    ensure_index_dirs()
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(name="demo3_docs", metadata={"hnsw:space": "cosine"})
    existing = collection.get(include=[])
    existing_ids = set(existing.get("ids", []))
    if existing_ids:
        collection.delete(ids=list(existing_ids))

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embed_texts([chunk.content for chunk in batch], text_type="document")
        collection.add(
            ids=[f"{chunk.doc_id}:{chunk.chunk_id}" for chunk in batch],
            embeddings=vectors,
            documents=[chunk.content for chunk in batch],
            metadatas=[
                {
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "source_path": chunk.source_path,
                    "title": chunk.title,
                    "section": chunk.section,
                    "category": chunk.category,
                }
                for chunk in batch
            ],
        )


def build_indexes(*, skip_chroma: bool = False) -> dict[str, Any]:
    documents, chunks = load_corpus()
    write_doc_store(documents)
    write_chunks(chunks)
    write_bm25_index(chunks)
    chroma_built = False
    if not skip_chroma:
        build_chroma_index(chunks)
        chroma_built = True
    return {
        "chunk_count": len(chunks),
        "doc_count": len(documents),
        "docs_path": str(DOCS_INDEX_PATH),
        "chunks_path": str(CHUNKS_PATH),
        "bm25_path": str(BM25_PATH),
        "chroma_built": chroma_built,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Demo 3 RAG indexes.")
    parser.add_argument("--skip-chroma", action="store_true", help="Only write chunk and BM25 indexes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_repo_env()
    args = parse_args(argv)
    result = build_indexes(skip_chroma=args.skip_chroma)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
