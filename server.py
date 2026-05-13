"""
Travel form backend.
Run:  uvicorn server:app --reload --port 8000
Then open: http://localhost:8000
Admin:     http://localhost:8000/admin  (password-protected)
"""

import json
import os
import secrets
import sqlite3
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

HERE = Path(__file__).parent
REGIONS_FILE = HERE / "regions.json"

# On Railway set DATA_DIR to the mounted volume path (e.g. /data)
DATA_DIR = Path(os.environ.get("DATA_DIR", str(HERE)))
DB_FILE = DATA_DIR / "responses.db"

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "dwb2025")

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
security = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(creds.username, ADMIN_USER) and \
         secrets.compare_digest(creds.password, ADMIN_PASS)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def get_db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT,
            home_region  TEXT NOT NULL,
            visited      TEXT NOT NULL,
            submitted_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()


init_db()


class Submission(BaseModel):
    name: Optional[str] = None
    home_region: str
    visited_regions: List[str]


# ── public endpoints ──────────────────────────────────────────────────────────

@app.get("/regions")
def regions():
    data = json.loads(REGIONS_FILE.read_text())
    return [{"id": r["id"], "name": r["name"]} for r in data]


@app.post("/submit")
def submit(s: Submission):
    if not s.home_region or not s.visited_regions:
        return JSONResponse({"ok": False, "error": "Missing fields"}, status_code=400)
    con = get_db()
    con.execute(
        "INSERT INTO submissions (name, home_region, visited) VALUES (?,?,?)",
        (s.name or None, s.home_region, json.dumps(s.visited_regions)),
    )
    con.commit()
    con.close()
    return {"ok": True}


# ── admin endpoints ───────────────────────────────────────────────────────────

@app.get("/admin", dependencies=[Depends(require_admin)])
def admin_page():
    return FileResponse(HERE / "admin.html")


@app.get("/admin/data", dependencies=[Depends(require_admin)])
def admin_data():
    con = get_db()
    rows = con.execute(
        "SELECT id, name, home_region, visited, submitted_at FROM submissions ORDER BY id DESC"
    ).fetchall()
    total = len(rows)
    con.close()

    region_counts: dict = {}
    submissions = []
    for row in rows:
        visited = json.loads(row["visited"])
        for r in [row["home_region"]] + visited:
            region_counts[r] = region_counts.get(r, 0) + 1
        submissions.append({
            "id": row["id"],
            "name": row["name"] or "—",
            "home_region": row["home_region"],
            "visited": visited,
            "submitted_at": row["submitted_at"],
        })

    top_regions = sorted(region_counts.items(), key=lambda x: -x[1])[:15]
    return {
        "total": total,
        "submissions": submissions,
        "top_regions": [{"name": n, "count": c} for n, c in top_regions],
    }


@app.get("/admin/export", dependencies=[Depends(require_admin)])
def admin_export():
    """TRAVELERS array ready to paste into regions.js."""
    regions = json.loads(REGIONS_FILE.read_text())
    region_id = {r["name"]: r["id"] for r in regions}

    con = get_db()
    rows = con.execute("SELECT id, home_region, visited FROM submissions").fetchall()
    con.close()

    travelers = []
    for row in rows:
        home_id = region_id.get(row["home_region"])
        vis_ids = [region_id[v] for v in json.loads(row["visited"]) if v in region_id]
        if home_id and vis_ids:
            travelers.append({
                "person_id": row["id"],
                "home_region_id": home_id,
                "visited_region_ids": vis_ids,
            })
    return travelers


app.mount("/", StaticFiles(directory=str(HERE), html=True), name="static")
