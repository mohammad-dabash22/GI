import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from database import get_db
from models import DocumentRecord
from auth import get_current_user, get_current_user_or_token
from audit_log import get_log
from graph_state import load_graph

router = APIRouter(prefix="/api")


@router.get("/documents")
async def list_documents(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = db.query(DocumentRecord).filter(DocumentRecord.project_id == project_id).all()
    docs = [
        {
            "name": r.original_name,
            "ext": os.path.splitext(r.original_name)[1].lower(),
            "available": os.path.exists(r.file_path),
        }
        for r in records
    ]
    return JSONResponse({"documents": docs})


@router.get("/document/{filename}")
async def serve_document(
    filename: str,
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(DocumentRecord).filter(
        DocumentRecord.project_id == project_id,
        DocumentRecord.original_name == filename,
    ).first()
    if not record or not os.path.exists(record.file_path):
        return JSONResponse({"error": "File not found"}, status_code=404)
    ext = os.path.splitext(filename)[1].lower()
    media_types = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/plain"}
    media = media_types.get(ext, "application/octet-stream")
    with open(record.file_path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/export/report")
async def export_report(
    project_id: int = Query(...),
    token: str = Query(""),
    user: dict = Depends(get_current_user_or_token),
    db: Session = Depends(get_db),
):
    gs = load_graph(project_id, db)
    entities = gs["entities"]
    relationships = gs["relationships"]
    eid_name = {e["id"]: e["name"] for e in entities}
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    entity_rows = "".join(
        f"<tr><td>{e.get('name','')}</td><td>{e.get('type','')}</td>"
        f"<td>{e.get('confidence_score','?')}/10</td>"
        f"<td>{', '.join(f'{k}: {v}' for k, v in e.get('properties', {}).items())}</td>"
        f"<td>{e.get('source','')}</td></tr>\n"
        for e in sorted(entities, key=lambda x: x.get("type", ""))
    )

    rel_rows = "".join(
        f"<tr><td>{eid_name.get(r['from_id'], r['from_id'])}</td>"
        f"<td>{r.get('label', r.get('type',''))}</td>"
        f"<td>{eid_name.get(r['to_id'], r['to_id'])}</td>"
        f"<td>{r.get('confidence_score','?')}/10</td>"
        f"<td>{r.get('source','')}</td></tr>\n"
        for r in relationships
    )

    high = sum(1 for e in entities if e.get("confidence") == "high")
    med = sum(1 for e in entities if e.get("confidence") == "medium")
    low = sum(1 for e in entities if e.get("confidence") == "low")

    audit_rows = "".join(
        f"<tr><td>{a.get('timestamp','')}</td><td>{a.get('action','')}</td>"
        f"<td>{a.get('user','')}</td>"
        f"<td>{json.dumps(a.get('details', {}))[:120]}</td></tr>\n"
        for a in get_log(50)
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Forensic Graph Intelligence Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 40px; color: #222; font-size: 11px; }}
h1 {{ font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ font-size: 14px; margin-top: 24px; border-bottom: 1px solid #999; padding-bottom: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 10px; }}
th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; }}
th {{ background: #f0f0f0; font-weight: 600; }}
.summary {{ display: flex; gap: 20px; margin: 12px 0; }}
.summary div {{ padding: 8px 16px; border: 1px solid #ccc; border-radius: 4px; text-align: center; }}
.summary .val {{ font-size: 20px; font-weight: bold; }}
.summary .lbl {{ font-size: 9px; color: #666; text-transform: uppercase; }}
.footer {{ margin-top: 30px; font-size: 9px; color: #888; border-top: 1px solid #ccc; padding-top: 8px; }}
@media print {{ body {{ margin: 20px; }} }}
</style></head><body>
<h1>Forensic Graph Intelligence Report</h1>
<p>Generated: {ts}</p>
<div class="summary">
<div><div class="val">{len(entities)}</div><div class="lbl">Entities</div></div>
<div><div class="val">{len(relationships)}</div><div class="lbl">Relationships</div></div>
<div><div class="val">{high}</div><div class="lbl">High Confidence</div></div>
<div><div class="val">{med}</div><div class="lbl">Medium</div></div>
<div><div class="val">{low}</div><div class="lbl">Low / Review</div></div>
</div>
<h2>Entities ({len(entities)})</h2>
<table><tr><th>Name</th><th>Type</th><th>Score</th><th>Properties</th><th>Source</th></tr>
{entity_rows}</table>
<h2>Relationships ({len(relationships)})</h2>
<table><tr><th>From</th><th>Relationship</th><th>To</th><th>Score</th><th>Source</th></tr>
{rel_rows}</table>
<h2>Audit Log (last 50 entries)</h2>
<table><tr><th>Timestamp</th><th>Action</th><th>User</th><th>Details</th></tr>
{audit_rows}</table>
<div class="footer">
This report was generated by the Forensic Graph Intelligence system. All extractions include AI confidence scores (1-10).
Items with scores below 5 should be independently verified against source documents.
</div>
</body></html>"""

    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": 'inline; filename="forensic-report.html"'},
    )
