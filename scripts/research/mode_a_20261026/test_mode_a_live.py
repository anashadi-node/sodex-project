"""Tes mode_a_live (offline; CLI dipalsukan). Fokus: SETIAP gerbang live memblokir, tidak ada jalur order tanpa arm, idempoten, tanpa retry."""
import datetime as dt, json, os, stat
from decimal import Decimal
import pytest
import mode_a_engine as eng
import mode_a_live as L
import spot_exec as sx

NOW = dt.datetime(2026, 12, 2, 1, 0, tzinfo=dt.timezone.utc)


def mkbook(a, mid):
    t = float(sx.TICK[a])
    bids = [(Decimal(str(mid - t * (i + 1))), Decimal("5")) for i in range(10)]
    asks = [(Decimal(str(mid + t * (i + 1))), Decimal("5")) for i in range(10)]
    return sx.validate_book({"asset": a, "bids": bids, "asks": asks})


MID = {"btc": 80000.0, "eth": 2300.0, "xaut": 4000.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    sec, fwd = tmp_path / "secrets", tmp_path / "fwd"; sec.mkdir(); fwd.mkdir()
    for n, v in (("ARM_FILE", sec / "LIVE_ARMED.json"), ("KILL_FILE", sec / "KILL"), ("ENV_FILE", sec / "sodex.env"),
                 ("LEDGER", fwd / "live_exec.jsonl"), ("STATE", fwd / "live_state.json"), ("FWD", str(fwd))):
        monkeypatch.setattr(L, n, str(v))
    monkeypatch.setattr(L, "now_utc", lambda: NOW)
    monkeypatch.setenv("CONFIRM_LIVE", "YES")
    (sec / "sodex.env").write_text("SODEX_PRIVATE_KEY=0xAAA\nSODEX_ACCOUNT_ID=7\nSODEX_ADDRESS=0xBBB\nSODEX_API_KEY=zzz # tak diteruskan\n")
    os.chmod(sec / "sodex.env", 0o600)
    arm = {"armed": True, "go_by": "Mas Anas", "go_utc": "2026-12-01T00:10:00+00:00", "not_before": "2026-12-01", "max_equity_usd": 400,
           "max_order_usd": 100, "max_total_buy_usd": 200, "engine_sha256": L.sha(os.path.join(L.HERE, "mode_a_engine.py")), "acknowledge_prareg23b_verdict": True}
    (sec / "LIVE_ARMED.json").write_text(json.dumps(arm))
    rec = {"kind": "rec", "asof": "2026-12-01", "backfill": False, "closes": MID, "targets": {"A": {"btc": 0.20, "eth": 0.10, "xaut": 0.0}, "B1": {}, "B2": {}}}
    (fwd / "ledger.jsonl").write_text(json.dumps(rec) + "\n")
    monkeypatch.setattr(sx, "fetch_book", lambda a, depth=20: mkbook(a, MID[a]))
    calls = []
    bal = [{"coin": "vUSDC", "total": "243.02", "available": "243.02"}]

    def fake(args, env=None, timeout=25):
        calls.append(args)
        if args[0] == "balance": return bal
        if args[:2] == ["orders", "place"]: return {"orderID": "123", "status": "FILLED"}
        raise AssertionError(args)
    monkeypatch.setattr(sx, "run_cli", fake)
    return {"sec": sec, "fwd": fwd, "arm": arm, "calls": calls, "bal": bal}


def arm_write(e, **kw):
    a = {**e["arm"], **kw}; (e["sec"] / "LIVE_ARMED.json").write_text(json.dumps(a))


def test_arm_ok(env): assert L.check_arm(NOW.date())["armed"] is True


@pytest.mark.parametrize("kw,pat", [({"armed": False}, "armed"), ({"go_by": ""}, "go_by"), ({"not_before": "2026-11-30"}, "2026-12-01"),
                                    ({"not_before": "2026-12-25"}, "belum tanggal"), ({"engine_sha256": "x"}, "engine_sha256"),
                                    ({"max_order_usd": 0}, "max_order_usd"), ({"max_equity_usd": -1}, "max_equity_usd"),
                                    ({"acknowledge_prareg23b_verdict": False}, "acknowledge"), ({"go_utc": "bukan tanggal"}, "tidak valid")])
def test_arm_blocks(env, kw, pat):
    arm_write(env, **kw)
    with pytest.raises(L.Block, match=pat): L.check_arm(NOW.date())


def test_arm_blocks_missing_file_kill_and_confirm(env, monkeypatch):
    monkeypatch.delenv("CONFIRM_LIVE")
    with pytest.raises(L.Block, match="CONFIRM_LIVE"): L.check_arm(NOW.date())
    monkeypatch.setenv("CONFIRM_LIVE", "YES"); (env["sec"] / "KILL").write_text("")
    with pytest.raises(L.Block, match="KILL"): L.check_arm(NOW.date())
    os.remove(env["sec"] / "KILL"); os.remove(env["sec"] / "LIVE_ARMED.json")
    with pytest.raises(L.Block, match="belum GO|belum ada"): L.check_arm(NOW.date())


def test_env_perm_and_content(env):
    e = L.load_env(); assert e["SODEX_PRIVATE_KEY"] == "0xAAA" and "SODEX_API_KEY" not in e
    os.chmod(env["sec"] / "sodex.env", 0o644)
    with pytest.raises(L.Block, match="600"): L.load_env()
    os.chmod(env["sec"] / "sodex.env", 0o600); (env["sec"] / "sodex.env").write_text("SODEX_PRIVATE_KEY=0x1\n")
    with pytest.raises(L.Block, match="kurang"): L.load_env()


def test_parse_balances():
    r = L.parse_balances([{"coin": "vUSDC", "total": "10", "locked": "3"}, {"coin": "vBTC", "total": "0.001", "available": "0.0008"}, {"coin": "DOGE", "total": "5"}])
    assert r["usdc"] == 7.0 and r["btc"] == 0.0008 and r["eth"] == 0.0
    assert L.parse_balances({"data": {"balances": [{"coin": "vETH", "total": "2"}]}})["eth"] == 2.0
    with pytest.raises(sx.ExecError): L.parse_balances("aneh")
    with pytest.raises(sx.ExecError): L.parse_balances([1])


def test_live_flow_orders_dan_idempoten(env):
    out = L.run(True)
    assert out["mode"] == "LIVE" and all(o["ok"] for o in out["orders"])
    placed = [c for c in env["calls"] if c[:2] == ["orders", "place"]]
    assert len(placed) == 2 and all("ioc" in c and "limit" in c for c in placed)
    for c in placed:
        a = {"BTC/USDC": "btc", "ETH/USDC": "eth"}[c[c.index("--symbol") + 1]]
        side, price, qty = c[c.index("--side") + 1], Decimal(c[c.index("--price") + 1]), Decimal(c[c.index("--qty") + 1])
        assert side == "buy" and price >= Decimal(str(MID[a]))                 # batas di atas ask (beli), tidak liar
        assert price <= Decimal(str(MID[a])) * Decimal("1.0040")               # <= ~30bps + tick
        assert qty % sx.STEP[a] == 0 and qty * price >= 5
    assert sum(float(Decimal(c[c.index("--qty") + 1]) * Decimal(c[c.index("--price") + 1])) for c in placed) <= 243.02
    n = len(env["calls"]); again = L.run(True)
    assert again["status"] == "SUDAH" and len([c for c in env["calls"] if c[:2] == ["orders", "place"]]) == 2
    kinds = [json.loads(x)["kind"] for x in open(L.LEDGER)]
    assert kinds == ["intent", "result"]


def test_dry_run_tidak_pernah_kirim_order(env):
    (env["fwd"] / "paper_exec_state.json").write_text(json.dumps({"accounts": {"A": {"cash": 243.02, "hold": {"btc": 0, "eth": 0, "xaut": 0}}}, "done": []}))
    out = L.run(False)
    assert out["mode"] == "DRY-RUN" and out["orders"]
    assert not [c for c in env["calls"] if c[:2] == ["orders", "place"]]


@pytest.mark.parametrize("kw", [{"max_order_usd": 10}, {"max_total_buy_usd": 20}, {"max_equity_usd": 100}])
def test_cap_memblokir_tanpa_order(env, kw):
    arm_write(env, **kw)
    with pytest.raises(L.Block): L.run(True)
    assert not [c for c in env["calls"] if c[:2] == ["orders", "place"]]


def test_target_basi_dan_backfill_diblok(env):
    p = env["fwd"] / "ledger.jsonl"; r = json.loads(p.read_text()); r["asof"] = "2026-11-29"; p.write_text(json.dumps(r) + "\n")
    with pytest.raises(L.Block, match="basi"): L.run(True)
    r["asof"] = "2026-12-01"; r["backfill"] = True; p.write_text(json.dumps(r) + "\n")
    with pytest.raises(L.Block, match="backfill"): L.run(True)


def test_gagal_order_tidak_retry_dan_dicatat(env, monkeypatch):
    n = {"k": 0}
    def fake(args, env=None, timeout=25):
        if args[0] == "balance": return env_bal
        n["k"] += 1; raise sx.ExecError("timeout")
    env_bal = env["bal"]; monkeypatch.setattr(sx, "run_cli", fake)
    out = L.run(True)
    assert n["k"] == 1 and out["orders"][0]["ok"] is False and len(out["orders"]) == 1      # berhenti di kegagalan pertama
    assert L.run(True)["status"] == "SUDAH"                                                 # tidak diulang otomatis


def test_intent_tanpa_result_memblokir(env):
    open(L.LEDGER, "w").write(json.dumps({"kind": "intent", "asof": "2026-12-01"}) + "\n")
    with pytest.raises(L.Block, match="rekonsiliasi"): L.run(True)


def test_tanpa_arm_run_live_tidak_ada_order(env):
    os.remove(env["sec"] / "LIVE_ARMED.json")
    with pytest.raises(L.Block): L.run(True)
    assert env["calls"] == []


def test_selftest_hanya_testnet(env, monkeypatch):
    monkeypatch.delenv("SODEX_TESTNET", raising=False)
    with pytest.raises(L.Block, match="TESTNET"): L.selftest()


# ---- circuit breaker drawdown (anggaran risiko, disetujui user 26-Okt-2026) ----
def _seed_peak(e, peak):
    (e["fwd"] / "live_exec.jsonl").write_text(json.dumps({"kind": "result", "asof": "2026-11-30", "equity_after": peak, "orders": []}) + "\n")


def test_dd_breach_menulis_kill_dan_tanpa_order(env):
    _seed_peak(env, 400.0)                       # ekuitas kini 243,02 -> -39%
    n0 = len(env["calls"])
    with pytest.raises(L.Block, match="CIRCUIT BREAKER"): L.run(True)
    assert (env["sec"] / "KILL").exists()
    assert not [c for c in env["calls"][n0:] if c[:2] == ["orders", "place"]]
    with pytest.raises(L.Block, match="KILL"): L.check_arm(NOW.date())     # run berikutnya tetap terkunci


def test_dd_dalam_batas_lolos(env):
    _seed_peak(env, 280.0)                       # 243,02/280 = -13,2% > -20%
    r = L.run(True)
    assert r["mode"] == "LIVE" and not (env["sec"] / "KILL").exists()


@pytest.mark.parametrize("lim", [0, -5, 21, 50, "20"])
def test_dd_batas_arm_tak_valid_atau_longgar_ditolak(env, lim):
    with pytest.raises(L.Block, match="max_drawdown_pct"): L.check_drawdown(243.0, {"max_drawdown_pct": lim})


def test_dd_arm_boleh_mengetatkan(env):
    _seed_peak(env, 280.0)                       # -13,2%
    with pytest.raises(L.Block, match="CIRCUIT BREAKER"): L.check_drawdown(243.02, {"max_drawdown_pct": 10})


def test_dd_tanpa_riwayat_tidak_memblokir(env):
    assert L.check_drawdown(243.02, {})["dd_pct"] == 0.0
