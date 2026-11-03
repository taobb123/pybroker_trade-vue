# -*- coding: utf-8 -*-
"""题材复盘：精确匹配、0.52 门槛、六组合只标注。不写观察池。"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capm.sources import OHLC_CACHE
from theme_review import (
    _load_bars,
    collect_members,
    combo_from_turnover,
    list_concepts,
    match_concepts,
    parse_themes,
    review_themes,
)
from theme_review_api import router


def _bars(symbols: list[str], rows: int = 90) -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        dates = pd.bdate_range("2025-12-01", periods=rows)
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10.0,
                    "volume": 1000.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


class ParseMatchTest(unittest.TestCase):
    def test_parse_keeps_order_and_drops_duplicates(self) -> None:
        self.assertEqual(parse_themes("脑机接口，脑机接口\n三季报增长"), ["脑机接口", "三季报增长"])

    def test_exact_name_match(self) -> None:
        index = pd.DataFrame(
            {
                "ts_code": ["BK0001.DC", "BK0002.DC"],
                "name": ["脑机接口", "三季报增长"],
            }
        )
        matched, missing = match_concepts(["脑机接口", "食品饮料"], index)
        self.assertEqual(matched, [{"name": "脑机接口", "ts_code": "BK0001.DC"}])
        self.assertEqual(missing, ["食品饮料"])

    def test_members_merge_themes(self) -> None:
        matched = [
            {"name": "脑机接口", "ts_code": "BK1"},
            {"name": "三季报增长", "ts_code": "BK2"},
        ]
        members = pd.DataFrame(
            {
                "concept_code": ["BK1", "BK1", "BK2"],
                "con_code": ["002172.SZ", "300433.SZ", "002172.SZ"],
                "con_name": ["澳洋健康", "蓝思科技", "澳洋健康"],
            }
        )
        rows = collect_members(matched, members)
        self.assertEqual([row["symbol"] for row in rows], ["002172", "300433"])
        self.assertEqual(rows[0]["themes"], ["脑机接口", "三季报增长"])
        self.assertEqual(matched[0]["member_count"], 2)
        self.assertEqual(matched[1]["member_count"], 1)


class ReviewTest(unittest.TestCase):
    def test_keeps_threshold_and_labels_combo_without_writing(self) -> None:
        index = pd.DataFrame({"ts_code": ["BK1"], "name": ["脑机接口"]})
        members = pd.DataFrame(
            {
                "concept_code": ["BK1", "BK1", "BK1"],
                "con_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "con_name": ["甲", "乙", "丙"],
            }
        )
        seen: list[str] = []

        def score(frame, template):
            del template
            symbol = str(frame["symbol"].iloc[0])
            related = symbol == "000001"
            return {
                "similarity": 0.52 if related else 0.51,
                "spiral": 0.8,
                "price": 0.8,
                "volume": 0.8,
                "yang": 0.8,
                "yang_n": 3,
                "vr": 3.0,
                "related": related,
                "reason": "",
            }

        def combos(rows):
            seen.extend(row["symbol"] for row in rows)
            return {"000001": ("上涨放量突破", "")}

        def bars(_symbols):
            return pd.concat([_bars(["000001", "000002"], 90), _bars(["000003"], 10)], ignore_index=True)

        with patch("theme_review.score_frame", score):
            payload = review_themes(
                "脑机接口，食品饮料",
                index_loader=lambda: ("20261103", index),
                member_loader=lambda trade_date, codes: members,
                bars_loader=bars,
                combo_loader=combos,
            )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["empty"])
        report = payload["report"]
        self.assertEqual([row["symbol"] for row in report["rows"]], ["000001"])
        self.assertEqual(report["rows"][0]["similarity"], 0.52)
        self.assertEqual(report["rows"][0]["combo_name"], "上涨放量突破")
        self.assertEqual(report["rows"][0]["themes"], "脑机接口")
        self.assertEqual(seen, ["000001"])
        self.assertNotIn("000002", [row["symbol"] for row in report["rows"]])
        self.assertNotIn("000003", [row["symbol"] for row in report["rows"]])
        self.assertTrue(any("食品饮料" in note for note in report["notes"]))
        self.assertTrue(any("日线不足" in note for note in report["notes"]))

    def test_blank_combo_when_turnover_missing(self) -> None:
        name, note = combo_from_turnover("下跌放量", float("nan"))
        self.assertEqual(name, "")
        self.assertIn("换手率", note)
        kept, kept_note = combo_from_turnover("下跌放量", 1.2)
        self.assertEqual((kept, kept_note), ("下跌放量", ""))
        self.assertTrue(math.isnan(float("nan")))

    def test_module_does_not_export_watch_pool(self) -> None:
        text = Path(__file__).with_name("theme_review.py").read_text(encoding="utf-8")
        self.assertNotIn("export_combo_watch_lists", text)
        self.assertNotIn("to_csv", text)


class ConceptListTest(unittest.TestCase):
    def test_unique_sorted_names(self) -> None:
        index = pd.DataFrame({"name": ["脑机接口", "脑机接口", " ", "三季报增长", None]})
        payload = list_concepts(index, "20261103")
        self.assertEqual(payload["names"], ["三季报增长", "脑机接口"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["trade_date"], "20261103")


class LoadBarsTest(unittest.TestCase):
    def test_store_ohlc_gets_cache_path(self) -> None:
        short = _bars(["003006"], rows=10)
        full = _bars(["003006", "002172"])
        with (
            patch("theme_review.load_ohlc", side_effect=[short, full]),
            patch("theme_review.fetch_act_bars", return_value=full),
            patch("theme_review.store_ohlc") as store,
        ):
            out = _load_bars(["002172"])
        self.assertEqual(store.call_args.args[1], OHLC_CACHE)
        self.assertEqual(set(out["symbol"]), {"003006", "002172"})


class ApiTest(unittest.TestCase):
    def test_post_uses_live_entry(self) -> None:
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        sample = {
            "ok": True,
            "empty": False,
            "error": None,
            "message": None,
            "report": {"rows": [{"symbol": "000001"}]},
        }
        with patch("theme_review_api.review_themes_live", return_value=sample) as live:
            response = client.post("/api/theme-review", json={"themes": "脑机接口"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"]["rows"][0]["symbol"], "000001")
        live.assert_called_once_with("脑机接口")

    def test_get_concepts_uses_live_catalog(self) -> None:
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        sample = {"ok": True, "names": ["脑机接口"], "count": 1, "trade_date": "20261103"}
        with patch("theme_review_api.list_concepts_live", return_value=sample) as live:
            response = client.get("/api/theme-review/concepts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["names"], ["脑机接口"])
        live.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
