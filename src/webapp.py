#!/usr/bin/env python3
"""Localhost dashboard: flats + pipeline monitoring."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from flask import Flask, jsonify, send_from_directory

from config import MIN_SCORE, POINT_A_NAME, POINT_B_NAME, WEB_HOST, WEB_PORT
from db import get_flats, get_pipeline_snapshot, init_db

WEB_DIR = SRC / "web"
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/flats")
def api_flats():
    init_db()
    return jsonify(
        {
            "flats": get_flats(limit=400),
            "min_score": MIN_SCORE,
            "point_a": POINT_A_NAME,
            "point_b": POINT_B_NAME,
        }
    )


@app.get("/api/pipeline")
def api_pipeline():
    init_db()
    return jsonify(get_pipeline_snapshot())


if __name__ == "__main__":
    init_db()
    print(f"Dashboard http://{WEB_HOST}:{WEB_PORT}", flush=True)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
