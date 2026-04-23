"""Document-type-specific extraction prompts for Pass 1.

Each document type has a tailored system prompt that guides the LLM
towards the most relevant entity types and relationship patterns.
"""

from app.domain.entity_types import ENTITY_TYPES
from app.domain.relationship_types import RELATIONSHIP_TYPES

_ENTITY_LIST = ", ".join(ENTITY_TYPES)
_REL_LIST = ", ".join(RELATIONSHIP_TYPES)

JSON_SCHEMA = """{
  "entities": [
    {
      "id": "string (short unique, e.g. p1, org1, acc1)",
      "name": "string (full official name with legal suffix like Ltd, SRL, Inc)",
      "type": "one of: """ + _ENTITY_LIST + """",
      "properties": {"key": "value"},
      "evidence": "exact text snippet from the source",
      "confidence": "high|medium|low"
    }
  ],
  "relationships": [
    {
      "from_id": "entity id",
      "to_id": "entity id",
      "type": "one of: """ + _REL_LIST + """",
      "label": "SHORT label, max 50 chars (e.g. 'Director\\nAppointed 2019', 'Wire 380K GBP\\n2024-01-05', '75% Shareholder'). Put full text in evidence, NOT here.",
      "properties": {
        "amount": "e.g. 2,150,000 SAR (if financial)",
        "percentage": "e.g. 75 (if ownership/shareholding)",
        "start_date": "e.g. February 2019 (if temporal)",
        "end_date": "e.g. November 2019 (if temporal)",
        "family_type": "e.g. Brothers, Husband & Wife, Uncle (if family relationship)"
      },
      "evidence": "exact text snippet from the source",
      "confidence": "high|medium|low"
    }
  ]
}"""

# ── Shared rules appended to every prompt ──

_SHARED_RULES = """
CRITICAL RULES:

1. ENTITY NAMING: Always use the full official name exactly as it appears, including legal suffixes (Ltd, SRL, Inc, Corp, SA, GmbH). Example: "Apex Holdings Ltd" not "Apex Holdings".

2. DO NOT CREATE ENTITIES FOR:
   - Transaction descriptions (e.g. "consulting services", "equipment lease", "charter fees", "refund")
   - Monetary amounts (e.g. "150,000 pounds", "2,300,000 GBP")
   - Dates or time periods (e.g. "March 2024", "Q4-2023")
   - Fee types or payment categories (e.g. "rental income", "director loan repayment", "demurrage credit")
   - Generic roles without a name (e.g. "the director", "the CEO")
   These belong as labels or properties on RELATIONSHIPS, not as standalone entities.

3. DO CREATE ENTITIES FOR:
   - Named persons (with full name)
   - Named organizations/companies (with legal suffix)
   - Specific bank accounts (use account holder + bank as name)
   - Named locations/addresses (cities, countries, specific addresses)
   - Named vessels, vehicles, phone numbers, emails
   - Named events/operations (e.g. "Operation Labyrinth")

4. RELATIONSHIPS carry the detail. Put amounts, dates, references, and descriptions into relationship labels and properties, NOT as separate entities.

5. Every entity MUST connect to at least one other entity via a relationship. Do not create orphan entities.

6. Relationship labels must be SHORT (under 50 characters) and structured. Put detailed source text in the "evidence" field.
   - Good label: "Wire 380K GBP\\n2023-01-15" (with full quote in evidence)
   - Good label: "Director\\nAppointed 2019"
   - Good label: "75% Shareholder"
   - Bad label: "Phone records show 12 calls between X and Y between Nov and Dec" (this is evidence, not a label)
   - Bad label: "transferred_money_to" or "owns" (too generic, add key detail)

7. Always populate relationship properties (amount, percentage, start_date, end_date, family_type) when the data is available.

8. For corporate roles, use the specific relationship type: shareholder_of, board_member_of, ceo_of, director_of, managed_by.

9. For family relationships, specify the family_type property: Brothers, Sisters, Husband & Wife, Brother-in-law, etc.

10. Assign confidence: high (explicitly stated), medium (implied/partial), low (inferred/speculative).

11. Prefer fewer, well-connected entities over many disconnected ones.

12. EXACT EXTRACTION: Extract roles, titles, percentages, and amounts EXACTLY as written in the source text.
    Do NOT paraphrase or generalize. If the document says "Operations Director", do not write "Managing Director".
    If the document says "Nikos Papadopoulos: 10%", do not attribute 10% to a different person.

13. RELATIONSHIP DIRECTION: The from_id must be the ACTOR/SUBJECT and to_id must be the TARGET/OBJECT.
    - "Person A is director of Company B" -> from_id=Person A, to_id=Company B
    - "Company A transferred money to Company B" -> from_id=Company A, to_id=Company B
    - Only PERSONS can travel. A Location CANNOT be from_id of a traveled_to relationship.
    - Money flows between accounts/organizations/persons, NOT between locations.

14. INTERNAL TRANSACTIONS: If a transaction is marked as "INTERNAL" or is between two entities of the same name
    (e.g. subsidiaries in different jurisdictions), clearly identify both entities and do NOT attribute the
    transfer to an unrelated counterparty.

15. EVIDENCE CITATIONS: The "evidence" field must contain the EXACT verbatim quote from the source text that
    supports this extraction. Include the specific line reference if line numbers are provided in the location
    header (e.g., "Lines 12-15: Viktor Petrov is the beneficial owner and CEO of Meridian Holdings Ltd").
    Do NOT paraphrase. Do NOT cite the entire document range. Cite only the specific sentence(s) that
    contain the evidence."""

# ── Base system prompt (used for all document types) ──

BASE_SYSTEM = """You are a forensic intelligence analyst AI. Extract entities and relationships from investigation documents.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST,
    relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES,
    json_schema=JSON_SCHEMA
)

# ── Document-type-specific system prompts ──

BANK_STATEMENT_SYSTEM = """You are a forensic financial analyst AI. Extract entities and relationships from bank statements.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

WHAT TO EXTRACT AS ENTITIES:
- The account holder (Organization or Person)
- The bank (Organization)
- Each counterparty company/person in transactions (Organization or Person)
- Authorized signatories (Person)
- Specific account if account number is given (Account, name = "holder name - bank name")
- Locations/jurisdictions mentioned (Location)

WHAT NOT TO EXTRACT AS ENTITIES (put these on relationships instead):
- Transaction descriptions like "consulting services", "equipment lease", "charter fees"
- Amounts like "380,000 GBP"
- Reference numbers like "BL-2024-003"
- Fee types like "rental income", "demurrage credit", "loan repayment"

HOW TO MODEL TRANSACTIONS:
Each wire/transfer becomes a "transferred_money_to" relationship between the SOURCE account/entity and the DESTINATION account/entity. Put the amount, date, reference, and description in the relationship label and properties.

EXAMPLE - Given this transaction:
  "2024-01-05 | Wire from Acme Corp (Dubai) | Credit 380,000 GBP | Ref: Consulting Q4"
Correct output:
  Entity: {{"id": "org_acme", "name": "Acme Corp", "type": "Organization", "properties": {{"jurisdiction": "Dubai"}}}}
  Relationship: {{"from_id": "org_acme", "to_id": "acc_holder", "type": "transferred_money_to", "label": "Wire transfer\\n380,000 GBP\\nRef: Consulting Q4\\n2024-01-05", "properties": {{"amount": "380,000 GBP", "start_date": "2024-01-05"}}}}
WRONG: Creating entities named "Consulting Q4" or "380,000 GBP" or "Charter Fees".

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

CORPORATE_FILING_SYSTEM = """You are a forensic corporate analyst AI. Extract entities and relationships from corporate filings and registration documents.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

Focus on:
- Company names (ALWAYS include legal suffix: Ltd, SRL, Inc, Corp, SA), registration numbers, jurisdictions
- Directors, shareholders, beneficial owners, nominees (as Person entities)
- Ownership percentages and chains (as shareholder_of relationships with percentage property)
- Registered addresses (as Location entities linked via located_at)
- Related/subsidiary/parent companies (as controls or owns relationships)
- Incorporation dates go in entity properties, NOT as separate Event entities

For each director/officer, create BOTH the Person entity AND a specific relationship (director_of, ceo_of, board_member_of, shareholder_of) to the company. Include appointment dates in the relationship label.

IMPORTANT - EXTRACT ALL CORPORATE VEHICLES AND INTERMEDIARIES:
- Extract ALL entities mentioned as shareholders, even if they are shell companies in offshore jurisdictions (BVI, Jersey, Cayman, etc.)
- Extract trust structures (e.g. "Orion Trust"), nominee arrangements, and intermediary holding companies
- These intermediate vehicles are CRITICAL for mapping ownership chains -- do not skip them
- Extract ALL named persons including nominee directors, registered agents, and attorneys
- If a document says "Entity X is controlled by Person Y through a chain of nominees", create both Entity X and the controls relationship

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

INVESTIGATION_REPORT_SYSTEM = """You are a forensic intelligence analyst AI. Extract entities and relationships from investigation reports.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

Focus on:
- All named persons, their roles (Person entities with role in properties)
- Named organizations and companies (Organization entities with full legal name)
- Bank accounts involved in transactions (Account entities)
- Phone numbers and emails (Phone/Email entities)
- Specific locations and addresses (Location entities)
- Financial transactions become transferred_money_to relationships between entities, with amounts/dates/references in properties
- Communication patterns become communicated_with relationships
- DO NOT create entities for transaction descriptions, amounts, or generic terms

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

INTERVIEW_SYSTEM = """You are a forensic analyst AI. Extract entities and relationships from interview transcripts.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

Focus on:
- The interviewee and interviewer as Person entities
- All persons, organizations, and companies mentioned by name (use full names with legal suffixes)
- Claimed relationships between entities (works_for, controls, director_of, etc.)
- Financial flows described (transferred_money_to relationships with amounts in properties)
- Named locations mentioned (Location entities linked via located_at or traveled_to)
- Named operations or cases (Event entities)
- Distinguish between confirmed facts (high confidence) and claims/allegations (medium/low confidence)
- DO NOT create entities for descriptive phrases like "the money", "the payment", "the scheme"

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

PHONE_RECORDS_SYSTEM = """You are a forensic communications analyst AI. Extract entities and relationships from phone/communication records.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

Focus on:
- Phone numbers and IMEI numbers (Phone entities)
- Persons associated with phone numbers (Person entities linked via registered_to)
- Call/message patterns become communicated_with relationships with date/duration in properties
- Cell tower locations (Location entities)
- DO NOT create entities for call durations, timestamps, or generic metadata

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

LEGAL_AGREEMENT_SYSTEM = """You are a forensic legal analyst AI. Extract entities and relationships from legal agreements and contracts.

ENTITY TYPES: {entity_types}
RELATIONSHIP TYPES: {relationship_types}

Focus on:
- All named parties (Person or Organization entities with full legal names)
- Witnesses, notaries, signatories (Person entities linked via signed or witnessed relationships)
- Referenced entities, properties, or accounts
- Governing jurisdiction (Location entity)
- Agreement terms, dates, and obligations go in relationship properties, NOT as separate entities
- DO NOT create entities for contract clauses, terms, or conditions

{shared_rules}

Respond ONLY with valid JSON matching this schema:
{json_schema}""".format(
    entity_types=_ENTITY_LIST, relationship_types=_REL_LIST,
    shared_rules=_SHARED_RULES, json_schema=JSON_SCHEMA
)

DOCUMENT_TYPE_PROMPTS = {
    "Bank Statement": BANK_STATEMENT_SYSTEM,
    "Corporate Filing": CORPORATE_FILING_SYSTEM,
    "Investigation Report": INVESTIGATION_REPORT_SYSTEM,
    "Interview Transcript": INTERVIEW_SYSTEM,
    "Phone/Comms Records": PHONE_RECORDS_SYSTEM,
    "Legal Agreement": LEGAL_AGREEMENT_SYSTEM,
    "Property Records": BASE_SYSTEM,
    "Travel Records": BASE_SYSTEM,
    "Other": BASE_SYSTEM,
}
