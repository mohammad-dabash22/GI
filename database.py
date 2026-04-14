from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()


def _migrate_add_columns():
    from sqlalchemy import text, inspect
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
