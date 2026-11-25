import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import paper_test_swing as swing


class TestSwingDataSafety(unittest.TestCase):
    def _rows(self, n=25):
        return [[0, "1", "2", "0.5", "1.5", "10"] for _ in range(n)]

    def test_hype_falls_back_from_spot_to_futures(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def json(self):
                return self.payload

        def fake_get(url, params, timeout):
            if "api/v3" in url:
                return Response({"code": -1121, "msg": "Invalid symbol."})
            return Response(self._rows())

        with patch.object(swing.requests, "get", side_effect=fake_get):
            self.assertEqual(len(swing._fetch_binance_klines("HYPEUSDT", "1h", 25)), 25)

    def test_confirmation_fails_closed_on_api_failure(self):
        with patch.object(swing, "_fetch_binance_klines", side_effect=RuntimeError("down")):
            self.assertFalse(swing._confirm_15m("HYPE"))

    def test_confirmation_rejects_insufficient_bars(self):
        with patch.object(swing, "_fetch_binance_klines", return_value=self._rows(10)):
            self.assertFalse(swing._confirm_15m("BTC"))


if __name__ == "__main__":
    unittest.main()
