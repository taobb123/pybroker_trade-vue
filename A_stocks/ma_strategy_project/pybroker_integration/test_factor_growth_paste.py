# -*- coding: utf-8 -*-
"""粘贴代码只写独立排序表，不进入分组综合表。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import factor_growthT_indicator as growth


class PastedSymbolsTests(unittest.TestCase):
    def test_empty_paste_does_not_rank(self):
        with patch.object(growth, "rank_symbols_by_growth") as rank:
            code = growth.run_pasted_symbols(["", "  "])
        self.assertEqual(code, 2)
        rank.assert_not_called()

    def test_paste_writes_its_own_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_csv = os.path.join(tmp, "paste.csv")
            combined = os.path.join(tmp, "combined.csv")
            growth._save_ranking_csv(
                [{"分组": "Q", "排名": 1, "股票代码": "600519", "总分": 2.0}],
                combined,
            )
            with open(combined, encoding="utf-8-sig") as handle:
                before = handle.read()

            def fake_rank(symbols):
                details = {
                    symbols[0]: {
                        "total_score": 9.0,
                        "layer1_score": 1.0,
                        "layer2_score": 2.0,
                        "layer3_score": 3.0,
                        "layer4_score": 4.0,
                    }
                }
                return list(symbols), details, {symbols[0]: 9.0}

            with patch.object(growth, "rank_symbols_by_growth", side_effect=fake_rank), patch.object(
                growth, "get_stock_names", return_value={"002821": "示例"}
            ), patch.object(growth, "get_stock_industries", return_value={"002821": ""}):
                code = growth.run_pasted_symbols(["002821"], ranking_file=out_csv)

            self.assertEqual(code, 0)
            with open(out_csv, encoding="utf-8-sig") as handle:
                text = handle.read()
            self.assertIn("002821", text)
            self.assertIn("示例", text)
            self.assertNotIn("分组", text)
            with open(combined, encoding="utf-8-sig") as handle:
                self.assertEqual(handle.read(), before)


if __name__ == "__main__":
    unittest.main()
