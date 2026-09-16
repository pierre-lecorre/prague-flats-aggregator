import json
import sqlite3
from datetime import datetime, timedelta
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
        ("listed_fees", "INTEGER"),
    ):
        _add_column(cursor, "listings", col, typedef)
    for col, typedef in (
        ("commute_a", "REAL"),
        ("commute_b", "REAL"),
        ("price", "INTEGER"),
        ("fee", "INTEGER"),
        ("total", "INTEGER"),
        ("fee_source", "TEXT"),
        ("is_reserved", "INTEGER DEFAULT 0"),
        ("is_unavailable", "INTEGER DEFAULT 0"),
        ("is_city_auction", "INTEGER DEFAULT 0"),
    ):
        _add_column(cursor, "evaluations", col, typedef)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            found INTEGER DEFAULT 0,
            inserted INTEGER DEFAULT 0,
            error TEXT
        )
    """)
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
         listed_at, bedrooms, district, json_data, listed_fees)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        listing.get("listed_fees"),
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
    listings = [dict(row) for row in rows]
    for listing in listings:
        if listing.get("listed_fees") is not None:
            continue
        raw = listing.get("json_data")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("listed_fees") is not None:
            listing["listed_fees"] = data["listed_fees"]
    return listings


def save_evaluation(
    listing_id: str,
    score: float,
    reasons: str,
    is_flatshare: bool,
    is_auction: bool,
    commute_minutes: Optional[float] = None,
    commute_a: Optional[float] = None,
    commute_b: Optional[float] = None,
    price: Optional[int] = None,
    fee: Optional[int] = None,
    total: Optional[int] = None,
    fee_source: Optional[str] = None,
    is_reserved: bool = False,
    is_unavailable: bool = False,
    is_city_auction: bool = False,
):
    conn = _connect()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    if commute_minutes is None and commute_a is not None:
        commute_minutes = commute_a
    cursor.execute("""
        INSERT INTO evaluations
        (listing_id, score, reasons, is_flatshare, is_auction, commute_minutes,
         commute_a, commute_b, price, fee, total, fee_source,
         is_reserved, is_unavailable, is_city_auction, evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing_id,
        score,
        reasons,
        1 if is_flatshare else 0,
        1 if is_auction else 0,
        commute_minutes,
        commute_a,
        commute_b,
        price,
        fee,
        total,
        fee_source,
        1 if is_reserved else 0,
        1 if is_unavailable else 0,
        1 if is_city_auction else 0,
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


LISTING_REQUIRED_FIELDS = (
    "title",
    "price",
    "url",
    "address",
    "description",
    "latitude",
    "longitude",
)


def listing_date(listing: Dict[str, Any]) -> Optional[str]:
    """Source last-edited/published time, else when we first stored the row."""
    return listing.get("listed_at") or listing.get("created_at")


def listing_date_source(listing: Dict[str, Any]) -> str:
    if listing.get("listed_at"):
        return "listed"
    return "added"


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def missing_fields(listing: Dict[str, Any], evaluation: Optional[Dict[str, Any]] = None) -> List[str]:
    missing = [name for name in LISTING_REQUIRED_FIELDS if _is_empty(listing.get(name))]
    if evaluation:
        for name in ("score", "fee", "total"):
            if evaluation.get(name) is None:
                missing.append(f"eval.{name}")
        reserved = bool(evaluation.get("is_reserved") or evaluation.get("is_unavailable"))
        score = evaluation.get("score") or 0
        if score and float(score) >= 60 and not reserved:
            if _is_empty(evaluation.get("commute_a")):
                missing.append("eval.commute_a")
            if _is_empty(evaluation.get("commute_b")):
                missing.append("eval.commute_b")
    return missing


def _parse_images(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [str(x) for x in data if x]
    return []


def _decorate_listing(row: Dict[str, Any]) -> Dict[str, Any]:
    listing = dict(row)
    listing["images"] = _parse_images(listing.get("images"))
    listing["listing_date"] = listing_date(listing)
    listing["listing_date_source"] = listing_date_source(listing)
    evaluation = {
        "score": listing.pop("eval_score", None),
        "reasons": listing.pop("eval_reasons", None),
        "is_flatshare": bool(listing.pop("eval_is_flatshare", 0)),
        "is_auction": bool(listing.pop("eval_is_auction", 0)),
        "is_city_auction": bool(listing.pop("eval_is_city_auction", 0)),
        "is_reserved": bool(listing.pop("eval_is_reserved", 0)),
        "is_unavailable": bool(listing.pop("eval_is_unavailable", 0)),
        "commute_a": listing.pop("eval_commute_a", None),
        "commute_b": listing.pop("eval_commute_b", None),
        "price": listing.pop("eval_price", listing.get("price")),
        "fee": listing.pop("eval_fee", None),
        "total": listing.pop("eval_total", None),
        "fee_source": listing.pop("eval_fee_source", None),
        "evaluated_at": listing.pop("eval_evaluated_at", None),
    }
    listing["evaluation"] = evaluation
    listing["missing_fields"] = missing_fields(listing, evaluation)
    return listing


_FLATS_SQL = """
    SELECT
        l.*,
        e.score AS eval_score,
        e.reasons AS eval_reasons,
        e.is_flatshare AS eval_is_flatshare,
        e.is_auction AS eval_is_auction,
        e.is_city_auction AS eval_is_city_auction,
        e.is_reserved AS eval_is_reserved,
        e.is_unavailable AS eval_is_unavailable,
        e.commute_a AS eval_commute_a,
        e.commute_b AS eval_commute_b,
        e.price AS eval_price,
        e.fee AS eval_fee,
        e.total AS eval_total,
        e.fee_source AS eval_fee_source,
        e.evaluated_at AS eval_evaluated_at
    FROM listings l
    LEFT JOIN evaluations e ON e.id = (
        SELECT id FROM evaluations
        WHERE listing_id = l.id
        ORDER BY evaluated_at DESC, id DESC
        LIMIT 1
    )
"""


def get_flats(limit: int = 200) -> List[Dict[str, Any]]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        _FLATS_SQL + " ORDER BY COALESCE(NULLIF(l.listed_at, ''), l.created_at) DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return [_decorate_listing(row) for row in rows]


def log_pipeline_run(
    source: str,
    found: int = 0,
    inserted: int = 0,
    error: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> None:
    conn = _connect()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        """
        INSERT INTO pipeline_runs
        (source, started_at, finished_at, found, inserted, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source, started_at or now, finished_at or now, found, inserted, error),
    )
    conn.commit()
    conn.close()


def get_pipeline_snapshot() -> Dict[str, Any]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS n FROM listings")
    listings_total = cursor.fetchone()["n"]
    cursor.execute("SELECT COUNT(*) AS n FROM listings WHERE is_active = 1")
    listings_active = cursor.fetchone()["n"]
    cursor.execute("SELECT COUNT(*) AS n FROM evaluations")
    evaluations_total = cursor.fetchone()["n"]
    cursor.execute(
        """
        SELECT COUNT(*) AS n FROM listings
        WHERE id NOT IN (SELECT listing_id FROM evaluations) AND is_active = 1
        """
    )
    unevaluated = cursor.fetchone()["n"]
    cursor.execute(
        """
        SELECT source, COUNT(*) AS n,
               MAX(created_at) AS last_added,
               MAX(listed_at) AS last_listed
        FROM listings
        GROUP BY source
        """
    )
    by_source = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT source, started_at, finished_at, found, inserted, error
        FROM pipeline_runs
        WHERE id IN (SELECT MAX(id) FROM pipeline_runs GROUP BY source)
        ORDER BY finished_at DESC
        """
    )
    last_runs = [dict(row) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT source, started_at, finished_at, found, inserted, error
        FROM pipeline_runs
        ORDER BY id DESC
        LIMIT 30
        """
    )
    recent_runs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    flats = get_flats(limit=500)
    field_counts: Dict[str, int] = {name: 0 for name in LISTING_REQUIRED_FIELDS}
    incomplete = []
    new_items = []
    generated_at = datetime.utcnow().isoformat()
    recent_cut = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    for flat in flats:
        missing = flat.get("missing_fields") or []
        for name in missing:
            field_counts[name] = field_counts.get(name, 0) + 1
        if missing:
            incomplete.append({
                "id": flat.get("id"),
                "source": flat.get("source"),
                "title": flat.get("title"),
                "url": flat.get("url"),
                "listing_date": flat.get("listing_date"),
                "listing_date_source": flat.get("listing_date_source"),
                "missing_fields": missing,
            })
        created = flat.get("created_at") or ""
        listed = flat.get("listing_date") or ""
        if created >= recent_cut or listed >= recent_cut:
            new_items.append({
                "id": flat.get("id"),
                "source": flat.get("source"),
                "title": flat.get("title"),
                "url": flat.get("url"),
                "listing_date": flat.get("listing_date"),
                "listing_date_source": flat.get("listing_date_source"),
                "created_at": flat.get("created_at"),
                "missing_fields": missing,
                "score": (flat.get("evaluation") or {}).get("score"),
                "is_reserved": (flat.get("evaluation") or {}).get("is_reserved"),
                "is_unavailable": (flat.get("evaluation") or {}).get("is_unavailable"),
            })

    return {
        "listings_total": listings_total,
        "listings_active": listings_active,
        "evaluations_total": evaluations_total,
        "unevaluated": unevaluated,
        "by_source": by_source,
        "last_runs": last_runs,
        "recent_runs": recent_runs,
        "empty_fields": field_counts,
        "incomplete": incomplete[:80],
        "incomplete_count": len(incomplete),
        "new_last_24h": new_items[:80],
        "new_last_24h_count": len(new_items),
        "generated_at": generated_at,
    }
