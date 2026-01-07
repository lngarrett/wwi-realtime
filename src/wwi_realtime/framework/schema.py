"""Database schema for WWI Story Engine.

This module defines the schema for:
- arcs: Narrative arcs from Wikipedia campaign structure
- canonical_sources: Curated primary sources (memoirs, diaries, letters)
- source_coverage: What arcs/events each source covers
- source_passages: Parsed passages from sources with FTS index

The existing events table is extended with arc_id foreign key.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2  # Increment when schema changes

# New tables for story engine
STORY_ENGINE_SCHEMA = """
-- Narrative arcs from Wikipedia campaign structure
CREATE TABLE IF NOT EXISTS arcs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    parent_arc_id TEXT,
    start_date DATE,
    end_date DATE,
    wikipedia_url TEXT,
    narrative_summary TEXT,
    significance TEXT,
    theater TEXT,  -- 'western_front', 'eastern_front', 'gallipoli', etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_arc_id) REFERENCES arcs(id)
);

CREATE INDEX IF NOT EXISTS idx_arcs_parent ON arcs(parent_arc_id);
CREATE INDEX IF NOT EXISTS idx_arcs_dates ON arcs(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_arcs_theater ON arcs(theater);

-- Curated canonical primary sources
CREATE TABLE IF NOT EXISTS canonical_sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    author_info TEXT,
    type TEXT,  -- 'memoir', 'diary', 'letters', 'poetry', 'journalism'
    perspective TEXT,  -- 'german', 'british', 'french', 'american', 'australian', etc.
    gutenberg_id TEXT,
    internet_archive_id TEXT,
    source_url TEXT,
    publication_year INTEGER,
    available BOOLEAN DEFAULT FALSE,
    ingested BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 5,  -- 1 = highest priority
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sources_available ON canonical_sources(available);
CREATE INDEX IF NOT EXISTS idx_sources_ingested ON canonical_sources(ingested);
CREATE INDEX IF NOT EXISTS idx_sources_priority ON canonical_sources(priority);

-- Source coverage: what arcs/events each source covers
CREATE TABLE IF NOT EXISTS source_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    arc_id TEXT,
    event_id TEXT,
    topic TEXT,  -- 'trench_warfare', 'artillery', 'gas_attacks', etc.
    relevance_score REAL DEFAULT 1.0,
    notes TEXT,
    FOREIGN KEY (source_id) REFERENCES canonical_sources(id),
    FOREIGN KEY (arc_id) REFERENCES arcs(id)
);

CREATE INDEX IF NOT EXISTS idx_coverage_source ON source_coverage(source_id);
CREATE INDEX IF NOT EXISTS idx_coverage_arc ON source_coverage(arc_id);
CREATE INDEX IF NOT EXISTS idx_coverage_event ON source_coverage(event_id);
CREATE INDEX IF NOT EXISTS idx_coverage_topic ON source_coverage(topic);

-- Parsed passages from sources
CREATE TABLE IF NOT EXISTS source_passages (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    content TEXT NOT NULL,
    page_or_chapter TEXT,
    sequence_num INTEGER,  -- order within source
    date_referenced DATE,
    date_approximate TEXT,  -- "August 1914", "during the Somme"
    has_direct_quote BOOLEAN DEFAULT FALSE,
    topics TEXT,  -- JSON array
    word_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES canonical_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_passages_source ON source_passages(source_id);
CREATE INDEX IF NOT EXISTS idx_passages_date ON source_passages(date_referenced);
CREATE INDEX IF NOT EXISTS idx_passages_quote ON source_passages(has_direct_quote);

-- Full-text search index for passages
CREATE VIRTUAL TABLE IF NOT EXISTS source_passages_fts USING fts5(
    content,
    topics,
    date_approximate,
    content=source_passages,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON source_passages BEGIN
    INSERT INTO source_passages_fts(rowid, content, topics, date_approximate)
    VALUES (NEW.rowid, NEW.content, NEW.topics, NEW.date_approximate);
END;

CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON source_passages BEGIN
    INSERT INTO source_passages_fts(source_passages_fts, rowid, content, topics, date_approximate)
    VALUES ('delete', OLD.rowid, OLD.content, OLD.topics, OLD.date_approximate);
END;

CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON source_passages BEGIN
    INSERT INTO source_passages_fts(source_passages_fts, rowid, content, topics, date_approximate)
    VALUES ('delete', OLD.rowid, OLD.content, OLD.topics, OLD.date_approximate);
    INSERT INTO source_passages_fts(rowid, content, topics, date_approximate)
    VALUES (NEW.rowid, NEW.content, NEW.topics, NEW.date_approximate);
END;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Migration to add arc_id to existing events table
EVENTS_MIGRATION = """
-- Add arc_id column to events if not exists
ALTER TABLE events ADD COLUMN arc_id TEXT REFERENCES arcs(id);
"""


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a database connection with proper settings."""
    if db_path is None:
        db_path = Path("data/events.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all story engine tables and indexes."""
    conn.executescript(STORY_ENGINE_SCHEMA)

    # Check if we need to migrate events table
    cursor = conn.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cursor.fetchall()}

    if "arc_id" not in columns:
        try:
            conn.execute(EVENTS_MIGRATION)
        except sqlite3.OperationalError:
            pass  # Column might already exist

    # Record schema version
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
        (SCHEMA_VERSION,)
    )
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version, or 0 if not versioned."""
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def verify_schema(conn: sqlite3.Connection) -> dict:
    """Verify all expected tables exist and return stats."""
    tables = {
        "arcs": 0,
        "canonical_sources": 0,
        "source_coverage": 0,
        "source_passages": 0,
        "source_passages_fts": 0,
        "events": 0,
    }

    for table in tables:
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            tables[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            tables[table] = -1  # Table doesn't exist

    return {
        "version": get_schema_version(conn),
        "tables": tables,
        "all_exist": all(v >= 0 for v in tables.values()),
    }
