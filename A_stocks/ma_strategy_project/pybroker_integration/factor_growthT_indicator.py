#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据需求完成新的跟踪成长趋势的评分筛选逻辑
很好，你现在的方向非常清晰：

> ✅ 低风险资产结构
> ✅ 稳定真实现金流
> ✅ 高且持续的毛利率

你现有系统里已经有：

* ROE
* 自由现金流率
* 收入增长
* 利润增长
* 毛利率
* ROA
* 负债率
* 加权得分

但如果目标是“资产负债健康 + 现金流稳定 + 毛利率持续性”，
目前还缺少几个非常关键的“趋势型指标”。

下面我给你一个**最优增强方案（按重要性排序）**。

---

# 一、资产负债结构：不仅要低负债，还要安全结构

你现在只有：

> 负债率

这远远不够。

建议新增 3 个核心指标：

---

## ① 有息负债率（比总负债更重要）

```text
有息负债率 = 有息负债 / 总资产
```

原因：

* 应付账款不危险
* 有息债务才危险

很多公司负债率 60%，
但有息负债只有 10%，其实很安全。

---

## ② 利息保障倍数（防雷核心）

```text
利息保障倍数 = EBIT / 利息费用
```

> <3 危险
>
> > 5 安全
> > 10 极安全

---

## ③ 现金覆盖率

```text
现金 + 交易性金融资产 / 有息负债
```

如果 >1

说明公司理论上可立刻还清债务。

---

# 二、现金流稳定性（这是你现在最大缺失）

你有“自由现金流率”，但没有“稳定性”。

建议新增：

---

## ④ FCF 连续为正年数

统计：

过去 5 年 FCF > 0 的年数

优质公司：

> ≥4 年

---

## ⑤ 经营现金流/净利润（利润质量）

```text
OCF / NetIncome
```

长期应 > 1

---

## ⑥ 现金流波动率（趋势指标）

```text
FCF 5年标准差 / FCF平均值
```

越低越稳定。

---

# 三、毛利率“持续性”是关键

你现在只有“毛利率当前值”。

但真正强公司：

毛利率稳定 + 趋势向上。

必须增加：

---

## ⑦ 毛利率 5年标准差

```text
毛利率_std_5Y
```

越低越好。

---

## ⑧ 毛利率趋势（斜率）

用线性回归：

```text
毛利率_t = a + b * 时间
```

b > 0 说明提升。

---

## ⑨ 毛利率相对行业溢价

```text
毛利率 - 行业平均毛利率
```

否则你会选到：

低毛利行业的“好学生”。

---

# 四、你提到：收入大于存货

非常聪明。

这是一个“需求强度 + 存货压力”指标。

建议加入：

---

## ⑩ 存货周转率

```text
存货周转率 = 营业成本 / 平均存货
```

越高越好。

---

## ⑪ 存货增长率 vs 收入增长率

```text
存货增长 - 收入增长
```

如果：

存货增长 > 收入增长

说明卖不动。

优质公司：

收入增长 ≥ 存货增长。

---

# 五、结合你现有系统，升级为“稳健高质量模型”

你现在可以重构评分逻辑：

---

# 模型升级结构

## 第一层：资产安全（25%）

* 有息负债率（负向）
* 利息保障倍数
* 现金覆盖率
* 负债率趋势

---

## 第二层：现金流质量（30%）

* FCF连续为正年数
* OCF/NI
* FCF波动率（负向）
* FCF增长率

---

## 第三层：盈利质量（30%）

* ROE
* ROA
* 毛利率
* 毛利率_std（负向）
* 毛利率趋势

---

## 第四层：运营效率（15%）

* 存货周转率
* 存货增长 - 收入增长（负向）

---

# 六、真正优质公司的财务特征

长期顶级公司通常表现为：

* 毛利率稳定且缓慢提升
* FCF稳定为正
* OCF > 净利润
* 有息负债极低
* 存货周转持续优化

---

# 七、如果你只允许加 5 个指标

最优组合：

1. 有息负债率
2. 利息保障倍数
3. FCF连续为正年数
4. 毛利率5年标准差
5. 存货增长 - 收入增长

这 5 个会极大提升你模型质量。

---

# 八、你现在模型的定位

你现在在构建的是：

> “稳健型高质量复利模型”

这类公司：

* 不暴涨
* 不暴雷
* 长期稳步上行

这比纯成长模型更适合长期持有。

---

如果你愿意，我可以：

* 给你一个完整的“稳健高质量公司评分公式”
* 或帮你重构一个 0-100 分的质量打分系统
* 或帮你设计一个“趋势可视化雷达图系统”

你现在已经在向“机构级基本面选股体系”进阶了。

"""

from __future__ import annotations

import argparse
import os
import sys
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Sequence, Tuple
from datetime import datetime, timedelta

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.steady_quality_financial import build_steady_quality_scores
from pybroker_integration.mx_self_select import (
    DEFAULT_MX_GROUPS_DIR,
    group_txt_path,
    load_group_symbols_txt,
    replace_group_symbols,
)

# pybroker / 自定义行情源仅回测路径需要；排序推送勿在 import 时加载，
# 否则会写缓存目录并拖垮 uvicorn --reload，前端轮询变成 Failed to fetch。


def _pyb():
    import pybroker as pyb

    return pyb


# ==================== 稳健型高质量四层评分逻辑（见文件头注释） ====================

def _ensure_quality_rank_params():
    pyb = _pyb()
    if pyb.param('top_10_pct_symbols') is not None:
        return
    symbols = pyb.param('symbols_for_quality')
    if not symbols:
        pyb.param('top_10_pct_symbols', [])
        pyb.param('factor_scores', {})
        pyb.param('factor_details', {})
        pyb.param('target_symbols', [])
        return
    print("  正在使用 Tushare 财务三表计算稳健高质量四层评分...")
    df_scores, top_10_pct, factor_details = build_steady_quality_scores(
        symbols, min_valid_indicators=5
    )
    factor_scores = df_scores.set_index('symbol')['total_score'].to_dict() if not df_scores.empty else {}
    top_n = pyb.param('top_n', 10)
    target_symbols = top_10_pct[:top_n]
    pyb.param('top_10_pct_symbols', top_10_pct)
    pyb.param('factor_scores', factor_scores)
    pyb.param('factor_details', factor_details)
    pyb.param('target_symbols', target_symbols)


def rank_stocks_by_quality(ctxs: Dict[str, Any]) -> List[str]:
    pyb = _pyb()
    _ensure_quality_rank_params()
    return pyb.param('top_10_pct_symbols') or []


def execute_quality_strategy(ctx: Any):
    pyb = _pyb()
    target_symbols = pyb.param('target_symbols')
    if target_symbols is None or len(target_symbols) == 0:
        return
    factor_scores = pyb.param('factor_scores') or {}
    try:
        if ctx.long_pos():
            if ctx.symbol not in target_symbols:
                ctx.sell_all_shares()
        else:
            if ctx.symbol in target_symbols:
                rank = target_symbols.index(ctx.symbol) + 1
                top_n = len(target_symbols)
                weight = (top_n - rank + 1) / sum(range(1, top_n + 1))
                ctx.buy_shares = ctx.calc_target_shares(weight)
                ctx.score = factor_scores.get(ctx.symbol, 0.0)
    except Exception as e:
        print(f"⚠ 警告: {ctx.symbol} 策略执行异常: {e}")


def load_stock_pool(file_path: str) -> List[str]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            symbols = [s.strip() for s in content.replace('\n', ' ').split() if s.strip()]
            return symbols
    except Exception as e:
        print(f"✗ 加载股票池失败: {e}")
        return []


def get_stock_names(symbols: List[str]) -> Dict[str, str]:
    """使用 Tushare Pro stock_basic 批量获取股票名称，返回 {代码: 名称}。"""
    result = {s: s for s in symbols}
    try:
        from config.settings import DATA_CONFIG
        token = (DATA_CONFIG or {}).get("tushare_token", "") or ""
        if not token:
            return result
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        if df is None or df.empty:
            return result
        code_to_name = {}
        for _, row in df.iterrows():
            ts_code = row['ts_code']
            name = row['name']
            code = str(ts_code).split('.')[0]
            code_to_name[code] = name
            code_to_name[ts_code] = name
        for sym in symbols:
            code = sym.strip()
            if len(code) == 6 and code.isdigit():
                result[sym] = code_to_name.get(code, sym)
            else:
                result[sym] = code_to_name.get(sym, sym)
    except Exception as e:
        print(f"⚠ 获取股票名称失败: {e}，将使用代码显示")
    return result


def get_stock_industries(symbols: List[str]) -> Dict[str, str]:
    """使用 Tushare Pro stock_basic 批量获取股票行业信息，返回 {代码: 行业名称}。"""
    result = {s: "" for s in symbols}
    try:
        from config.settings import DATA_CONFIG
        token = (DATA_CONFIG or {}).get("tushare_token", "") or ""
        if not token:
            return result
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        # 同时尝试读取通用 industry 字段和分级行业字段
        df = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,industry,industry_l1,industry_l2,industry_l3'
        )
        if df is None or df.empty:
            return result
        code_to_industry = {}
        for _, row in df.iterrows():
            ts_code = row['ts_code']
            code = str(ts_code).split('.')[0]
            # 优先使用更标准的一级行业，其次回退到旧的 industry 字段
            industry = (
                row.get('industry_l1')
                or row.get('industry')
                or ''
            )
            code_to_industry[code] = industry
            code_to_industry[ts_code] = industry
        for sym in symbols:
            code = sym.strip()
            if len(code) == 6 and code.isdigit():
                result[sym] = code_to_industry.get(code, "")
            else:
                result[sym] = code_to_industry.get(sym, "")
    except Exception as e:
        print(f"⚠ 获取股票行业失败: {e}，将返回空行业字段")
    return result


def _rank_symbols_keep_all(
    symbols: Sequence[str],
) -> Tuple[List[str], Dict[str, Dict], Dict[str, float]]:
    """组内打分排序；财务不足的票排在末尾，避免把手改名单丢掉。"""
    uniq: List[str] = []
    seen = set()
    for raw in symbols:
        s = "".join(ch for ch in str(raw) if ch.isdigit()).zfill(6)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    if not uniq:
        return [], {}, {}
    df_scores, _top, details = build_steady_quality_scores(uniq, min_valid_indicators=5)
    factor_scores = (
        df_scores.set_index("symbol")["total_score"].to_dict() if not df_scores.empty else {}
    )
    ranked: List[str] = []
    have = set()
    if not df_scores.empty:
        for _, r in df_scores.sort_values("total_score", ascending=False).iterrows():
            sym = str(r["symbol"])
            ranked.append(sym)
            have.add(sym)
    ranked.extend([s for s in uniq if s not in have])
    return ranked, details or {}, factor_scores


def _ranking_rows(
    group_name: str,
    ranked: Sequence[str],
    details: Dict[str, Dict],
    names: Dict[str, str],
    industries: Dict[str, str],
) -> List[dict]:
    rows = []
    for i, symbol in enumerate(ranked, 1):
        d = details.get(symbol, {})
        rows.append(
            {
                "分组": group_name,
                "排名": i,
                "股票代码": symbol,
                "股票名称": names.get(symbol, symbol),
                "行业": industries.get(symbol, ""),
                "总分": d.get("total_score"),
                "资产安全得分": d.get("layer1_score"),
                "现金流质量得分": d.get("layer2_score"),
                "盈利质量得分": d.get("layer3_score"),
                "运营效率得分": d.get("layer4_score"),
            }
        )
    return rows


def _save_ranking_csv(rows: List[dict], ranking_file: str) -> None:
    ranking_df = pd.DataFrame(rows)
    if not ranking_df.empty:
        ranking_df = ranking_df.round(4)
    tmp_file = ranking_file + ".tmp"
    ranking_df.to_csv(tmp_file, index=False, encoding="utf-8-sig")
    try:
        os.replace(tmp_file, ranking_file)
        print(f"✓ 排名已保存: {ranking_file}")
    except OSError:
        print(f"✓ 排名已写入: {tmp_file}")
        print(
            f"  若 {os.path.basename(ranking_file)} 被其他程序打开，请关闭后手动将 .tmp 重命名为该文件。"
        )


class GrowthRankError(RuntimeError):
    """成长因子打分失败；形态建仓 / 回测对比应中止东财推送。"""


def rank_symbols_by_growth(
    symbols: Sequence[str],
) -> Tuple[List[str], Dict[str, Dict], Dict[str, float]]:
    """
    对给定代码按成长因子排序（财务不足的票排末尾）。
    无有效代码、接口异常、或全部无财务分时抛 GrowthRankError。
    """
    uniq: List[str] = []
    seen = set()
    for raw in symbols:
        s = "".join(ch for ch in str(raw) if ch.isdigit()).zfill(6)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    if not uniq:
        raise GrowthRankError("无有效 6 位代码")
    try:
        ranked, details, scores = _rank_symbols_keep_all(uniq)
    except GrowthRankError:
        raise
    except Exception as exc:
        raise GrowthRankError(f"打分异常: {exc}") from exc
    if not ranked:
        raise GrowthRankError("排序结果为空")
    scored = [s for s, sc in scores.items() if sc is not None and sc == sc]
    if not scored:
        raise GrowthRankError("财务数据全部缺失或无效")
    return ranked, details or {}, scores


def write_growth_rank_csv(
    group_name: str,
    ranked: Sequence[str],
    details: Dict[str, Dict],
    path: str,
    name_map: Optional[Dict[str, str]] = None,
) -> str:
    """写出成长因子重排表，供工作流「报告」查看。"""
    out = os.path.abspath(path)
    ddir = os.path.dirname(out)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    names = dict(name_map or {})
    missing = [s for s in ranked if not str(names.get(s) or "").strip()]
    if missing:
        try:
            names.update(get_stock_names(missing))
        except Exception as exc:
            print(f"⚠ 成长因子补名称失败: {exc}")
    try:
        industries = get_stock_industries(list(ranked))
    except Exception as exc:
        print(f"⚠ 成长因子补行业失败: {exc}")
        industries = {s: "" for s in ranked}
    rows = _ranking_rows(group_name, ranked, details, names, industries)
    _save_ranking_csv(rows, out)
    return out


def run_mx_group_growth_rank(
    group_names: Sequence[str],
    *,
    skip_push: bool = False,
    ranking_file: Optional[str] = None,
    groups_dir: Optional[str] = None,
) -> int:
    """
    读取项目内分组 txt → 各组独立成长排序 → 推东财同名分组。
    不回写桌面文件，也不覆盖分组 txt。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ranking_file = ranking_file or os.path.join(script_dir, "factor_growth_ranking.csv")
    groups_dir = os.path.abspath(groups_dir or DEFAULT_MX_GROUPS_DIR)
    wanted = [str(g).strip() for g in group_names if str(g).strip()]
    print("=" * 80)
    print("成长因子排序 · 项目分组文件（不混合、不回写桌面）")
    print("分组: " + "、".join(f"「{g}」" for g in wanted))
    print(f"名单目录: {groups_dir}")
    print("=" * 80)
    if not wanted:
        print("✗ 未指定分组")
        return 2

    all_rows: List[dict] = []
    any_ok = False
    for g in wanted:
        path = group_txt_path(g, groups_dir)
        current, notes = load_group_symbols_txt(path)
        print("-" * 72)
        for line in notes:
            print(f"  {line}")
        print(f"【{g}】{len(current)} 只: {', '.join(current) if current else '（空）'}")
        if not current:
            print(f"  跳过「{g}」：无有效代码，不推送")
            continue
        ranked, details, scores = _rank_symbols_keep_all(current)
        names = get_stock_names(ranked)
        industries = get_stock_industries(ranked)
        all_rows.extend(_ranking_rows(g, ranked, details, names, industries))
        print("  组内成长排序（高→低）:")
        for i, sym in enumerate(ranked, 1):
            sc = scores.get(sym)
            sc_s = f"{sc:.4f}" if sc is not None and sc == sc else "无财务分"
            print(f"    {i}. {names.get(sym, sym)} {sym}  {sc_s}")
        any_ok = True
        if skip_push:
            print(f"  已跳过写回东财「{g}」")
            continue
        ok, push_notes = replace_group_symbols(
            ranked, group_name=g, current_symbols=current
        )
        for line in push_notes:
            print(f"  {line}")
        if not ok:
            print(f"  ⚠ 「{g}」写回东财未完全成功")
        print(f"  未改写分组文件: {path}")

    if all_rows:
        try:
            _save_ranking_csv(all_rows, ranking_file)
        except Exception as save_err:
            print(f"⚠ 保存排名失败: {save_err}")
    else:
        _save_ranking_csv([], ranking_file)
        print("成长表为空（各分组均无代码）")

    return 0 if any_ok else 2


def main():
    """默认：股票池 + 四层评分 + 回测。指定 --from-mx-groups 则读项目分组 txt，排序后推东财。"""
    parser = argparse.ArgumentParser(description="稳健高质量成长因子")
    parser.add_argument(
        "--from-mx-groups",
        default="",
        help="逗号分隔分组名（日常 M加,Q,量能）；读取 config/mx_groups/{名}.txt，组内成长排序后推东财同名分组",
    )
    parser.add_argument(
        "--mx-groups-dir",
        default="",
        help="分组 txt 目录（默认 config/mx_groups）",
    )
    parser.add_argument(
        "--skip-mx-push",
        action="store_true",
        help="只排序写 CSV，不写回东财自选",
    )
    args, _unknown = parser.parse_known_args()
    groups_arg = str(args.from_mx_groups or "").strip()
    if groups_arg:
        names = [x.strip() for x in groups_arg.replace("，", ",").split(",") if x.strip()]
        raise SystemExit(
            run_mx_group_growth_rank(
                names,
                skip_push=bool(args.skip_mx_push),
                groups_dir=str(args.mx_groups_dir or "").strip() or None,
            )
        )

    print("=" * 80)
    print("稳健型高质量复利策略 - 资产安全/现金流质量/盈利质量/运营效率 四层评分")
    print("=" * 80)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    stock_pool_file = os.path.join(script_dir, 'stocks_pool.txt')
    symbols = load_stock_pool(stock_pool_file)

    if not symbols:
        print("✗ 股票池为空，无法继续")
        return

    print(f"✓ 股票池加载成功: {len(symbols)} 只股票")
    print(f"  股票列表: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}")

    top_n = 10
    initial_cash = 500000
    # 默认拉取最近日期数据：结束日=今天，开始日=3年前
    end_date_d = datetime.now()
    start_date_d = end_date_d - timedelta(days=3 * 365)
    end_date = end_date_d.strftime('%Y%m%d')
    start_date = start_date_d.strftime('%Y%m%d')

    print(f"\n策略参数:")
    print(f"  - 持仓数量（从前 10% 中取）: {top_n}")
    print(f"  - 初始资金: {initial_cash:,} 元")
    print(f"  - 回测日期: {start_date} 至 {end_date}")

    import pybroker as pyb
    from pybroker import Strategy, StrategyConfig
    from pybroker_integration.custom_data_source import create_custom_data_source

    pyb.enable_data_source_cache('factor_growth_cache')
    pyb.param('top_n', top_n)
    pyb.param('symbols_for_quality', symbols)

    _ensure_quality_rank_params()
    top_10_pct = pyb.param('top_10_pct_symbols') or []
    target_symbols = pyb.param('target_symbols') or []
    factor_details = pyb.param('factor_details') or {}
    factor_scores = pyb.param('factor_scores') or {}

    if not target_symbols:
        print("✗ 未能得到有效的前 10% 股票（财务数据可能全部失败），退出")
        return

    print(f"\n✓ 稳健高质量前 10% 共 {len(top_10_pct)} 只，实际持仓前 {len(target_symbols)} 只")

    config = StrategyConfig(max_long_positions=top_n, initial_cash=initial_cash)
    data_source = create_custom_data_source()
    strategy = Strategy(
        data_source,
        start_date=start_date,
        end_date=end_date,
        config=config,
    )
    strategy.set_before_exec(rank_stocks_by_quality)
    strategy.add_execution(execute_quality_strategy, symbols, indicators=[])

    print("\n" + "=" * 80)
    print("开始回测（行情数据）...")
    print("=" * 80)

    import time
    start_time = time.time()
    try:
        result = strategy.backtest(warmup=1)
        elapsed = time.time() - start_time
        print(f"\n✓ 回测完成！耗时: {elapsed:.2f} 秒")

        if hasattr(result, 'metrics_df') and result.metrics_df is not None:
            print("\n策略表现指标:")
            print(result.metrics_df)

        if factor_details:
            print("\n" + "=" * 80)
            print("稳健高质量四层评分：代码排名与各层得分、总分")
            print("=" * 80)
            sorted_stocks = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)
            n_ranked = len(sorted_stocks)
            rank_symbols = [s for s, _ in sorted_stocks]
            stock_names = get_stock_names(rank_symbols)
            stock_industries = get_stock_industries(rank_symbols)
            print(f"\n有效排名数量: {n_ranked} 只（按总分从高到低）")
            print(f"\n{'排名':<6} {'股票名称':<14} {'代码':<8} {'行业':<8} {'总分':<10} {'资产安全':<10} {'现金流质量':<10} {'盈利质量':<10} {'运营效率':<10}")
            print("-" * 110)
            for rank, (symbol, score) in enumerate(sorted_stocks, 1):
                name = stock_names.get(symbol, symbol)
                industry = stock_industries.get(symbol, "")
                d = factor_details.get(symbol, {})
                l1 = d.get("layer1_score", np.nan)
                l2 = d.get("layer2_score", np.nan)
                l3 = d.get("layer3_score", np.nan)
                l4 = d.get("layer4_score", np.nan)
                def _s(v):
                    return f"{v:.4f}" if pd.notna(v) and np.isfinite(v) else "-"
                name_show = (name[:12] + "..") if len(name) > 14 else name
                industry_show = (industry[:6] + "..") if len(industry) > 8 else industry
                print(f"{rank:<6} {name_show:<14} {symbol:<8} {industry_show:<8} {_s(score):<10} {_s(l1):<10} {_s(l2):<10} {_s(l3):<10} {_s(l4):<10}")

        if hasattr(result, 'trades') and result.trades is not None and not result.trades.empty:
            csv_file = os.path.join(script_dir, 'factor_growth_trades.csv')
            result.trades.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n✓ 交易记录已保存: {csv_file}")

        if factor_details and factor_scores:
            ranking_data = []
            all_symbols = [s for s, _ in sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)]
            stock_names_all = get_stock_names(all_symbols)
            stock_industries_all = get_stock_industries(all_symbols)
            for rank, (symbol, score) in enumerate(sorted(factor_scores.items(), key=lambda x: x[1], reverse=True), 1):
                d = factor_details.get(symbol, {})
                ranking_data.append({
                    "排名": rank,
                    "股票代码": symbol,
                    "股票名称": stock_names_all.get(symbol, symbol),
                    "行业": stock_industries_all.get(symbol, ""),
                    "总分": score,
                    "资产安全得分": d.get("layer1_score"),
                    "现金流质量得分": d.get("layer2_score"),
                    "盈利质量得分": d.get("layer3_score"),
                    "运营效率得分": d.get("layer4_score"),
                })
            ranking_df = pd.DataFrame(ranking_data)
            ranking_df = ranking_df.round(4)
            ranking_file = os.path.join(script_dir, 'factor_growth_ranking.csv')
            tmp_file = ranking_file + '.tmp'
            try:
                ranking_df.to_csv(tmp_file, index=False, encoding='utf-8-sig')
                try:
                    os.replace(tmp_file, ranking_file)
                    print(f"✓ 排名已保存: {ranking_file}")
                except OSError:
                    # 原文件被占用（如 Excel 打开）时替换失败，保留 .tmp 并提示
                    print(f"✓ 排名已写入: {tmp_file}")
                    print(f"  若 {os.path.basename(ranking_file)} 被其他程序打开，请关闭后手动将 .tmp 重命名为该文件。")
            except Exception as save_err:
                print(f"⚠ 保存排名失败: {save_err}")

        print("\n" + "=" * 80)
        print("策略执行完成")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ 回测错误: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()

