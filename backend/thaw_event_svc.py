"""解冻事件空桩：只写任务表与审计，封批正式字段零改（甲路径）。

- 解冻轨不得写封批正式字段：不碰 temp_batches.status/generation/sealed_at，
  不写 seal_snapshots；封批表零改。
- 批次若处于封批轨（正式封批或影子封批态）一律拒收，并记「解冻偏航」。
- 同批解冻须抢 batch:{id} 封批锁；后到只留争用痕，不写态。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_writer
from db import connect, now_iso, write_audit
from locks import acquire_committed, release_committed
from models import ThawStubIn
from track_state import (
    OFFICIAL_SEAL_STATUS,
    SHADOW_DISPLAY,
    attach_track_state,
    batch_track_state,
    consistency_snapshot,
)

router = APIRouter(tags=["stubs"])

THAW_PENDING = "待提交"


@router.get("/api/thaw/jobs")
def list_thaw_jobs(authorization: AuthHeader = None):
    require_writer(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM thaw_event_jobs ORDER BY id DESC LIMIT 100"
        ).fetchall()
        return {
            "items": attach_track_state(conn, rows),
            "track": consistency_snapshot(conn, "stubs"),
        }


def _reject(conn, user: str, batch_id, action: str, reason: str, detail: str) -> None:
    write_audit(
        conn,
        user,
        action,
        str(batch_id if batch_id is not None else "none"),
        {"reason": reason, "verdict": "拒写", "detail": detail},
    )
    conn.commit()
    raise HTTPException(409, detail)


def _assert_thawable(conn, batch_id: int):
    batch = conn.execute(
        "SELECT * FROM temp_batches WHERE id=?", (batch_id,)
    ).fetchone()
    state = batch_track_state(conn, batch)
    if state["official_sealed"] or state["shadow_sealed"]:
        raise HTTPException(
            409,
            f"批次处于封批轨（{SHADOW_DISPLAY if state['shadow_sealed'] else OFFICIAL_SEAL_STATUS}），"
            "解冻事件拒收",
        )
    return batch


@router.post("/api/thaw-stub")
def stub_thaw(body: ThawStubIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        if body.batch_id is not None:
            exists = conn.execute(
                "SELECT id FROM temp_batches WHERE id=?", (body.batch_id,)
            ).fetchone()
            if not exists:
                raise HTTPException(404, "批次不存在")
        lock_key = f"batch:{body.batch_id}" if body.batch_id is not None else None
        if lock_key and not acquire_committed(conn, lock_key, user):
            _reject(
                conn,
                user,
                body.batch_id,
                "解冻偏航",
                "争用",
                "争用：后到只记争用，不写解冻态",
            )
        try:
            batch = None
            if body.batch_id is not None:
                try:
                    batch = _assert_thawable(conn, body.batch_id)
                except HTTPException as exc:
                    _reject(
                        conn,
                        user,
                        body.batch_id,
                        "解冻偏航",
                        "封批轨",
                        str(exc.detail),
                    )
            cur = conn.execute(
                """INSERT INTO thaw_event_jobs(batch_id,thaw_minutes,mode,status,detail,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    body.batch_id,
                    body.thaw_minutes,
                    body.mode,
                    THAW_PENDING,
                    "仅登记解冻轨；封批正式字段零改",
                    now_iso(),
                ),
            )
            write_audit(
                conn,
                user,
                "thaw_stub",
                str(body.batch_id if body.batch_id is not None else "none"),
                {"job_id": cur.lastrowid, "track": "解冻轨", "seal_written": False},
            )
            conn.commit()
            return {
                "job_id": cur.lastrowid,
                "status": THAW_PENDING,
                "batch_unchanged": True,
                "seal_unchanged": True,
                "track": "解冻轨",
                "batch_status": batch["status"] if batch else None,
            }
        finally:
            if lock_key:
                release_committed(conn, lock_key, user)
