from __future__ import annotations

import unittest
from dataclasses import replace
from unittest import mock
import urllib.error

from anantara.sodex_twin_engine import Config, Telegram


class TestTelegramGuard(unittest.TestCase):

    def test_invalid_token_format_disables_notifier(self):
        cfg = replace(Config(), tg_token="not-a-token", tg_chat="12345")
        tg = Telegram(cfg)
        self.assertFalse(tg.ok)
        self.assertEqual(tg.health()["disabled_reason"], "invalid_token_format")

    def test_unauthorized_disables_after_first_send(self):
        cfg = replace(
            Config(),
            tg_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
            tg_chat="12345",
        )
        tg = Telegram(cfg)
        err = urllib.error.HTTPError(
            url=tg.url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            tg.send("hello")
        self.assertFalse(tg.ok)
        self.assertEqual(
            tg.health()["disabled_reason"],
            "unauthorized_token_rotate_TELEGRAM_BOT_TOKEN",
        )


if __name__ == "__main__":
    unittest.main()
