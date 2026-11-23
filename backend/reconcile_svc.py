"""仓间配额 vs 在批差额对账 + 互证只读。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from db import connect
from track_state import batch_track_state, consistency_snapshot

router = APIRouter(tags=["reconcile"])

def _chamber_recon(conn, chamber) -> dict:
    cid = chamber["id"]
    quota = int(chamber["quota_batches"])
    batch_rows = conn.execute(
        "SELECT * FROM temp_batches WHERE chamber_id=?", (cid,)
    ).fetchall()
    states = [batch_track_state(conn, row) for row in batch_rows]
    active = sum(
        1
        for row in batch_rows
        if row["status"] not in ("已封批", "作废")
    )
    sealed = sum(1 for s in states if s["official_sealed"])
    shadow = sum(1 for s in states if s["shadow_sealed"])
    thaw_pending = sum(1 for s in states if s["thaw_pending"])
    inconsistent = sum(1 for s in states if not s["consistent"])
    gap = quota - active
    # 配额平衡只看在批；拆轨一致另列字段，不与配额口径混用。
    ok = active <= quota
    return {
        "chamber_id": cid,
        "chamber_code": chamber["chamber_code"],
        "region": chamber["region"],
        "quota_batches": quota,
        "active_batches": active,
        "sealed_batches": sealed,
        "shadow_sealed_batches": shadow,
        "thaw_pending_batches": thaw_pending,
        "inconsistent_batches": inconsistent,
        "quota_left": gap,
        "balanced": ok,
        "proof": {
            "formula": "active_batches <= quota_batches",
            "left": active,
            "right": quota,
            "inconsistent": inconsistent,
        },
    }


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        chambers = conn.execute("SELECT * FROM cold_chambers ORDER BY id").fetchall()
        items = [_chamber_recon(conn, c) for c in chambers]
        bad = [i for i in items if not i["balanced"]]
        return {
            "items": items,
            "track": consistency_snapshot(conn, "reconcile"),
            "summary": {
                "total": len(items),
                "balanced": len(items) - len(bad),
                "unbalanced": len(bad),
            },
        }


@router.get("/api/reconcile/{chamber_code}")
def reconcile_one(chamber_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        ch = conn.execute(
            "SELECT * FROM cold_chambers WHERE chamber_code=?", (chamber_code,)
        ).fetchone()
        if not ch:
            raise HTTPException(404, "仓间不存在")
        return _chamber_recon(conn, ch)


@router.get("/api/proof/batch/{batch_code}")
def batch_proof(batch_code: str, authorization: AuthHeader = None):
    """批次互证：封批代 + 温谱导出 + 开放游标。"""
    require_user(authorization)
    with connect() as conn:
        batch = conn.execute(
            "SELECT * FROM temp_batches WHERE batch_code=?", (batch_code,)
        ).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        open_exc = conn.execute(
            """SELECT COUNT(*) c FROM excursion_cursors
               WHERE batch_id=? AND status='开放'""",
            (batch["id"],),
        ).fetchone()["c"]
        exports = conn.execute(
            """SELECT COUNT(*) c FROM spectrum_exports
               WHERE batch_id=? AND status='已导出'""",
            (batch["id"],),
        ).fetchone()["c"]
        state = batch_track_state(conn, batch)
        sealed = state["official_sealed"]
        spectrum_ok = (exports >= 1) if sealed else True
        return {
            "batch_code": batch_code,
            "status": state["display_status"],
            "raw_status": batch["status"],
            "generation": batch["generation"],
            "open_excursions": open_exc,
            "spectrum_exports": exports,
            "sealed": sealed,
            "official_seal": state["official_sealed"],
            "shadow_sealed": state["shadow_sealed"],
            "thaw_pending": state["thaw_pending"],
            "consistent": state["consistent"],
            "excursion_closed": open_exc == 0,
            "spectrum_matches_seal": spectrum_ok,
            "proof": {
                "formula": "official_seal => spectrum>=1 and open_excursions==0",
                "sealed": sealed,
                "official_seal": state["official_sealed"],
                "shadow_sealed": state["shadow_sealed"],
                "open_excursions": open_exc,
                "exports": exports,
            },
        }