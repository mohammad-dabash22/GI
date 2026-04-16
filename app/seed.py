"""Demo data for seeding a test project on first startup."""

# Moved from root seed_data.py — content preserved exactly.
# This is imported by app/main.py during startup.

from seed_data import get_demo_entities, get_demo_relationships

__all__ = ["get_demo_entities", "get_demo_relationships"]
