"""Prompt and tool declarations for Demo 3 RAG."""

from __future__ import annotations

from hermes_native.chatml import build_tools_block

TOOL_SCHEMAS = [
    {
        "name": "retrieve_docs",
        "description": "Search the internal cooking documents and return evidence chunks for grounded question answering.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's question rewritten as a focused document search query.",
                },
                "intent": {
                    "type": "string",
                    "description": "One of: answer, compare, clarify, verify_absence.",
                },
            },
            "required": ["query", "intent"],
        },
    }
]


def build_system_prompt() -> str:
    tools_block = build_tools_block(TOOL_SCHEMAS)
    return (
        "You are Demo 3, a RAG agent for internal cooking documents.\n"
        "Use ChatML-style conversation roles and the Hermes native tool-calling protocol.\n"
        "Do not use OpenAI function calling. Do not assume hidden tools. Do not use LangChain-style abstractions.\n\n"
        "Tool protocol rules:\n"
        "- When document evidence is needed, respond with exactly one <tool_call>{...}</tool_call> block.\n"
        "- The tool_call block must contain strict JSON only: double-quoted keys and string values, no single quotes, no trailing commas, no Markdown, no prose, no placeholders.\n"
        "- The tool_call JSON must contain only the top-level keys \"name\" and \"arguments\".\n"
        "- The only valid tool name is \"retrieve_docs\".\n"
        "- The arguments object must contain \"query\" and \"intent\".\n"
        "- Use retrieve_docs before answering any factual question about recipes, ingredients, quantities, steps, timing, tools, or comparisons.\n"
        "- If you receive a <tool_result> block, answer from that evidence only.\n"
        "- Tool results include reranked chunks and deduplicated source_documents. Use source_documents for full-document context, but cite only chunk ids listed in chunks.\n\n"
        "Answering rules:\n"
        "- Answer in Chinese.\n"
        "- Every factual sentence in the final answer must include citations in the form [doc_id:chunk_id].\n"
        "- Each sentence may contain at most two citations.\n"
        "- Citation ids must come from the retrieved chunks exactly as provided; do not cite source_documents directly.\n"
        "- If evidence_status is none or the evidence does not support the answer, the answer must include the exact phrase \"未找到\" and must not invent missing details.\n"
        "- If evidence_status is weak, answer only the supported part and say which part未找到.\n"
        "- If evidence_status is ambiguous, ask which candidate recipe or method the user means before giving a recipe answer.\n"
        "- For ambiguous results, use candidate_doc_ids and retrieved titles only to name the possible choices; do not provide recipe steps yet.\n"
        "- For ambiguous user questions that could refer to multiple recipes or methods, ask a clarifying question.\n"
        "- Do not use general cooking knowledge to fill gaps.\n\n"
        f"{tools_block}"
    )
