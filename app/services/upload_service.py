"""Upload service: file storage, text extraction, and pipeline orchestration."""

import json
import os
import uuid

from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS
from app.models import DocumentRecord
from app.core.extractors import extract_text
from app.core.deduplication import deduplicate_entities, remap_relationships
from app.core.graph_builder import build_graph_data
from app.core.graph_state import load_graph, save_graph, push_undo, require_project, get_pipeline_status
from app.ai.pipeline import extract_full_pipeline
from app.services.audit_service import log_action


async def process_upload(
    files,
    doc_types: str,
    mode: str,
    project_id: int,
    username: str,
    db: Session,
) -> dict:
    """Process uploaded documents through the extraction pipeline.

    Returns the API response dict (success/failure, graph data, errors).
    """
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    push_undo(project_id, gs.entities, gs.relationships)

    if mode == "new":
        gs.entities.clear()
        gs.relationships.clear()
        gs.errors.clear()

    try:
        doc_type_map = json.loads(doc_types)
    except (json.JSONDecodeError, TypeError):
        doc_type_map = {}

    files_data = []
    all_errors = list(gs.errors)

    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            all_errors.append(f"Skipped unsupported file: {file.filename}")
            continue

        safe_name = f"{uuid.uuid4().hex}_{file.filename}"
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        doc_rec = DocumentRecord(
            project_id=project_id,
            original_name=file.filename,
            stored_filename=safe_name,
            doc_type=doc_type_map.get(file.filename, "Other"),
            file_path=save_path,
        )
        db.add(doc_rec)
        db.commit()

        try:
            filename, chunks = extract_text(save_path)
            if not chunks:
                all_errors.append(f"No text extracted from {file.filename}")
                continue
            full_text = "\n\n".join(c["text"] for c in chunks)
            dtype = doc_type_map.get(file.filename, "Other")
            files_data.append({
                "filename": filename,
                "chunks": chunks,
                "doc_type": dtype,
                "full_text": full_text,
            })
        except Exception as e:
            all_errors.append(f"Error reading {file.filename}: {str(e)}")

    if not files_data:
        return {
            "success": False,
            "error": "No processable files",
            "errors": all_errors,
            "status_code": 400,
        }

    ps = get_pipeline_status(project_id)
    ps["running"] = True
    ps["current_pass"] = 0
    ps["pass_detail"] = "Starting..."
    ps["events"] = []

    def _progress_cb(pass_name, current, total):
        ps["current_pass"] = int(pass_name.replace("pass", ""))
        ps["pass_detail"] = f"{pass_name}: {current}/{total}"

    try:
        result = extract_full_pipeline(files_data, progress_cb=_progress_cb)
        new_entities = result["entities"]
        new_relationships = result["relationships"]
        all_errors.extend(result.get("errors", []))

        combined_entities = list(gs.entities) + new_entities
        combined_rels = list(gs.relationships) + new_relationships
        deduped_entities, id_mapping = deduplicate_entities(combined_entities)
        remapped_rels = remap_relationships(combined_rels, id_mapping)

        save_graph(project_id, deduped_entities, remapped_rels, all_errors, db)
        graph_data = build_graph_data(deduped_entities, remapped_rels)

        log_action("upload_documents", user=username, details={
            "project_id": project_id,
            "files": [fd["filename"] for fd in files_data],
            "entities_extracted": len(deduped_entities),
            "relationships_extracted": len(remapped_rels),
            "mode": mode,
        })

        return {
            "success": True,
            "files_processed": [fd["filename"] for fd in files_data],
            "entity_count": len(deduped_entities),
            "relationship_count": len(remapped_rels),
            "errors": all_errors,
            "graph": graph_data,
            "pipeline": {
                "passes_completed": result.get("pass", 0),
                "merges_applied": result.get("pass2_result", {}).get("merges_applied", 0),
            },
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        all_errors.append(f"Pipeline error: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "errors": all_errors,
            "status_code": 500,
        }
    finally:
        ps["running"] = False


# ── Structured (XLSX/CSV) upload ─────────────────────────────────────────────


def _build_txn_label(props: dict) -> str:
    """Build a short, human-readable edge label from transaction properties."""
    parts = []
    if props.get("amount"):
        try:
            parts.append(f"${float(props['amount']):,.2f}")
        except (ValueError, TypeError):
            parts.append(str(props["amount"]))
    if props.get("reference"):
        parts.append(str(props["reference"]))
    if props.get("start_date"):
        parts.append(str(props["start_date"]))
    return " - ".join(parts) if parts else "Transaction"


def _aggregate_relationships(relationships: list[dict], filename: str) -> list[dict]:
    """Group transaction edges by (from_id, to_id) direction. Returns one
    aggregated edge per pair with individual transactions in properties."""
    pair_map: dict[tuple, dict] = {}

    for rel in relationships:
        key = (rel["from_id"], rel["to_id"])
        bucket = pair_map.setdefault(key, {
            "total": 0.0,
            "count": 0,
            "min_date": None,
            "max_date": None,
            "transactions": [],
        })
        bucket["count"] += 1
        try:
            amt = float(rel["properties"].get("amount", 0))
            bucket["total"] += amt
        except (ValueError, TypeError):
            pass  # non-numeric amount — skip aggregation total
        date_str = rel["properties"].get("start_date")
        if date_str:
            if bucket["min_date"] is None or date_str < bucket["min_date"]:
                bucket["min_date"] = date_str
            if bucket["max_date"] is None or date_str > bucket["max_date"]:
                bucket["max_date"] = date_str
        bucket["transactions"].append(rel["properties"])

    aggregated = []
    for (fid, tid), bucket in pair_map.items():
        date_range = ""
        if bucket["min_date"] and bucket["max_date"]:
            date_range = f" | {bucket['min_date']} – {bucket['max_date']}"
        elif bucket["min_date"]:
            date_range = f" | {bucket['min_date']}"

        label = f"Total: ${bucket['total']:,.2f} | {bucket['count']} transactions{date_range}"

        aggregated.append({
            "from_id": fid,
            "to_id": tid,
            "type": "transferred_money_to",
            "label": label,
            "source": filename,
            "evidence": f"Aggregated from {bucket['count']} rows in {filename}",
            "confidence": "high",
            "confidence_score": 9,
            "confidence_reason": "Derived from structured data file",
            "properties": {
                "total": bucket["total"],
                "count": bucket["count"],
                "min_date": bucket["min_date"],
                "max_date": bucket["max_date"],
                "transactions": bucket["transactions"],
            },
        })
    return aggregated


def process_structured_upload(
    data: dict,
    username: str,
    db: Session,
) -> dict:
    """Process a structured (XLSX/CSV) upload. No AI involved.

    data keys: project_id, mode, filename, mapping, default_entity_type, rows
    Returns the API response dict.
    """
    project_id = data["project_id"]
    mode = data.get("mode", "incremental")
    filename = data.get("filename", "structured_upload.csv")
    mapping = data["mapping"]
    default_entity_type = data.get("default_entity_type", "Account")
    rows = data.get("rows", [])

    require_project(project_id, db)
    gs = load_graph(project_id, db)
    push_undo(project_id, gs.entities, gs.relationships)

    if mode == "new":
        gs.entities.clear()
        gs.relationships.clear()
        gs.errors.clear()

    all_errors: list[str] = list(gs.errors)

    # Column indices from the mapping
    from_col = mapping.get("from_entity")
    to_col = mapping.get("to_entity")
    amount_col = mapping.get("amount")
    date_col = mapping.get("date")
    ref_col = mapping.get("reference")
    from_type_col = mapping.get("from_type")
    to_type_col = mapping.get("to_type")

    if from_col is None or to_col is None:
        return {
            "success": False,
            "error": "Both 'From Entity' and 'To Entity' columns must be mapped.",
            "errors": all_errors,
            "status_code": 400,
        }

    # ── Step 1: Create entities from unique From/To values ──
    entity_map: dict[str, dict] = {}  # normalized_name -> entity dict

    def _get_or_create_entity(raw_name, type_col, row):
        name = str(raw_name).strip()
        if not name:
            return None
        lookup_key = name.lower()
        if lookup_key not in entity_map:
            etype = default_entity_type
            if type_col is not None:
                try:
                    etype = str(row[type_col]).strip() or default_entity_type
                except (IndexError, TypeError):
                    pass
            entity_map[lookup_key] = {
                "id": f"struct_{uuid.uuid4().hex[:8]}",
                "name": name,
                "type": etype,
                "source": filename,
                "sources": [filename],
                "evidence": f"From structured upload: {filename}",
                "all_evidence": [f"From structured upload: {filename}"],
                "confidence": "high",
                "confidence_score": 9,
                "confidence_reason": "Derived from structured data file",
                "properties": {},
            }
        return entity_map[lookup_key]

    # ── Step 2: Create individual edges from each row ──
    raw_relationships: list[dict] = []

    for idx, row in enumerate(rows):
        try:
            from_val = row[from_col] if from_col < len(row) else None
            to_val = row[to_col] if to_col < len(row) else None
        except (IndexError, TypeError):
            all_errors.append(f"Row {idx + 1}: could not read From/To columns")
            continue

        if not from_val or not to_val:
            all_errors.append(f"Row {idx + 1}: missing From or To value, skipped")
            continue

        from_entity = _get_or_create_entity(from_val, from_type_col, row)
        to_entity = _get_or_create_entity(to_val, to_type_col, row)
        if not from_entity or not to_entity:
            continue

        props = {}
        if amount_col is not None:
            try:
                props["amount"] = row[amount_col] if amount_col < len(row) else None
            except (IndexError, TypeError):
                pass
        if date_col is not None:
            try:
                props["start_date"] = str(row[date_col]) if date_col < len(row) else None
            except (IndexError, TypeError):
                pass
        if ref_col is not None:
            try:
                props["reference"] = str(row[ref_col]) if ref_col < len(row) else None
            except (IndexError, TypeError):
                pass

        raw_relationships.append({
            "from_id": from_entity["id"],
            "to_id": to_entity["id"],
            "type": "transferred_money_to",
            "label": _build_txn_label(props),
            "source": filename,
            "evidence": f"Row {idx + 1}: {str(from_val).strip()} -> {str(to_val).strip()}",
            "confidence": "high",
            "confidence_score": 9,
            "confidence_reason": "Derived from structured data file",
            "properties": props,
        })

    if not entity_map:
        return {
            "success": False,
            "error": "No valid entities found in upload",
            "errors": all_errors,
            "status_code": 400,
        }

    # ── Step 3: Aggregate before dedup ──
    new_entities = list(entity_map.values())
    aggregated_rels = _aggregate_relationships(raw_relationships, filename)

    # ── Step 4: Merge with existing graph ──
    combined_entities = list(gs.entities) + new_entities
    combined_rels = list(gs.relationships) + aggregated_rels
    deduped_entities, id_mapping = deduplicate_entities(combined_entities)
    remapped_rels = remap_relationships(combined_rels, id_mapping)

    save_graph(project_id, deduped_entities, remapped_rels, all_errors, db)
    graph_data = build_graph_data(deduped_entities, remapped_rels)

    log_action("upload_structured", user=username, details={
        "project_id": project_id,
        "filename": filename,
        "rows_processed": len(rows),
        "rows_skipped": len(rows) - len(raw_relationships),
        "entities_created": len(new_entities),
        "aggregated_edges": len(aggregated_rels),
        "mode": mode,
    })

    return {
        "success": True,
        "files_processed": [filename],
        "entity_count": len(deduped_entities),
        "relationship_count": len(remapped_rels),
        "errors": all_errors,
        "graph": graph_data,
        "structured": {
            "rows_processed": len(raw_relationships),
            "rows_skipped": len(rows) - len(raw_relationships),
            "entities_created": len(new_entities),
            "aggregated_edges": len(aggregated_rels),
        },
    }

