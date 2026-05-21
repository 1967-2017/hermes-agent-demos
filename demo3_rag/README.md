# Demo 3: Hermes Native RAG Document QA

Demo 3 builds a RAG agent over `demo3_rag/data/docs` with explicit ChatML plus Hermes-native `<tool_call>` blocks.

It does not use LangChain, OpenAI function calling, or hardcoded scenario answers.

## Architecture

- Chunking: Markdown files are split by headings, then long sections are split into 350-900 character chunks.
- Document store: `demo3_rag/data/index/docs.jsonl` stores one cleaned full-text record per source document.
- Chunk store: `demo3_rag/data/index/chunks.jsonl` is retained as a build/debug artifact.
- Vector store: Chroma persistent collection at `demo3_rag/data/index/chroma` stores chunk embeddings, chunk text, and lightweight chunk metadata.
- Retrieval: Chroma top-k=8 plus BM25 top-k=8 are hydrated through Chroma, reranked with DashScope `qwen3-vl-rerank`, then mapped to deduplicated full source documents from `docs.jsonl`.
- Generation: answers must cite evidence as `[doc_id:chunk_id]`, with at most two citations per sentence.

## Environment

Repo-local `.env` values override inherited environment variables.

Set the normal chat model variables:

```powershell
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

Demo 3 retrieval uses DashScope only:

```powershell
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_API_KEY=
DEMO3_EMBEDDING_MODEL=text-embedding-v3
DEMO3_RERANK_MODEL=qwen3-vl-rerank
```

## Install Dependencies

```powershell
pip install chromadb rank-bm25 jieba
```

## Build Index

```powershell
python -m demo3_rag.ingest
```

This writes:

- `chunks.jsonl` with full chunk text and metadata
- `docs.jsonl` with full cleaned source document text and metadata
- `bm25.json` with BM25 keys and tokens
- Chroma with chunk ids, embeddings, chunk text, and lightweight chunk metadata

For a lightweight local parse/BM25 check without embeddings:

```powershell
python -m demo3_rag.ingest --skip-chroma
```

## Run

```powershell
python -m demo3_rag.main --input "西红柿炒鸡蛋需要哪些原料？"
python -m demo3_rag.main --scenario single_001
```

## Viewer

Start the interactive RAG viewer:

```powershell
python -m demo3_rag.viewer_server
```

Open:

```text
http://127.0.0.1:8766/viewer/
```

The viewer can run built-in scenarios or manual questions, stream runtime events with SSE, and inspect JSON traces from `demo3_rag/data/traces`.

## Verify

```powershell
python -m demo3_rag.verify
python -m demo3_rag.verify --scenario none_001
python -m demo3_rag.verify --hardcoding-only
```

The eval set contains 20 scenarios:

- 8 single-document answerable questions
- 6 cross-document synthesis questions
- 4 unsupported questions that must say `未找到`
- 2 ambiguous questions that must ask for clarification

Traces are written to `demo3_rag/data/traces`.
