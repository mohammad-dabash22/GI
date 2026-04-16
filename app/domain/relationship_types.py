"""Relationship type definitions and visual styles for the graph."""

RELATIONSHIP_TYPES = [
    "owns", "works_for", "related_to", "transferred_money_to", "communicated_with",
    "located_at", "associated_with", "controls", "registered_to", "paid_by",
    "met_with", "traveled_to", "signed", "witnessed", "received_from",
    "shareholder_of", "board_member_of", "family", "referred_by", "financed",
    "sold_shares_to", "trades_with", "managed_by", "ceo_of", "director_of",
]

EDGE_STYLES = {
    # Money flows -- red family, thick, particles
    "transferred_money_to": {"color": "#E74C3C", "width": 3,   "dashes": False, "particles": 4},
    "paid_by":              {"color": "#E55B5B", "width": 2.5, "dashes": False, "particles": 3},
    "received_from":        {"color": "#D94040", "width": 2.5, "dashes": False, "particles": 3},
    "financed":             {"color": "#C0392B", "width": 3,   "dashes": False, "particles": 3},
    # Ownership / control -- green family
    "owns":                 {"color": "#27AE60", "width": 2.5, "dashes": False, "particles": 0},
    "controls":             {"color": "#2ECC71", "width": 2.5, "dashes": False, "particles": 0},
    "shareholder_of":       {"color": "#1E8449", "width": 2.5, "dashes": False, "particles": 0},
    "sold_shares_to":       {"color": "#52BE80", "width": 2,   "dashes": False, "particles": 0},
    # Employment / roles -- blue family, each distinct
    "works_for":            {"color": "#5B8DEF", "width": 2,   "dashes": False, "particles": 0},
    "ceo_of":               {"color": "#3A6FD8", "width": 2.5, "dashes": False, "particles": 0},
    "director_of":          {"color": "#4A7FE8", "width": 2,   "dashes": False, "particles": 0},
    "board_member_of":      {"color": "#6E9EF5", "width": 2,   "dashes": False, "particles": 0},
    "managed_by":           {"color": "#85B0F7", "width": 1.5, "dashes": False, "particles": 0},
    # Communication -- purple family, dashed
    "communicated_with":    {"color": "#9B59B6", "width": 2,   "dashes": True,  "particles": 2},
    "met_with":             {"color": "#AF7AC5", "width": 1.5, "dashes": True,  "particles": 0},
    "family":               {"color": "#8E44AD", "width": 2,   "dashes": True,  "particles": 0},
    # Location / registration -- teal/brown, thin dashed
    "located_at":           {"color": "#1ABC9C", "width": 1.5, "dashes": True,  "particles": 0},
    "traveled_to":          {"color": "#16A085", "width": 1.5, "dashes": False, "particles": 0},
    "registered_to":        {"color": "#48C9B0", "width": 1.5, "dashes": False, "particles": 0},
    # Documents / legal -- indigo
    "signed":               {"color": "#6C7AE0", "width": 1.5, "dashes": False, "particles": 0},
    "witnessed":            {"color": "#7D8BE8", "width": 1,   "dashes": True,  "particles": 0},
    # Trade / commerce -- pink
    "trades_with":          {"color": "#E84393", "width": 2,   "dashes": False, "particles": 2},
    # Weak / generic -- grey, thin dashed
    "related_to":           {"color": "#888888", "width": 1,   "dashes": True,  "particles": 0},
    "associated_with":      {"color": "#999999", "width": 1,   "dashes": True,  "particles": 0},
    "referred_by":          {"color": "#777777", "width": 1,   "dashes": True,  "particles": 0},
}

DEFAULT_EDGE_STYLE = {"color": "#888888", "width": 1, "dashes": True, "particles": 0}

# Semantic groupings for importance-based rendering
MONEY_TYPES = {"transferred_money_to", "paid_by", "received_from", "financed"}
CONTROL_TYPES = {"owns", "controls", "shareholder_of", "sold_shares_to", "ceo_of", "director_of"}
WEAK_TYPES = {"related_to", "associated_with", "referred_by"}
