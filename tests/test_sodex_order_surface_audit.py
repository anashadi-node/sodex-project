from unittest import TestCase


class SodexOrderSurfaceAuditTests(TestCase):
    def test_all_current_order_surfaces_are_guarded_or_disabled(self):
        from scripts import sodex_order_surface_audit as audit

        report = audit.build_report()

        self.assertEqual(report["status"], "OK", report)
        self.assertEqual(report["bad_count"], 0, report)

    def test_audit_tracks_the_known_live_order_surface_set(self):
        from scripts import sodex_order_surface_audit as audit

        report = audit.build_report()
        surfaces = {row["file"]: row["status"] for row in report["surfaces"]}

        # anantara_daemon.py no longer has direct order-place surface (uses sf.cli for balance only)
        self.assertEqual(surfaces["anantara/sodex_autofarm.py"], "GUARDED")
        self.assertEqual(surfaces["scripts/sodex_micro_pilot.py"], "GUARDED")
        self.assertEqual(surfaces["scripts/spcx_tournament.py"], "GUARDED")
        self.assertEqual(surfaces["anantara/sodex_spot_farm.py"], "DEPRECATED_DISABLED")
        self.assertEqual(surfaces["anantara/sodex_farming.py"], "GUARDED")
        self.assertEqual(surfaces["anantara/sodex_directional.py"], "GUARDED")
        self.assertEqual(surfaces["anantara/sodex_twin_engine.py"], "GUARDED")
