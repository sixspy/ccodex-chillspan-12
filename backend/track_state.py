"""解冻轨 × 封批轨拆轨口径（甲路径）。

唯一口径来源：解冻事件不得写封批正式字段；正式封批只认 seal_snapshots
（且须与批次当前代数一致）。批次表 status='已封批' 却无正式快照的，一律
视为影子封批态，不得在任一视图展示为已封。

立场见 docs/thaw-seal-note.md（2026-11-23 当日封口，折中禁用）。
"""
from __future__ import annotations

import hashlib
import json

OFFICIAL_SEAL_STATUS = "已封批"
SHADOW_DISPLAY = "影子封批·待复核"
# 解冻空桩只有登记/待提交，未晋升为正式封批依据。
THAW_PENDING_STATUSES = ("待提交", "空桩登记")
# 须同态的五视图 + 对账互证。
TRACK_VIEWS = ("batches", "seal", "spectrum", "stubs", "routes", "reconcile")


def official_seal_row(conn, batch):
    """正式封批快照：状态已封批且代次与批次当前代次一致。"""
    return conn.execute(
        """SELECT * FROM seal_snapshots
           WHERE batch_id=? AND status=? AND batch_generation=?
           ORDER BY id DESC LIMIT 1""",
        (int(batch["id"]), OFFICIAL_SEAL_STATUS, int(batch["generation"])),
    ).fetchone()


def thaw_pending_count(conn, batch_id: int) -> int:
    marks = ",".join("?" for _ in THAW_PENDING_STATUSES)
    return int(
        conn.execute(
            f"""SELECT COUNT(*) c FROM thaw_event_jobs
                WHERE batch_id=? AND status IN ({marks})""",
            (int(batch_id), *THAW_PENDING_STATUSES),
        ).fetchone()["c"]
    )


def batch_track_state(conn, batch) -> dict:
    """单批次轨态：封批轨（正式/影子/未封）+ 解冻轨（待提交/无）。"""
    batch = dict(batch)
    snap = official_seal_row(conn, batch)
    official_sealed = snap is not None
    shadow_sealed = batch["status"] == OFFICIAL_SEAL_STATUS and not official_sealed
    pending = thaw_pending_count(conn, batch["id"])

    status_sealed = batch["status"] == OFFICIAL_SEAL_STATUS
    # 两轨各执一词：批次表喊已封却无快照、有快照却批次表未封、正式封批仍挂解冻待提交。
    consistent = (status_sealed == official_sealed) and not (
        official_sealed and pending > 0
    )

    if official_sealed:
        display_status = OFFICIAL_SEAL_STATUS
        seal_track = "正式封批"
    elif shadow_sealed:
        display_status = SHADOW_DISPLAY
        seal_track = SHADOW_DISPLAY
    else:
        display_status = batch["status"]
        seal_track = "未封批"
    thaw_track = "解冻待提交" if pending else "无轨"

    return {
        "batch_id": int(batch["id"]),
        "batch_code": batch["batch_code"],
        "status": batch["status"],
        "display_status": display_status,
        "seal_track": seal_track,
        "thaw_track": thaw_track,
        "official_sealed": official_sealed,
        "shadow_sealed": shadow_sealed,
        "seal_generation": int(snap["batch_generation"]) if snap else None,
        "thaw_pending": pending,
        "consistent": consistent,
    }


def attach_track_state(conn, rows, batch_key: str = "id") -> list[dict]:
    """给业务行附 state；行内无 batch_id 时取 batch_key 所指列。"""
    items = []
    for row in rows:
        item = dict(row)
        bid = item.get("batch_id", item.get(batch_key))
        if bid is None:
            item["state"] = None
        else:
            batch = conn.execute(
                "SELECT * FROM temp_batches WHERE id=?", (int(bid),)
            ).fetchone()
            item["state"] = batch_track_state(conn, batch) if batch else None
        items.append(item)
    return items


def consistency_snapshot(conn, view: str) -> dict:
    """同态票：五视图读同一份轨态指纹，票不一致即两轨异态。"""
    rows = conn.execute("SELECT * FROM temp_batches ORDER BY id").fetchall()
    states = [batch_track_state(conn, row) for row in rows]
    canonical = json.dumps(
        [
            [
                s["batch_id"],
                s["status"],
                s["display_status"],
                s["official_sealed"],
                s["shadow_sealed"],
                s["seal_generation"],
                s["thaw_pending"],
                s["consistent"],
            ]
            for s in states
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    token = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {
        "view": view,
        "views": list(TRACK_VIEWS),
        "consistency_token": token,
        "batches": len(states),
        "official_sealed": sum(1 for s in states if s["official_sealed"]),
        "shadow_sealed": sum(1 for s in states if s["shadow_sealed"]),
        "thaw_pending": sum(1 for s in states if s["thaw_pending"]),
        "inconsistent": sum(1 for s in states if not s["consistent"]),
    }
