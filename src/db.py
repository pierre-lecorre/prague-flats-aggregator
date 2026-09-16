import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
import json

DB_PATH = "flats.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()

def listing_exists(listing_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def insert_listing(listing: Dict[str, Any]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO listings 
        (id, source, title, price, size_m2, address, url, description, images, latitude, longitude, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        1
    ))
    conn.commit()
    conn.close()

def get_new_listings() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
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

def save_evaluation(listing_id: str, score: float, reasons: str, 
                    is_flatshare: bool, is_auction: bool, commute_minutes: Optional[float]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO evaluations 
        (listing_id, score, reasons, is_flatshare, is_auction, commute_minutes, evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (listing_id, score, reasons, 1 if is_flatshare else 0, 
            1 if is_auction else 0, commute_minutes, now))
    conn.commit()
    conn.close()

def mark_listing_inactive(listing_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE listings SET is_active = 0, updated_at = ? WHERE id = ?", 
                   (datetime.utcnow().isoformat(), listing_id))
    conn.commit()
    conn.close()