"""五视图同态总票（只读）。"""
from __future__ import annotations

from fastapi import APIRouter

from auth import AuthHeader, require_user
from db import connect
from track_state import batch_track_state, consistency_snapshot

router = APIRouter(tags=["track"])


@router.get("/api/track/state")
def track_state(authorization: AuthHeader = None):
    """空桩 / 封批 / 批次 / 温谱 / 线路 五视图读同一轨态票。"""
    require_user(authorization)
    with connect() as conn:
        items = [
            batch_track_state(conn, row)
            for row in conn.execute(
                "SELECT * FROM temp_batches ORDER BY id"
            ).fetchall()
        ]
        return {"items": items, "track": consistency_snapshot(conn, "track")}
