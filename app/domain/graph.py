"""Typed value object for graph state, replacing raw dicts."""

from dataclasses import dataclass, field


@dataclass
class GraphState:
    """Immutable snapshot of a project's graph data.

    Replaces the raw dicts previously returned by load_graph().
    """
    entities: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    positions: dict = field(default_factory=dict)
    rejected_items: list[dict] = field(default_factory=list)
