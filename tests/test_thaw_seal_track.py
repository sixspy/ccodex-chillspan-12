"""解冻空桩 × 封批态拆轨回归（甲路径）。

口径（见 docs/thaw-seal-note.md）：
- 甲路径：解冻事件不得写封批正式字段，封批表零改，已正式封批一律拒收。
- 影子态（temp_batches 显示已封但无正式封批快照）不得被展示为已封。
- 两人同批提交解冻须抢 batch:{id} 封批锁；后到只留争用痕，不写态。

本文件先落三枚红测：解冻改正式封批、影子态未晋升却显示已封、双人同批抢解冻。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db, now_iso


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user: str = "admin") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _batch_row(conn, batch_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM temp_batches WHERE id=?", (batch_id,)
    ).fetchone()
    return dict(row)


def _snapshot_count(conn, batch_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM seal_snapshots WHERE batch_id=?", (batch_id,)
    ).fetchone()["c"]


def _thaw_count(conn, batch_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM thaw_event_jobs WHERE batch_id=?", (batch_id,)
    ).fetchone()["c"]


def _seed_official_seal(batch_id: int) -> None:
    """种子夹具：正式封批（封批快照 + 批次态同写），封批表已有正式记录。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM temp_batches WHERE id=?", (batch_id,)
        ).fetchone()
        gen = int(row["generation"])
        manifest = json.dumps(
            {"batch_code": row["batch_code"], "generation": gen},
            ensure_ascii=False,
        )
        conn.execute(
            """INSERT INTO seal_snapshots(batch_id,batch_generation,manifest,status,sealed_at)
               VALUES (?,?,?,?,?)""",
            (batch_id, gen, manifest, "已封批", "2026-11-23T09:00:00"),
        )
        conn.execute(
            "UPDATE temp_batches SET status='已封批', sealed_at=? WHERE id=?",
            ("2026-11-23T09:00:00", batch_id),
        )
        conn.commit()


def _seed_shadow_sealed() -> int:
    """种子夹具：影子封批态 —— 批次显示已封，但无正式封批快照，且挂着待提交解冻空桩。"""
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO temp_batches(batch_code,chamber_id,probe_id,cargo_ref,
               temp_points,generation,status,min_observed,max_observed,created_at,sealed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "TB-SHADOW-001",
                1,
                1,
                "影子货载",
                json.dumps([{"t": "08:00", "c": -19.0}], ensure_ascii=False),
                2,
                "已封批",
                -19.0,
                -19.0,
                now_iso(),
                "2026-11-23T08:00:00",
            ),
        )
        batch_id = cur.lastrowid
        conn.execute(
            """INSERT INTO thaw_event_jobs(batch_id,thaw_minutes,mode,status,detail,created_at)
               VALUES (?,?,?,?,?,?)""",
            (batch_id, 25, "卸货口", "待提交", "影子态未晋升", now_iso()),
        )
        conn.commit()
        return int(batch_id)


def test_thaw_must_not_write_official_seal():
    """红测甲：解冻改正式封批 —— 已正式封批批次拒收，封批表与批次正式字段零改。"""
    c = TestClient(app)
    h = _auth(c)
    batch_id = 1
    _seed_official_seal(batch_id)
    with connect() as conn:
        before = _batch_row(conn, batch_id)
        snap_before = _snapshot_count(conn, batch_id)
        thaw_before = _thaw_count(conn, batch_id)

    r = c.post(
        "/api/thaw-stub",
        headers=h,
        json={"batch_id": batch_id, "thaw_minutes": 30, "mode": "卸货口"},
    )
    assert r.status_code == 409, r.text
    assert "封批" in r.json()["detail"]

    with connect() as conn:
        after = _batch_row(conn, batch_id)
        assert _snapshot_count(conn, batch_id) == snap_before
        assert _thaw_count(conn, batch_id) == thaw_before
        audit = conn.execute(
            """SELECT action,payload FROM audit_trail
               WHERE action='解冻偏航' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        assert audit is not None
        assert "拒写" in audit["payload"]
    for key in ("status", "generation", "sealed_at"):
        assert after[key] == before[key]


def test_shadow_sealed_never_shown_as_official():
    """红测乙：影子态未晋升却显示已封 —— 无正式快照不得展示已封，温谱拒导。"""
    c = TestClient(app)
    h = _auth(c)
    batch_id = _seed_shadow_sealed()

    detail = c.get(f"/api/batches/{batch_id}", headers=h).json()
    state = detail["state"]
    assert state["official_sealed"] is False
    assert state["consistent"] is False
    assert state["thaw_pending"] == 1

    proof = c.get("/api/proof/batch/TB-SHADOW-001", headers=h).json()
    assert proof["sealed"] is False
    assert proof["official_seal"] is False
    assert proof["consistent"] is False

    seals = c.get("/api/seals", headers=h).json()["items"]
    assert all(s["batch_id"] != batch_id for s in seals)

    sp = c.post("/api/spectrum/export", headers=h, json={"batch_id": batch_id})
    assert sp.status_code == 409


def test_two_actors_same_batch_thaw_contend_on_seal_lock():
    """红测丙：双人同批抢解冻 —— 抢 batch:{id} 封批锁，后到留争用痕不写态。"""
    c = TestClient(app)
    h_admin = _auth(c, "admin")
    h_ops = _auth(c, "ops")
    batch_id = 3
    lock_key = f"batch:{batch_id}"

    got = c.post("/api/locks/acquire", headers=h_admin, json={"lock_key": lock_key})
    assert got.status_code == 200
    with connect() as conn:
        thaw_before = _thaw_count(conn, batch_id)
        before = _batch_row(conn, batch_id)

    r = c.post(
        "/api/thaw-stub",
        headers=h_ops,
        json={"batch_id": batch_id, "thaw_minutes": 18, "mode": "后到"},
    )
    assert r.status_code == 409, r.text

    with connect() as conn:
        assert _thaw_count(conn, batch_id) == thaw_before
        after = _batch_row(conn, batch_id)
        rows = conn.execute(
            "SELECT * FROM contention_log WHERE lock_key=?", (lock_key,)
        ).fetchall()
        assert any(row["actor"] == "ops" for row in rows)
    for key in ("status", "generation", "sealed_at"):
        assert after[key] == before[key]

    c.post("/api/locks/release", headers=h_admin, json={"lock_key": lock_key})


def test_five_views_share_one_track_state():
    """验收：空桩 / 封批 / 批次 / 温谱 / 线路 五视图读同一轨态指纹。"""
    c = TestClient(app)
    h = _auth(c)
    _seed_shadow_sealed()

    views = {
        "batches": c.get("/api/batches", headers=h).json(),
        "seal": c.get("/api/seals", headers=h).json(),
        "spectrum": c.get("/api/spectrum", headers=h).json(),
        "stubs": c.get("/api/thaw/jobs", headers=h).json(),
        "routes": c.get("/api/routes", headers=h).json(),
        "reconcile": c.get("/api/reconcile", headers=h).json(),
    }
    tokens = {name: body["track"]["consistency_token"] for name, body in views.items()}
    assert len(set(tokens.values())) == 1, tokens
    required = {"batches", "seal", "spectrum", "stubs", "routes"}
    assert required.issubset(set(views["routes"]["track"]["views"]))
    assert views["batches"]["track"]["shadow_sealed"] >= 1
    assert views["batches"]["track"]["inconsistent"] >= 1


def test_thaw_unknown_batch_is_404_not_sealed_reject():
    c = TestClient(app)
    h = _auth(c)
    r = c.post(
        "/api/thaw-stub", headers=h, json={"batch_id": 99999, "thaw_minutes": 5}
    )
    assert r.status_code == 404
