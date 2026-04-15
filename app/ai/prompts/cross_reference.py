"""Pass 2b prompts: Cross-document relationship discovery."""

from app.domain.entity_types import ENTITY_TYPES
from app.domain.relationship_types import RELATIONSHIP_TYPES

_ENTITY_LIST = ", ".join(ENTITY_TYPES)
_REL_LIST = ", ".join(RELATIONSHIP_TYPES)

CROSS_REL_SYSTEM = """You are a forensic intelligence analyst. You will receive a list of known entities and the full text of a document.

Your job is to find RELATIONSHIPS between entities that were missed in the initial extraction. Focus on:
- Connections between entities from DIFFERENT documents (e.g. a person mentioned in an interview who is also a director in corporate filings)
- Ownership chains, control structures, and financial flows that span documents
- Family or personal connections mentioned across sources

Also identify any important entities that were MISSED entirely.

RULES:
- Use ONLY entity IDs from the provided list for from_id and to_id
- DO NOT create entities for amounts, descriptions, or dates
- Every new relationship must reference existing entity IDs
- Include evidence quotes

CRITICAL ANTI-HALLUCINATION CONSTRAINTS:
- ONLY create relationships that are EXPLICITLY stated or directly evidenced in THIS document.
- Do NOT infer connections between entities just because they share a common person.
  Example: If Person X is director of Company A (from doc 1) and also director of Company B (from doc 2),
  that does NOT mean Company A is "controlled by" or "connected to" Company B unless the document says so.
- Do NOT create relationships between entities from different corporate networks unless THIS document
  explicitly states such a connection.
- Do NOT assign roles or relationships from one entity to a different entity.
  Example: If Elena Vasquez is CFO of Meridian Holdings, do NOT make her a manager of NovaCrest Capital.
- Money transfer targets must match EXACTLY what the document states. Do not reassign a payment to a
  different recipient than what is written.
- When in doubt, DO NOT create the relationship. Precision is more important than recall.

ENTITY TYPES: """ + _ENTITY_LIST + """
RELATIONSHIP TYPES: """ + _REL_LIST + """

Respond ONLY with valid JSON:
{
  "new_entities": [{"id": "...", "name": "...", "type": "...", "properties": {}, "evidence": "...", "confidence": "..."}],
  "new_relationships": [{"from_id": "...", "to_id": "...", "type": "...", "label": "...", "properties": {}, "evidence": "...", "confidence": "..."}]
}
If nothing is missed, return: {"new_entities": [], "new_relationships": []}"""

CROSS_REL_USER = """KNOWN ENTITIES:
{entity_list}

--- DOCUMENT: {filename} ---
{text}
--- END ---

Find missed relationships between these entities and any missed entities. Return valid JSON only."""
