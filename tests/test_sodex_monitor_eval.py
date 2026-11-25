import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase


class SodexMonitorEvalTests(TestCase):
    def test_default_volume_fee_ratio_matches_current_real_ratio_doctrine(self):
        from scripts import sodex_monitor_eval as mon

        # post-emergency base ratio (emergency expired 2026-07-18)
        self.assertEqual(mon.TARGET_VOLUME_FEE_RATIO, mon.Decimal("7000"))

    def test_week_window_uses_saturday_0700_wib_boundary(self):
        from scripts import sodex_monitor_eval as mon

        now = datetime(2026, 6, 18, 3, 30, tzinfo=timezone.utc)
        window = mon.week_window(now)

        self.assertEqual(window.start, datetime(2026, 6, 13, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end, datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(window.label, "2026-06-13T00:00:00+00:00_to_2026-06-20T00:00:00+00:00")

    def test_live_kill_status_and_repair_plan_are_reported(self):
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kills = {
                "REALWIDE_LIVE_KILL": root / "REALWIDE_LIVE_KILL",
                "SPOT_LIVE_KILL": root / "SPOT_LIVE_KILL",
            }
            kills["REALWIDE_LIVE_KILL"].write_text("")

            status = mon.read_live_kill_status(kills)
            plan = mon.build_repair_plan({}, {}, {"active": False}, status)

        self.assertTrue(status["active"])
        self.assertEqual(status["active_files"], ["REALWIDE_LIVE_KILL"])
        self.assertEqual(plan["actions"][0]["type"], "LIVE_KILL_ACTIVE_NO_TRADING")
        self.assertIn("explicit GO-LIVE", plan["actions"][0]["safe"])

    def test_text_report_includes_live_kills(self):
        from scripts import sodex_monitor_eval as mon

        report = {
            "ts": "2026-09-18T00:00:00+00:00",
            "window": {"range": "12 September 2026 - 19 September 2026", "weekly_label": "weekly 19 sodex", "snapshot_wib": "19 September 2026 07:00 WIB"},
            "verdict": {"status": "FAIL", "reasons": [], "warnings": []},
            "monitor_risk": {},
            "repair_plan": {"watchdog_restart_signal": False},
            "live_kills": {"active": True, "active_files": ["REALWIDE_LIVE_KILL", "SPOT_LIVE_KILL"]},
            "official_dashboard": {"volume": {}},
            "ledger": {"quality": "OK", "volume": {}, "pnl": {}, "costs": {}, "ratios": {}, "rts": {}, "warnings": []},
            "account": {"quality": "OK", "account_value": {}, "assets": {}, "warnings": []},
            "telegram_health": {},
        }

        text = mon.format_text(report)

        self.assertIn("live_kills", text)
        self.assertIn("REALWIDE_LIVE_KILL", text)

    def test_week_display_labels_indonesian_dates_and_weekly_sodex_number(self):
        from scripts import sodex_monitor_eval as mon

        window = mon.week_window(datetime(2026, 6, 18, 3, 30, tzinfo=timezone.utc))
        display = mon.week_display(window)

        self.assertEqual(display["range"], "13 Juni 2026 - 20 Juni 2026")
        self.assertEqual(display["weekly_label"], "weekly 20 sodex")
        self.assertEqual(display["snapshot_wib"], "20 Juni 2026 07:00 WIB")

    def test_ledger_aggregation_reports_raw_and_weighted_volume_ratio(self):
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "twin.db"
            con = sqlite3.connect(db_path)
            con.executescript(
                """
                CREATE TABLE fills(
                  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, engine TEXT NOT NULL,
                  bucket TEXT NOT NULL, pair TEXT NOT NULL, side TEXT NOT NULL,
                  price TEXT NOT NULL, qty TEXT NOT NULL, notional TEXT NOT NULL,
                  fee TEXT NOT NULL, maker INTEGER NOT NULL, rt_id TEXT);
                CREATE TABLE rts(
                  rt_id TEXT PRIMARY KEY, ts_close TEXT, engine TEXT, pair TEXT,
                  volume TEXT, net_pnl TEXT);
                """
            )
            con.executemany(
                "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("2026-06-13T01:00:00+00:00", "E1", "S", "PEPE/USDC", "buy", "1", "1", "100", "0.01", 1, "r1"),
                    ("2026-06-14T01:00:00+00:00", "E2", "P", "BTC-USD", "buy", "1", "1", "300", "0.03", 0, "r2"),
                    ("2026-06-12T23:59:00+00:00", "E2", "P", "BTC-USD", "buy", "1", "1", "999", "9", 1, "old"),
                ],
            )
            con.executemany(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                [
                    ("r1", "2026-06-13T02:00:00+00:00", "E1", "PEPE/USDC", "100", "1.5"),
                    ("r2", "2026-06-14T02:00:00+00:00", "E2", "BTC-USD", "300", "-0.5"),
                    ("old", "2026-06-12T23:59:00+00:00", "E2", "BTC-USD", "999", "-9"),
                ],
            )
            con.commit()
            con.close()

            window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
            agg = mon.aggregate_ledger(db_path, window)

        self.assertEqual(agg["quality"], "OK")
        self.assertEqual(agg["fills"]["count"], 2)
        self.assertEqual(agg["volume"]["spot_usd"], 100.0)
        self.assertEqual(agg["volume"]["perps_usd"], 300.0)
        self.assertEqual(agg["volume"]["raw_total_usd"], 400.0)
        self.assertEqual(agg["volume"]["weighted_total_usd"], 500.0)
        self.assertAlmostEqual(agg["ratios"]["volume_to_fee"], 10000.0)
        self.assertEqual(agg["rts"]["count"], 2)
        self.assertEqual(agg["rts"]["wins"], 1)
        self.assertEqual(agg["rts"]["losses"], 1)
        self.assertEqual(agg["pnl"]["realized_net_usd"], 1.0)

    def test_report_verdict_is_honest_about_target_and_data_quality(self):
        from scripts import sodex_monitor_eval as mon

        window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
        ledger = {
            "quality": "OK",
            "volume": {"raw_total_usd": 800_000.0, "weighted_total_usd": 900_000.0},
            "pnl": {"realized_net_usd": -12.0},
            "ratios": {"volume_to_fee": 5500.0},
            "rts": {"count": 50, "win_rate": 0.62},
            "warnings": [],
        }
        account = {"quality": "API_UNAVAILABLE", "warnings": ["perps state missing"]}

        verdict = mon.evaluate(window, ledger, account)

        self.assertEqual(verdict["status"], "FAIL")
        self.assertIn("weekly_volume_below_target", verdict["reasons"])
        self.assertIn("weekly_win_rate_below_target", verdict["reasons"])
        self.assertIn("realized_pnl_negative", verdict["reasons"])
        self.assertIn("account_api_not_ok", verdict["reasons"])

    def test_evaluate_no_api_mode_does_not_count_as_api_failure(self):
        from scripts import sodex_monitor_eval as mon

        window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
        ledger = {
            "quality": "OK",
            "volume": {"raw_total_usd": 0},
            "pnl": {"realized_net_usd": 0},
            "ratios": {"volume_to_fee": None},
            "rts": {"count": 0, "win_rate": None},
            "coverage": {"e1_covers_e2_fees": True, "combined_no_loss": True},
        }
        verdict = mon.evaluate(window, ledger, {"quality": "DISABLED", "warnings": []})

        self.assertNotIn("account_api_not_ok", verdict["reasons"])

    def test_official_dashboard_volume_overrides_ledger_for_target_progress(self):
        from scripts import sodex_monitor_eval as mon

        window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
        ledger = {
            "quality": "OK",
            "volume": {
                "raw_total_usd": 631_194.03,
                "spot_usd": 201_796.99,
                "perps_usd": 429_397.04,
            },
            "pnl": {"realized_net_usd": 31.18},
            "costs": {"fees_usd": 110.37},
            "ratios": {"volume_to_fee": 5718.0},
            "rts": {"count": 10, "win_rate": 0.9},
            "warnings": [],
        }
        account = {"quality": "OK", "warnings": []}
        official = {
            "quality": "OK",
            "canonical": True,
            "volume": {
                "spot_usd": 132_732.25,
                "perps_usd": 15_520.46,
                "total_usd": 148_252.71,
            },
        }

        verdict = mon.evaluate(
            window,
            ledger,
            account,
            official_dashboard=official,
            target_volume=mon.Decimal("1000000"),
            target_ratio=mon.Decimal("6400"),
        )

        self.assertAlmostEqual(verdict["progress"]["weekly_volume_pct"], 0.14825271)
        self.assertAlmostEqual(verdict["progress"]["canonical_volume_usd"], 148_252.71)
        self.assertEqual(verdict["progress"]["canonical_volume_source"], "official_dashboard")
        self.assertIn("official_dashboard_lower_than_internal_ledger", verdict["warnings"])

    def test_dashboard_snapshot_is_normalized_and_reconciled_with_ledger(self):
        from scripts import sodex_monitor_eval as mon

        window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
        ledger = {
            "volume": {
                "spot_usd": 201_796.99,
                "perps_usd": 429_397.04,
                "raw_total_usd": 631_194.03,
            }
        }

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            (out_dir / "official_dashboard.json").write_text(json.dumps({
                "source": "sodex.com/points screenshot",
                "observed_at": "2026-06-18T00:38:55+00:00",
                "weekly_label": "weekly 20 sodex",
                "range": "13 Juni 2026 - 20 Juni 2026",
                "spot_volume_usd": 132_732.25,
                "futures_volume_usd": 15_520.46,
            }))

            official = mon.load_official_dashboard_snapshot(out_dir, window, ledger)

        self.assertEqual(official["quality"], "OK")
        self.assertTrue(official["canonical"])
        self.assertAlmostEqual(official["volume"]["total_usd"], 148_252.71)
        self.assertAlmostEqual(official["reconciliation"]["total_delta_usd"], 482_941.32, places=2)

    def test_persist_report_writes_latest_json_and_jsonl(self):
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            report = {"ts": "2026-06-18T00:00:00+00:00", "status": "OK"}
            latest, history = mon.persist_report(report, out_dir)

            self.assertEqual(json.loads(latest.read_text()), report)
            lines = history.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0]), report)

    def test_api_trade_fee_is_converted_from_fee_coin_to_usd(self):
        from scripts import sodex_monitor_eval as mon

        class FakeApi:
            errors = []

            def get(self, path):
                if path == "/spot/markets/tickers":
                    return {"data": [{"symbol": "vPEPE_vUSDC", "bidPx": "0.000002", "askPx": "0.000004"}]}
                if path == "/perps/markets/tickers":
                    return {"data": []}
                if "/spot/accounts/" in path and path.endswith("/trades"):
                    return {
                        "data": [
                            {
                                "symbol": "vPEPE_vUSDC",
                                "side": "BUY",
                                "price": "0.000003",
                                "quantity": "1000000",
                                "fee": "1000",
                                "feeCoin": "vPEPE",
                                "time": 1781427600000,
                                "isMaker": True,
                            }
                        ]
                    }
                if "/spot/accounts/" in path and path.endswith("/balances"):
                    return {"data": {"balances": []}}
                if "/perps/accounts/" in path and path.endswith("/state"):
                    return {"data": {"av": "0"}}
                if path.endswith("/perps/balances") or path.endswith("/perps/positions"):
                    return {"data": {"balances": [], "positions": []}}
                if path.endswith("/perps/trades") or path.endswith("/perps/fundings"):
                    return {"data": []}
                if path.endswith("/fee-rate"):
                    return {"data": {}}
                return {"data": []}

        window = mon.week_window(datetime(2026, 6, 18, tzinfo=timezone.utc))
        account = mon.aggregate_account("0xabc", window, api=FakeApi())

        self.assertEqual(account["quality"], "OK")
        self.assertEqual(account["api_weekly_activity"]["trade_count_returned_in_window"], 1)
        self.assertAlmostEqual(account["api_weekly_activity"]["trade_fees_returned_usd"], 0.003)

    def test_account_equity_does_not_double_count_locked_spot_balance(self):
        from scripts import sodex_monitor_eval as mon

        class FakeApi:
            errors = []

            def get(self, path):
                if path == "/spot/markets/tickers":
                    return {"data": [{"symbol": "vPEPE_vUSDC", "bidPx": "2", "askPx": "2"}]}
                if path == "/perps/markets/tickers":
                    return {"data": []}
                if "/spot/accounts/" in path and path.endswith("/balances"):
                    return {"data": {"balances": [
                        {"coin": "vPEPE", "total": "100", "locked": "100"},
                    ]}}
                if "/perps/accounts/" in path and path.endswith("/state"):
                    return {"data": {"av": "7"}}
                if path.endswith("/perps/balances") or path.endswith("/perps/positions"):
                    return {"data": {"balances": [], "positions": []}}
                if path.endswith("/trades") or path.endswith("/fundings"):
                    return {"data": []}
                if path.endswith("/fee-rate"):
                    return {"data": {}}
                return {"data": []}

        account = mon.aggregate_account(
            "0xabc",
            mon.week_window(mon.datetime(2026, 7, 8, tzinfo=mon.timezone.utc)),
            api=FakeApi(),
        )

        self.assertEqual(account["account_value"]["spot_equity_usd"], 200.0)
        self.assertEqual(account["account_value"]["total_equity_usd"], 207.0)
        self.assertEqual(account["assets"]["spot"][0]["locked"], 100.0)

    def test_telegram_summary_formats_latest_report(self):
        from scripts import sodex_monitor_eval as mon

        report = {
            "ts": "2026-06-18T00:58:00+00:00",
            "window": {
                "start": "2026-06-13T00:00:00+00:00",
                "end": "2026-06-20T00:00:00+00:00",
                "range": "13 Juni 2026 - 20 Juni 2026",
                "weekly_label": "weekly 20 sodex",
                "snapshot_wib": "20 Juni 2026 07:00 WIB",
            },
            "verdict": {
                "status": "FAIL",
                "reasons": ["weekly_volume_below_target", "volume_fee_ratio_below_target"],
                "progress": {"weekly_volume_pct": 0.486},
            },
            "ledger": {
                "quality": "OK",
                "volume": {
                    "raw_total_usd": 631194.03,
                    "weighted_total_usd": 832991.03,
                    "spot_usd": 201797.0,
                    "perps_usd": 429397.04,
                },
                "pnl": {"realized_net_usd": 31.18359},
                "costs": {"fees_usd": 110.375532},
                "ratios": {"volume_to_fee": 5718.6046},
                "rts": {"count": 7714, "win_rate": 0.91107},
            },
            "account": {
                "quality": "OK",
                "account_value": {
                    "total_equity_usd": 305.74,
                    "free_usd_total": 179.606,
                },
                "assets": {"perps_positions": [{"symbol": "BTC-USD"}]},
            },
        }

        text = mon.format_telegram_report(report)

        self.assertIn("SoDEX Monitoring & Evaluasi", text)
        self.assertIn("13 Juni 2026 - 20 Juni 2026 (weekly 20 sodex)", text)
        self.assertIn("snapshot: 20 Juni 2026 07:00 WIB", text)
        self.assertIn("FAIL", text)
        self.assertIn("$631,194", text)
        self.assertIn("1:5,719", text)
        self.assertIn("91.11%", text)
        self.assertIn("weekly_volume_below_target", text)

    def test_account_position_truth_blocks_positions_endpoint_false_flat(self):
        from scripts import sodex_monitor_eval as mon

        class FakeApi:
            errors: list[str] = []

            def get(self, path):
                if path.endswith("/state"):
                    return {
                        "data": {
                            "av": "100",
                            "P": [
                                {
                                    "s": "SPCX-USD",
                                    "sz": "0.6",
                                    "ep": "160.88",
                                    "ur": "-5.87",
                                    "iw": "19.30",
                                    "l": 5,
                                }
                            ],
                        }
                    }
                if path.endswith("/positions"):
                    return {"data": {"positions": []}}
                if path.endswith("/balances"):
                    return {"data": {"balances": []}}
                if path.endswith("/trades") or path.endswith("/fundings"):
                    return {"data": []}
                if path.endswith("/fee-rate"):
                    return {"data": {}}
                if path.endswith("/tickers"):
                    return {"data": []}
                return {"data": []}

        account = mon.aggregate_account(
            "0xabc",
            mon.week_window(mon.datetime(2026, 7, 8, tzinfo=mon.timezone.utc)),
            api=FakeApi(),
        )

        self.assertEqual(account["position_truth"]["quality"], "DISAGREE")
        self.assertEqual(account["position_truth"]["open_count"], 1)
        self.assertEqual(mon._account_open_position_count(account), 1)

        risk = mon.build_monitor_risk(
            {"quality": "OK", "fills": {"count": 0}, "rts": {"count": 0}},
            account,
            {"quality": "OK", "canonical": True},
            {"alert": False, "reasons": []},
            {"status": "PASS", "reasons": []},
            mon.now_utc(),
        )
        self.assertIn("position_truth_not_verified", {s["name"] for s in risk["signals"]})

    def test_account_position_truth_accepts_flat_state_without_P_field(self):
        from scripts import sodex_monitor_eval as mon

        class FakeApi:
            errors: list[str] = []

            def get(self, path):
                if path.endswith("/state"):
                    return {"data": {"av": "100"}}
                if path.endswith("/positions"):
                    return {"data": {"positions": []}}
                if path.endswith("/balances"):
                    return {"data": {"balances": []}}
                if path.endswith("/trades") or path.endswith("/fundings"):
                    return {"data": []}
                if path.endswith("/fee-rate"):
                    return {"data": {}}
                if path.endswith("/tickers"):
                    return {"data": []}
                return {"data": []}

        account = mon.aggregate_account(
            "0xabc",
            mon.week_window(mon.datetime(2026, 7, 8, tzinfo=mon.timezone.utc)),
            api=FakeApi(),
        )

        self.assertEqual(account["position_truth"]["quality"], "OK")
        self.assertTrue(account["position_truth"]["verified_flat"])
        self.assertEqual(account["position_truth"]["open_count"], 0)

    def test_telegram_summary_separates_official_dashboard_from_internal_ledger(self):
        from scripts import sodex_monitor_eval as mon

        report = {
            "ts": "2026-06-18T00:58:00+00:00",
            "window": {
                "start": "2026-06-13T00:00:00+00:00",
                "end": "2026-06-20T00:00:00+00:00",
                "range": "13 Juni 2026 - 20 Juni 2026",
                "weekly_label": "weekly 20 sodex",
                "snapshot_wib": "20 Juni 2026 07:00 WIB",
            },
            "verdict": {
                "status": "FAIL",
                "reasons": ["weekly_volume_below_target"],
                "warnings": ["official_dashboard_lower_than_internal_ledger"],
                "progress": {
                    "weekly_volume_pct": 0.14825271,
                    "canonical_volume_usd": 148_252.71,
                    "canonical_volume_source": "official_dashboard",
                },
            },
            "official_dashboard": {
                "quality": "OK",
                "canonical": True,
                "volume": {
                    "spot_usd": 132_732.25,
                    "perps_usd": 15_520.46,
                    "total_usd": 148_252.71,
                },
                "reconciliation": {
                    "total_delta_usd": 482_941.32,
                    "spot_delta_usd": 69_064.74,
                    "perps_delta_usd": 413_876.58,
                },
            },
            "ledger": {
                "quality": "OK",
                "volume": {
                    "raw_total_usd": 631_194.03,
                    "weighted_total_usd": 832_991.03,
                    "spot_usd": 201_796.99,
                    "perps_usd": 429_397.04,
                },
                "pnl": {"realized_net_usd": 31.18359},
                "costs": {"fees_usd": 110.375532},
                "ratios": {"volume_to_fee": 5718.6046},
                "rts": {"count": 7714, "win_rate": 0.91107},
            },
            "account": {"quality": "OK", "account_value": {}, "assets": {}},
        }

        text = mon.format_telegram_report(report)

        self.assertIn("Official SoDEX dashboard", text)
        self.assertIn("official total: $148,253", text)
        self.assertIn("spot/futures: $132,732 / $15,520", text)
        self.assertIn("Internal ledger audit", text)
        self.assertIn("ledger total: $631,194", text)
        self.assertIn("delta ledger-official: $482,941", text)

    def test_daemon_sodex_eval_handler_exists(self):
        # /sodex-eval and /sodex-monitor removed from dispatch (old farming commands
        # not aligned with current swing-paper-test / profit-first goals).
        # Handler functions retained for reference; verify they still parse.
        source = Path("anantara/anantara_daemon.py").read_text()
        self.assertIn("async def _cmd_sodex_eval", source)
        self.assertIn("def _sodex_eval_load_latest", source)

    def test_daemon_sodex_ratio_uses_monitor_eval_source(self):
        source = Path("anantara/anantara_daemon.py").read_text()

        self.assertIn("def _sodex_eval_load_latest", source)
        self.assertIn("def _sodex_ratio_report_text", source)
        self.assertIn("_sodex_ratio_report_text()", source)

    def test_monitor_eval_timer_runs_every_five_minutes(self):
        timer = Path("systemd/sodex-monitor-eval.timer").read_text()

        self.assertIn("OnCalendar=*:0/5", timer)
        self.assertIn("RandomizedDelaySec=10", timer)


class E2DirPromotionGateTests(TestCase):
    def _db(self, rows):
        import tempfile, sqlite3
        from datetime import datetime, timezone
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        con = sqlite3.connect(f.name)
        con.execute("CREATE TABLE e2_dir_signals (id INTEGER, pnl TEXT, opened_ts TEXT)")
        for i, (pnl, opened) in enumerate(rows):
            con.execute("INSERT INTO e2_dir_signals (id,pnl,opened_ts) VALUES (?,?,?)",
                        (i, str(pnl), opened))
        con.commit(); con.close()
        return Path(f.name)

    def test_wilson_lower_basic(self):
        from scripts import sodex_monitor_eval as mon
        # 30/50 = 0.60; Wilson lower ~0.46 (below 0.50 floor)
        wl = mon._wilson_lower(30, 50)
        self.assertTrue(0.45 < wl < 0.47, wl)
        self.assertEqual(mon._wilson_lower(0, 0), 0.0)

    def test_not_ready_when_n_below_min(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        fresh = (now - mon.timedelta(hours=1)).isoformat()
        db = self._db([(0.02, fresh)] * 30)  # n=30 < 50
        out = mon.evaluate_e2dir_promotion(db, now)
        self.assertFalse(out["ready"])
        self.assertIn("n_below_min", out["blockers"])

    def test_not_ready_when_stale(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        stale = (now - mon.timedelta(hours=200)).isoformat()  # > 72h
        db = self._db([(0.05, stale)] * 60)
        out = mon.evaluate_e2dir_promotion(db, now)
        self.assertFalse(out["ready"])
        self.assertIn("no_fresh_signals", out["blockers"])

    def test_not_ready_when_ev_negative(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        fresh = (now - mon.timedelta(hours=1)).isoformat()
        # 60 signals, mostly wins but big losers → avg negative
        rows = [(0.01, fresh)] * 55 + [(-1.0, fresh)] * 5
        db = self._db(rows)
        out = mon.evaluate_e2dir_promotion(db, now)
        self.assertFalse(out["ready"])
        self.assertIn("ev_not_positive", out["blockers"])

    def test_ready_when_robust(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        fresh = (now - mon.timedelta(hours=1)).isoformat()
        # 60 signals, 48 wins (80%) all +0.05, 12 losers -0.01 → avg>0, wilson_lo>0.50
        rows = [(0.05, fresh)] * 48 + [(-0.01, fresh)] * 12
        db = self._db(rows)
        out = mon.evaluate_e2dir_promotion(db, now)
        self.assertTrue(out["ready"], out)
        self.assertEqual(out["blockers"], [])
        self.assertEqual(out["n"], 60)
        self.assertGreater(out["wilson_lower"], 0.50)


class EarlyLossDetectionTests(TestCase):
    """Deteksi kerugian sangat dini — per-engine/pair + velocity."""
    def _db(self, rows):
        import tempfile, sqlite3
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False); f.close()
        con = sqlite3.connect(f.name)
        con.execute("CREATE TABLE rts (engine TEXT, pair TEXT, net_pnl TEXT, ts_close TEXT)")
        for eng, pair, pnl, ts in rows:
            con.execute("INSERT INTO rts VALUES (?,?,?,?)", (eng, pair, str(pnl), ts))
        con.commit(); con.close()
        return Path(f.name)

    def test_no_alert_when_profitable(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        recent = (now - mon.timedelta(minutes=10)).isoformat()
        db = self._db([("PVE", "SPCX-USD", 0.5, recent)] * 5)
        out = mon.detect_early_loss(db, now)
        self.assertFalse(out["alert"])

    def test_alert_on_window_loss(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        recent = (now - mon.timedelta(minutes=10)).isoformat()
        db = self._db([("PVE", "SPCX-USD", -1.0, recent)] * 5)  # -$5 window
        out = mon.detect_early_loss(db, now)
        self.assertTrue(out["alert"])
        self.assertTrue(any("window_loss" in r for r in out["reasons"]))

    def test_alert_on_pair_bleeding(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        recent = (now - mon.timedelta(minutes=10)).isoformat()
        db = self._db([("PVE", "CHZ-USD", -2.5, recent), ("PVE", "SPCX-USD", 0.2, recent)])
        out = mon.detect_early_loss(db, now)
        self.assertTrue(out["alert"])
        self.assertEqual(out["worst_pair"]["pair"], "CHZ-USD")

    def test_alert_on_acceleration(self):
        from scripts import sodex_monitor_eval as mon
        now = mon.now_utc()
        recent = (now - mon.timedelta(minutes=10)).isoformat()
        prior = (now - mon.timedelta(minutes=70)).isoformat()
        rows = [("PVE", "SPCX-USD", -4.0, recent)] + [("PVE", "SPCX-USD", 0.1, prior)]
        out = mon.detect_early_loss(self._db(rows), now)
        self.assertTrue(out["alert"])


class SensitiveMonitorRiskTests(TestCase):
    def test_fills_without_rt_and_stale_fill_with_open_position_requires_reconciliation(self):
        from scripts import sodex_monitor_eval as mon

        now = mon.now_utc()
        old = (now - mon.timedelta(minutes=30)).isoformat()
        ledger = {
            "quality": "OK",
            "fills": {"count": 8, "last_ts": old},
            "rts": {"count": 0},
        }
        account = {"quality": "OK", "assets": {"perps_positions": [{"symbol": "SPCX-USD"}]}}
        official = {"quality": "OK", "canonical": True}
        early = {"alert": False, "reasons": []}
        verdict = {"status": "FAIL", "reasons": ["no_closed_rts_this_window"]}

        risk = mon.build_monitor_risk(ledger, account, official, early, verdict, now)
        repair = mon.build_repair_plan(risk, early)

        self.assertEqual(risk["level"], "RED")
        names = {s["name"] for s in risk["signals"]}
        self.assertIn("fills_without_closed_rt", names)
        self.assertIn("stale_last_fill", names)
        self.assertIn("open_positions_with_stale_fills", names)
        self.assertFalse(repair["watchdog_restart_signal"])
        action_types = {a["type"] for a in repair["actions"]}
        self.assertIn("OPERATOR_POSITION_RECONCILIATION_REQUIRED", action_types)
        self.assertIn("RESTART_SUPPRESSED_POSITION_RECONCILE_FIRST", action_types)

    def test_stale_fill_without_open_position_is_observation_not_restart(self):
        from scripts import sodex_monitor_eval as mon

        risk = {
            "signals": [
                {"name": "stale_last_fill", "points": 22},
            ]
        }
        repair = mon.build_repair_plan(risk, {"alert": False})

        self.assertFalse(repair["watchdog_restart_signal"])
        self.assertEqual(repair["actions"][0]["type"], "STALE_FILL_OBSERVED_NO_RESTART")

    def test_fills_without_closed_rt_can_request_watchdog_restart(self):
        from scripts import sodex_monitor_eval as mon

        risk = {
            "signals": [
                {"name": "fills_without_closed_rt", "points": 24},
            ]
        }
        repair = mon.build_repair_plan(risk, {"alert": False})

        self.assertTrue(repair["watchdog_restart_signal"])
        self.assertEqual(repair["actions"][0]["type"], "WATCHDOG_RESTART_SIGNAL")

    def test_halt_suppresses_watchdog_restart_repair_signal(self):
        from scripts import sodex_monitor_eval as mon

        risk = {
            "signals": [
                {"name": "stale_last_fill", "points": 22},
            ]
        }
        repair = mon.build_repair_plan(
            risk,
            {"alert": False},
            {"active": True, "kind": "SAFETY_HALT"},
        )

        self.assertFalse(repair["watchdog_restart_signal"])
        self.assertIn("HALT_ACTIVE_NO_RESTART", {a["type"] for a in repair["actions"]})

    def test_telegram_health_degraded_is_scored(self):
        from scripts import sodex_monitor_eval as mon

        risk = mon.build_monitor_risk(
            {"quality": "OK", "fills": {"count": 1, "last_ts": mon.now_utc().isoformat()}, "rts": {"count": 1}},
            {"quality": "OK", "assets": {"perps_positions": []}},
            {"quality": "OK"},
            {"alert": False, "reasons": []},
            {"status": "PASS", "reasons": []},
            mon.now_utc(),
            {"quality": "DEGRADED", "verdict": "unauthorized_token_rotate_TELEGRAM_BOT_TOKEN"},
        )

        self.assertIn("telegram_alert_channel_degraded", {s["name"] for s in risk["signals"]})

    def test_official_ledger_drift_is_scored_and_refresh_recommended(self):
        from scripts import sodex_monitor_eval as mon

        risk = mon.build_monitor_risk(
            {"quality": "OK", "fills": {"count": 1, "last_ts": mon.now_utc().isoformat()}, "rts": {"count": 1}},
            {"quality": "OK", "assets": {"perps_positions": []}},
            {"quality": "OK", "reconciliation": {"total_delta_usd": 5000, "ledger_over_official_multiple": 3.0}},
            {"alert": False, "reasons": []},
            {"status": "PASS", "reasons": []},
            mon.now_utc(),
        )
        repair = mon.build_repair_plan(risk, {"alert": False})

        self.assertIn("official_ledger_drift", {s["name"] for s in risk["signals"]})
        self.assertIn("REFRESH_OFFICIAL_DASHBOARD_SNAPSHOT", {a["type"] for a in repair["actions"]})

    def test_build_report_contains_monitor_risk_and_repair_plan(self):
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "twin.db"
            con = sqlite3.connect(db_path)
            con.executescript(
                """
                CREATE TABLE fills(ts TEXT, engine TEXT, bucket TEXT, pair TEXT, side TEXT,
                  price TEXT, qty TEXT, notional TEXT, fee TEXT, maker INTEGER, rt_id TEXT);
                CREATE TABLE rts(rt_id TEXT, ts_close TEXT, engine TEXT, pair TEXT, volume TEXT, net_pnl TEXT);
                """
            )
            con.commit(); con.close()
            report = mon.build_report(db_path=db_path, out_dir=Path(td), no_api=True, at=mon.now_utc())

        self.assertIn("monitor_risk", report)
        self.assertIn("repair_plan", report)
        self.assertIn("telegram_health", report)
        self.assertEqual(report["repair_plan"]["mode"], "READ_ONLY_REPAIR_PLAN")


class LedgerAuditGuardTests(TestCase):
    """Penjaga integritas ledger (30-Sep-2026) — metrik hanya dari RT TERAUDIT.

    Insiden: penghitung RT (`_rt`) di-reset ke 0 di setiap sesi sementara
    `rt_close` memakai INSERT OR REPLACE pada PK `rt_id` → ID didaur ulang, baris
    historis tertimpa, dan `ts_close` (diisi now()) membuat baris lama masuk ke
    window metrik sekarang. Terukur di window 26-Sep→3-Okt: 325 baris dipakai
    verdict, 324 di antaranya fill-nya bertanggal Juni → WR 29,23% (95/325) palsu;
    sampel yang benar-benar sah = 0.

    Kontrak penjaga: sebuah RT hanya dihitung bila minimal satu fill-nya
    bertimestamp DI DALAM window. RT yang tak bisa diverifikasi dikeluarkan dan
    dilaporkan lewat `excluded_unverifiable` + warning — bukan didiamkan.
    """

    WINDOW_START = datetime(2026, 9, 26, tzinfo=timezone.utc)
    WINDOW_END = datetime(2026, 10, 3, tzinfo=timezone.utc)

    def _mk_db(self, td: str) -> tuple[Path, sqlite3.Connection]:
        db_path = Path(td) / "twin.db"
        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE fills(
              id INTEGER PRIMARY KEY, ts TEXT NOT NULL, engine TEXT NOT NULL,
              bucket TEXT NOT NULL, pair TEXT NOT NULL, side TEXT NOT NULL,
              price TEXT NOT NULL, qty TEXT NOT NULL, notional TEXT NOT NULL,
              fee TEXT NOT NULL, maker INTEGER NOT NULL, rt_id TEXT);
            CREATE TABLE rts(
              rt_id TEXT PRIMARY KEY, ts_close TEXT, engine TEXT, pair TEXT,
              volume TEXT, net_pnl TEXT);
            """
        )
        return db_path, con

    def _seed_contaminated(self, con: sqlite3.Connection) -> None:
        """1 RT teraudit + 1 RT daur-ulang (fill Juni) + 1 RT tanpa fill."""
        con.executemany(
            "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                # fill SAH: di dalam window, terikat ke E1-1
                ("2026-09-28T10:00:00+00:00", "E1", "S", "PEPE/USDC", "sell", "1", "1", "10", "0.01", 1, "E1-1"),
                # fill milik RT daur-ulang: bertanggal JUNI (di luar window)
                ("2026-06-12T03:43:00+00:00", "E1", "S", "PEPE/USDC", "sell", "1", "1", "10", "0.01", 1, "E1-2"),
            ],
        )
        con.executemany(
            "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
            [
                ("E1-1", "2026-09-28T10:00:00+00:00", "E1", "PEPE/USDC", "10", "0.5"),
                # nilai nyata sesi September, tetapi ID-nya milik baris Juni (daur ulang)
                ("E1-2", "2026-09-28T12:55:00+00:00", "E1", "PEPE/USDC", "99", "-9.9"),
                # tanpa fill sama sekali → tak terverifikasi
                ("E1-3", "2026-09-28T13:00:00+00:00", "E1", "PEPE/USDC", "50", "-5.0"),
            ],
        )
        con.commit()

    def _agg(self, td: str):
        from scripts import sodex_monitor_eval as mon

        db_path, con = self._mk_db(td)
        self._seed_contaminated(con)
        con.close()
        return mon, mon.aggregate_ledger(
            db_path, mon.WeekWindow(start=self.WINDOW_START, end=self.WINDOW_END))

    def test_rt_daur_ulang_dan_tanpa_fill_tidak_dihitung(self):
        """Skenario insiden: hanya RT yang fill-nya di dalam window yang masuk."""
        with tempfile.TemporaryDirectory() as td:
            mon, agg = self._agg(td)

        self.assertEqual(agg["quality"], "OK")
        self.assertEqual(agg["rts"]["count"], 1, "hanya RT teraudit yang dihitung")
        self.assertEqual(agg["rts"]["excluded_unverifiable"], 2)
        self.assertEqual(agg["rts"]["wins"], 1)
        self.assertEqual(agg["rts"]["win_rate"], 1.0)
        self.assertEqual(agg["pnl"]["realized_net_usd"], 0.5,
                         "PnL baris daur-ulang tidak boleh masuk")
        self.assertTrue(agg["rts"]["audited_only"])
        self.assertIn("rt_rows_unverifiable_excluded:2", agg["warnings"])

    def test_penjaga_tidak_menyentuh_metrik_fills(self):
        """Penjaga hanya menyaring tabel rts — fill/volume tetap apa adanya."""
        with tempfile.TemporaryDirectory() as td:
            _mon, agg = self._agg(td)

        self.assertEqual(agg["fills"]["count"], 1, "hanya fill di dalam window")
        self.assertEqual(agg["volume"]["raw_total_usd"], 10.0)

    def test_coverage_engine_tidak_tercemar_baris_palsu(self):
        """`by_engine_rt` (internal) menyuplai coverage → harus ikut terjaga.

        Tanpa penjaga, PnL palsu (−9,9 / −5,0) masuk ke `e1_realized_pnl` sehingga
        `combined_no_loss` salah menuduh rugi — persis yang terjadi di window nyata.
        """
        with tempfile.TemporaryDirectory() as td:
            _mon, agg = self._agg(td)

        cov = agg["coverage"]
        self.assertEqual(cov["e1_realized_pnl"], 0.5,
                         "PnL palsu (−14,9) tidak boleh masuk coverage engine")
        self.assertTrue(cov["combined_no_loss"],
                        "tidak boleh menuduh rugi dari baris palsu")
        self.assertTrue(cov["e1_covers_e2_fees"])

    def test_verdict_tidak_menuduh_pnl_negatif_dari_baris_palsu(self):
        """Keputusan: alasan palsu realized/combined_pnl_negative tidak muncul lagi."""
        with tempfile.TemporaryDirectory() as td:
            mon, agg = self._agg(td)
            window = mon.WeekWindow(start=self.WINDOW_START, end=self.WINDOW_END)
            verdict = mon.evaluate(window, agg, {"quality": "OK"})

        self.assertNotIn("realized_pnl_negative", verdict["reasons"],
                         "PnL negatif hanya berasal dari baris daur-ulang")
        self.assertNotIn("combined_pnl_negative", verdict["reasons"])
        self.assertNotIn("e1_profit_does_not_cover_e2_fees", verdict["reasons"])
        # 1 RT sah PnL +0,5 → WR 100% → tidak ada alasan WR sama sekali
        self.assertNotIn("weekly_win_rate_below_target", verdict["reasons"])
        self.assertNotIn("weekly_win_rate_missing", verdict["reasons"])

    def test_semua_baris_palsu_menghasilkan_wr_tak_terukur(self):
        """Kasus nyata window 26-Sep→3-Okt: SEMUA baris tak teraudit → WR None.

        Verdict harus jujur berkata "tak ada sampel", bukan mengklaim WR rendah.
        """
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            db_path, con = self._mk_db(td)
            con.executemany(
                "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [("2026-06-12T03:43:00+00:00", "E1", "S", "PEPE/USDC", "sell",
                  "1", "1", "10", "0.01", 1, "E1-2")],
            )
            con.executemany(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                [("E1-2", "2026-09-28T12:55:00+00:00", "E1", "PEPE/USDC", "99", "-9.9")],
            )
            con.commit()
            con.close()

            window = mon.WeekWindow(start=self.WINDOW_START, end=self.WINDOW_END)
            agg = mon.aggregate_ledger(db_path, window)
            verdict = mon.evaluate(window, agg, {"quality": "OK"})

        self.assertEqual(agg["rts"]["count"], 0)
        self.assertIsNone(agg["rts"]["win_rate"])
        self.assertEqual(agg["rts"]["excluded_unverifiable"], 1)
        self.assertEqual(agg["pnl"]["realized_net_usd"], 0.0)
        self.assertIn("weekly_win_rate_missing", verdict["reasons"])
        self.assertNotIn("weekly_win_rate_below_target", verdict["reasons"])
        self.assertNotIn("realized_pnl_negative", verdict["reasons"])

    def test_alarm_gap_pakai_hitungan_mentah_bukan_teraudit(self):
        """Alarm `fills_without_closed_rt` menanyakan "apakah RT DICATAT?", bukan
        "berapa yang teraudit".

        Regresi nyata 30-Sep: penjaga membuat `rt_count` 325→0 sehingga alarm gap
        menyala dan skor risiko naik 60→90 (RED) padahal pencatatan RT berjalan.
        """
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            db_path, con = self._mk_db(td)
            # 6 fill di dalam window TANPA rt_id (tak terikat round-trip)
            con.executemany(
                "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(f"2026-09-28T10:0{i}:00+00:00", "E1", "S", "PEPE/USDC", "buy",
                  "1", "1", "10", "0.01", 1, None) for i in range(6)],
            )
            # 1 baris RT: ts_close di window, fill-nya Juni → TIDAK teraudit
            con.execute(
                "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-06-12T03:43:00+00:00", "E1", "S", "PEPE/USDC", "sell",
                 "1", "1", "10", "0.01", 1, "E1-9"),
            )
            con.execute(
                "INSERT INTO rts(rt_id,ts_close,engine,pair,volume,net_pnl) VALUES(?,?,?,?,?,?)",
                ("E1-9", "2026-09-28T11:00:00+00:00", "E1", "PEPE/USDC", "10", "0.1"),
            )
            con.commit()
            con.close()

            agg = mon.aggregate_ledger(
                db_path, mon.WeekWindow(start=self.WINDOW_START, end=self.WINDOW_END))
            risk = mon.build_monitor_risk(
                agg, {"quality": "DISABLED"}, {}, {}, {"status": "FAIL", "reasons": []},
                now=datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
            names = [s["name"] for s in risk["signals"]]

        self.assertEqual(agg["fills"]["count"], 6)
        self.assertEqual(agg["rts"]["count"], 0, "tak ada RT teraudit")
        self.assertEqual(agg["rts"]["excluded_unverifiable"], 1)
        self.assertNotIn("fills_without_closed_rt", names,
                         "RT tetap tercatat → alarm gap tidak boleh menyala")

    def test_alarm_gap_tetap_menyala_bila_nol_benar_benar(self):
        """Kontrol negatif: tanpa baris RT sama sekali, alarm HARUS menyala.

        Membuktikan perbaikan di atas tidak sekadar mematikan alarm.
        """
        from scripts import sodex_monitor_eval as mon

        with tempfile.TemporaryDirectory() as td:
            db_path, con = self._mk_db(td)
            con.executemany(
                "INSERT INTO fills(ts,engine,bucket,pair,side,price,qty,notional,fee,maker,rt_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(f"2026-09-28T10:0{i}:00+00:00", "E1", "S", "PEPE/USDC", "buy",
                  "1", "1", "10", "0.01", 1, None) for i in range(6)],
            )
            con.commit()
            con.close()

            agg = mon.aggregate_ledger(
                db_path, mon.WeekWindow(start=self.WINDOW_START, end=self.WINDOW_END))
            risk = mon.build_monitor_risk(
                agg, {"quality": "DISABLED"}, {}, {}, {"status": "FAIL", "reasons": []},
                now=datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
            names = [s["name"] for s in risk["signals"]]

        self.assertEqual(agg["rts"]["count"], 0)
        self.assertEqual(agg["rts"]["excluded_unverifiable"], 0)
        self.assertIn("fills_without_closed_rt", names,
                      "6 fill tanpa satu pun baris RT = gap nyata → alarm wajib menyala")
