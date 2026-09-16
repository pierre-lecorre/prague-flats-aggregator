import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = str(Path(__file__).resolve().parent.parent / "flats.db")


def _connect():
    return sqlite3.connect(DB_PATH)


def _add_column(cursor, table: str, col: str, typedef: str) -> None:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except sqlite3.OperationalError:
        pass


def init_db():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            price INTEGER,
            size_m2 REAL,
            address TEXT,
            url TEXT UNIQUE NOT NULL,
            description TEXT,
            images TEXT,
            latitude REAL,
            longitude REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            score REAL,
            reasons TEXT,
            is_flatshare INTEGER DEFAULT 0,
            is_auction INTEGER DEFAULT 0,
            commute_minutes REAL,
            evaluated_at TEXT NOT NULL,
            FOREIGN KEY (listing_id) REFERENCES listings(id)
        )
    """)
    for col, typedef in (
        ("listed_at", "TEXT"),
        ("bedrooms", "INTEGER"),
        ("district", "TEXT"),
        ("json_data", "TEXT"),
    ):
        _add_column(cursor, "listings", col, typedef)
    for col, typedef in (
        ("commute_a", "REAL"),
        ("commute_b", "REAL"),
    ):
        _add_column(cursor, "evaluations", col, typedef)
    conn.commit()
    conn.close()


def listing_exists(listing_id: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def insert_listing(listing: Dict[str, Any]):
    conn = _connect()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO listings
        (id, source, title, price, size_m2, address, url, description, images,
         latitude, longitude, created_at, updated_at, is_active,
         listed_at, bedrooms, district, json_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing["id"],
        listing["source"],
        listing.get("title"),
        listing.get("price"),
        listing.get("size_m2"),
        listing.get("address"),
        listing["url"],
        listing.get("description", ""),
        json.dumps(listing.get("images", [])),
        listing.get("latitude"),
        listing.get("longitude"),
        now,
        now,
        1,
        listing.get("listed_at"),
        listing.get("bedrooms"),
        listing.get("district"),
        json.dumps(listing, ensure_ascii=False, default=str),
    ))
    conn.commit()
    conn.close()


def get_new_listings() -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM listings
        WHERE id NOT IN (SELECT listing_id FROM evaluations)
        AND is_active = 1
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_evaluation(
    listing_id: str,
    score: float,
    reasons: str,
    is_flatshare: bool,
    is_auction: bool,
    commute_minutes: Optional[float] = None,
    commute_a: Optional[float] = None,
    commute_b: Optional[float] = None,
):
    conn = _connect()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    if commute_minutes is None and commute_a is not None:
        commute_minutes = commute_a
    cursor.execute("""
        INSERT INTO evaluations
        (listing_id, score, reasons, is_flatshare, is_auction, commute_minutes,
         commute_a, commute_b, evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing_id,
        score,
        reasons,
        1 if is_flatshare else 0,
        1 if is_auction else 0,
        commute_minutes,
        commute_a,
        commute_b,
        now,
    ))
    conn.commit()
    conn.close()


def mark_listing_inactive(listing_id: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE listings SET is_active = 0, updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), listing_id),
    )
    conn.commit()
    conn.close()
