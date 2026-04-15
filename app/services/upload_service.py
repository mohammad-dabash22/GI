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
