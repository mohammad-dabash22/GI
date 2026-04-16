"""Pass 1: Fast parallel extraction with document-type-specific prompts."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

from app.config import FAST_MODEL, MAX_CONCURRENT_CALLS
from app.ai.client import call_llm, parse_json
from app.ai.prompts.extraction import DOCUMENT_TYPE_PROMPTS, BASE_SYSTEM

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS)


def _build_source_tag(filename: str, chunk: dict) -> str:
    """Build a human-readable source reference from chunk metadata."""
    parts = []
    if "page" in chunk:
        parts.append(f"Page {chunk['page']}")
    if "paragraph" in chunk:
        parts.append(f"Paragraph {chunk['paragraph']}")
    if "line_start" in chunk:
        parts.append(f"Lines {chunk['line_start']}-{chunk['line_end']}")
    return f"{filename}:{','.join(parts)}" if parts else filename


def _build_location_string(chunk: dict) -> str:
    """Build a location string from chunk metadata."""
    location_parts = []
    if "page" in chunk:
        location_parts.append(f"Page {chunk['page']}")
    if "paragraph" in chunk:
        location_parts.append(f"Paragraph {chunk['paragraph']}")
    if "line_start" in chunk:
        location_parts.append(f"Lines {chunk['line_start']}-{chunk['line_end']}")
    return ", ".join(location_parts) or "Unknown"


def _extract_chunk(filename: str, chunk: dict, doc_type: str) -> dict:
    """Extract entities and relationships from a single text chunk."""
    system = DOCUMENT_TYPE_PROMPTS.get(doc_type, BASE_SYSTEM)
    source = _build_source_tag(filename, chunk)
    location = _build_location_string(chunk)

    user = (
        f"Extract all entities and relationships from this document section.\n\n"
        f"Source file: {filename}\nDocument type: {doc_type}\nLocation: {location}\n\n"
        f"IMPORTANT: For the 'evidence' field, quote the EXACT sentence(s) from the text below. "
        f"Prefix with the specific line reference, e.g. 'Line 5: Viktor Petrov is the CEO'. "
        f"Do NOT cite the entire range '{location}' -- cite only the specific line(s).\n\n"
        f"--- DOCUMENT TEXT ---\n{chunk['text']}\n--- END ---\n\n"
        f"Return valid JSON only."
    )

    try:
        print(f"[EXTRACT] Calling LLM for {source} ...")
        raw = call_llm(system, user, model=FAST_MODEL, max_tokens=4096)
        print(f"[EXTRACT] Got response for {source} ({len(raw)} chars)")
        data = parse_json(raw)
        for e in data.get("entities", []):
            e["source"] = source
        for r in data.get("relationships", []):
            r["source"] = source
        print(f"[EXTRACT] {source}: {len(data.get('entities', []))} entities, "
              f"{len(data.get('relationships', []))} rels")
        return data
    except Exception as e:
        print(f"[EXTRACT ERROR] {source}: {type(e).__name__}: {e}")
        return {"entities": [], "relationships": [], "errors": [f"Chunk error ({source}): {e}"]}


def _make_doc_prefix(filename: str, chunk_idx: int) -> str:
    """Create a unique prefix for namespacing entity IDs within a chunk."""
    h = hashlib.md5(filename.encode()).hexdigest()[:4]
    return f"{h}_c{chunk_idx}"


def _namespace_ids(data: dict, prefix: str) -> dict:
    """Add prefix to all entity IDs and remap relationship from_id/to_id."""
    id_map = {}
    for e in data.get("entities", []):
        old_id = e.get("id", "")
        if old_id:
            new_id = f"{prefix}_{old_id}"
            id_map[old_id] = new_id
            e["id"] = new_id
    for r in data.get("relationships", []):
        fid = r.get("from_id", "")
        tid = r.get("to_id", "")
        if fid in id_map:
            r["from_id"] = id_map[fid]
        if tid in id_map:
            r["to_id"] = id_map[tid]
    return data


def pass1_quick_extract(filename: str, chunks: list[dict], doc_type: str,
                        progress_cb=None) -> dict:
    """Pass 1: Fast parallel extraction with type-specific prompts."""
    all_entities, all_relationships, errors = [], [], []

    def _process(chunk_idx, chunk):
        return chunk_idx, _extract_chunk(filename, chunk, doc_type)

    futures = []
    for ci, chunk in enumerate(chunks):
        futures.append(_executor.submit(_process, ci, chunk))

    for i, future in enumerate(futures):
        try:
            chunk_idx, result = future.result(timeout=120)
            prefix = _make_doc_prefix(filename, chunk_idx)
            result = _namespace_ids(result, prefix)
            for e in result.get("entities", []):
                if not e.get("id"):
                    e["id"] = f"{prefix}_ent_{len(all_entities)}"
            all_entities.extend(result.get("entities", []))
            all_relationships.extend(result.get("relationships", []))
            errors.extend(result.get("errors", []))
        except Exception as e:
            errors.append(f"Chunk {i} failed: {e}")
        if progress_cb:
            progress_cb("pass1", i + 1, len(futures))

    return {"entities": all_entities, "relationships": all_relationships, "errors": errors}
