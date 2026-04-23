"""Entity type definitions and visual styles for the graph."""

ENTITY_TYPES = [
    "Person", "Organization", "Account", "Phone", "Address",
    "Vehicle", "Email", "MoneyTransfer", "Event", "Location",
    "SocialMediaAccount",
]

ENTITY_STYLES = {
    "Person":        {"color": "#5B8DEF", "shape": "dot",          "size": 25, "emoji": "\U0001F464"},
    "Organization":  {"color": "#F5A623", "shape": "diamond",      "size": 25, "emoji": "\U0001F3E2"},
    "Account":       {"color": "#7ED321", "shape": "square",       "size": 20, "emoji": "\U0001F4B3"},
    "Phone":         {"color": "#BD10E0", "shape": "triangle",     "size": 20, "emoji": "\U0001F4DE"},
    "Address":       {"color": "#A0785A", "shape": "square",       "size": 18, "emoji": "\U0001F4CD"},
    "Vehicle":       {"color": "#6B7C8A", "shape": "triangle",     "size": 20, "emoji": "\U0001F697"},
    "Email":         {"color": "#4FC1E9", "shape": "dot",          "size": 18, "emoji": "\u2709"},
    "MoneyTransfer": {"color": "#ED5565", "shape": "star",         "size": 22, "emoji": "\U0001F4B5"},
    "Event":         {"color": "#E84393", "shape": "diamond",      "size": 20, "emoji": "\U0001F4C5"},
    "Location":             {"color": "#00B894", "shape": "triangleDown", "size": 20, "emoji": "\U0001F30D"},
    "SocialMediaAccount": {"color": "#1DA1F2", "shape": "dot",          "size": 20, "emoji": "\U0001F4F1"},
}

DEFAULT_NODE_STYLE = ENTITY_STYLES["Person"]
