"""Outcome logging, bandit weights, pause rules, HITL escalation."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.catalog import load_policies

DB_PATH = Path(__file__).parent.parent / "data" / "outcomes.db"

_escalation_queue: list[dict] = []
_spend_today: float = 0.0
_served_creatives: set[str] = set()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS placements (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                product_id TEXT,
                creative_id TEXT,
                intent_cluster TEXT,
                p_cvr REAL,
                bid REAL,
                served_at TEXT,
                action TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                placement_id TEXT,
                event_type TEXT,
                created_at TEXT,
                FOREIGN KEY (placement_id) REFERENCES placements(id)
            );
            CREATE TABLE IF NOT EXISTS bandit (
                creative_id TEXT,
                intent_cluster TEXT,
                impressions INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                conversions INTEGER DEFAULT 0,
                weight REAL DEFAULT 0.5,
                PRIMARY KEY (creative_id, intent_cluster)
            );
            CREATE TABLE IF NOT EXISTS paused (
                creative_id TEXT PRIMARY KEY,
                paused_at TEXT,
                reason TEXT
            );
            CREATE TABLE IF NOT EXISTS spend_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL,
                created_at TEXT
            );
        """)


def is_paused(creative_id: str) -> bool:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM paused WHERE creative_id = ?", (creative_id,)
        ).fetchone()
    return row is not None


def get_bandit_bonus(creative_id: str, intent_cluster: str) -> float:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT weight FROM bandit WHERE creative_id = ? AND intent_cluster = ?",
            (creative_id, intent_cluster),
        ).fetchone()
    return float(row["weight"]) if row else 0.5


def creative_never_served(creative_id: str) -> bool:
    return creative_id not in _served_creatives


def log_served(
    session_id: str,
    product_id: str,
    creative_id: str,
    intent_cluster: str,
    p_cvr: float,
    bid: float,
    action: str = "serve",
) -> str:
    init_db()
    global _spend_today
    placement_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as conn:
        conn.execute(
            """INSERT INTO placements
               (id, session_id, product_id, creative_id, intent_cluster, p_cvr, bid, served_at, action)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (placement_id, session_id, product_id, creative_id, intent_cluster, p_cvr, bid, now, action),
        )
        if action == "serve" and bid > 0:
            conn.execute("INSERT INTO spend_log (amount, created_at) VALUES (?, ?)", (bid, now))
            _spend_today += bid
        conn.execute(
            """INSERT INTO bandit (creative_id, intent_cluster, impressions, weight)
               VALUES (?, ?, 0, 0.5)
               ON CONFLICT(creative_id, intent_cluster) DO NOTHING""",
            (creative_id, intent_cluster),
        )

    if action == "serve":
        _served_creatives.add(creative_id)
    return placement_id


def record_event(placement_id: str, event_type: str) -> dict:
    init_db()
    policies = load_policies()
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as conn:
        placement = conn.execute(
            "SELECT * FROM placements WHERE id = ?", (placement_id,)
        ).fetchone()
        if not placement:
            return {"ok": False, "error": "placement not found"}

        conn.execute(
            "INSERT INTO events (placement_id, event_type, created_at) VALUES (?, ?, ?)",
            (placement_id, event_type, now),
        )

        cid = placement["creative_id"]
        cluster = placement["intent_cluster"]
        row = conn.execute(
            "SELECT * FROM bandit WHERE creative_id = ? AND intent_cluster = ?",
            (cid, cluster),
        ).fetchone()

        imp = row["impressions"] if row else 0
        clicks = row["clicks"] if row else 0
        convs = row["conversions"] if row else 0
        weight = row["weight"] if row else 0.5

        if event_type == "impression":
            imp += 1
            weight = max(0.1, weight - 0.02)
        elif event_type == "click":
            clicks += 1
            weight = min(0.95, weight + 0.05)
        elif event_type == "conversion":
            convs += 1
            weight = min(0.99, weight + 0.15)
        elif event_type == "no_click":
            imp += 1
            weight = max(0.05, weight - 0.04)

        conn.execute(
            """INSERT INTO bandit (creative_id, intent_cluster, impressions, clicks, conversions, weight)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(creative_id, intent_cluster) DO UPDATE SET
                 impressions = excluded.impressions,
                 clicks = excluded.clicks,
                 conversions = excluded.conversions,
                 weight = excluded.weight""",
            (cid, cluster, imp, clicks, convs, weight),
        )

        paused = False
        pause_threshold = policies.get("pause_after_impressions_no_click", 3)
        if imp >= pause_threshold and clicks == 0 and convs == 0:
            conn.execute(
                """INSERT INTO paused (creative_id, paused_at, reason)
                   VALUES (?, ?, ?)
                   ON CONFLICT(creative_id) DO UPDATE SET paused_at = excluded.paused_at, reason = excluded.reason""",
                (cid, now, f"{imp} impressions, 0 clicks"),
            )
            paused = True
            add_escalation(
                "pause_unprofitable",
                f"Creative {cid} paused after {imp} impressions with no clicks",
                {"creative_id": cid, "placement_id": placement_id},
            )

    return {"ok": True, "bandit_weight": weight, "paused": paused}


def add_escalation(gate: str, message: str, detail: dict | None = None):
    _escalation_queue.append({
        "id": str(uuid.uuid4()),
        "gate": gate,
        "message": message,
        "detail": detail or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    })


def get_escalation_queue() -> list[dict]:
    return list(_escalation_queue)


def resolve_escalation(escalation_id: str, approved: bool) -> bool:
    for item in _escalation_queue:
        if item["id"] == escalation_id:
            item["status"] = "approved" if approved else "rejected"
            if approved and item.get("detail", {}).get("creative_id"):
                _served_creatives.add(item["detail"]["creative_id"])
            return True
    return False


def check_spend_spike() -> bool:
    policies = load_policies()
    daily = policies.get("daily_budget", 500.0)
    threshold = policies.get("spend_spike_threshold", 0.20)
    # Simplified: flag if today's spend exceeds 20% of daily budget in one burst
    return _spend_today > daily * threshold


def get_dashboard_stats() -> dict:
    init_db()
    with _conn() as conn:
        total_imp = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_type IN ('impression', 'no_click')"
        ).fetchone()["c"]
        total_clicks = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_type = 'click'"
        ).fetchone()["c"]
        total_conv = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_type = 'conversion'"
        ).fetchone()["c"]
        total_spend = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM spend_log").fetchone()["s"]
        paused = [dict(r) for r in conn.execute("SELECT * FROM paused").fetchall()]
        bandit_rows = [dict(r) for r in conn.execute("SELECT * FROM bandit ORDER BY weight DESC LIMIT 20")]

    cvr = total_conv / max(total_imp, 1)
    return {
        "impressions": total_imp,
        "clicks": total_clicks,
        "conversions": total_conv,
        "cvr": round(cvr, 4),
        "spend": round(float(total_spend), 2),
        "paused_placements": paused,
        "top_bandit_weights": bandit_rows,
        "escalation_queue": get_escalation_queue(),
    }


def reset_session_state():
    """Clear in-memory state for simulations."""
    global _spend_today
    _spend_today = 0.0
    _served_creatives.clear()
    _escalation_queue.clear()


def reset_db():
    """Wipe outcome data for clean simulation runs."""
    reset_session_state()
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
