"""Database initialization and schema migrations.

Separated from models/base.py to avoid circular imports:
models define tables, this module creates them.
"""

from sqlalchemy import text, inspect

from app.models.base import engine, Base
# Import all models so Base.metadata knows about them
from app.models import User, Project, GraphSnapshot, DocumentRecord  # noqa: F401


def init_db():
    """Create all tables and run any pending migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()


def _migrate_add_columns():
    """Add columns that were introduced after initial schema."""
    insp = inspect(engine)
    if "graph_snapshots" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("graph_snapshots")]
        if "node_positions" not in cols:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE graph_snapshots ADD COLUMN node_positions TEXT DEFAULT "{}"'))
                print("[MIGRATE] Added node_positions column to graph_snapshots")
        if "rejected_items" not in cols:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE graph_snapshots ADD COLUMN rejected_items TEXT DEFAULT "[]"'))
                print("[MIGRATE] Added rejected_items column to graph_snapshots")
