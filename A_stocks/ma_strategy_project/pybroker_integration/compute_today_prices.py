# -*- coding: utf-8 -*-
"""
根据 train_model_shift.py（结果1）和 train_model_shift-2.py（结果2）的预测结果，
计算当日预测高价和低价。

步骤简述：
1. 结果1取每只股票最后一个交易日的预测价；结果2取最后两个交易日的预测价（可仅保留交易所交易日）。
2. 待计算序列 = [结果1最后一日的预测价, 结果2较前交易日的预测价]。
3. 用「结果2最后交易日预测价 + 昨日价格」分别减去待计算序列的两个价格，得到两个计算价，追加到序列。
4. 对 4 个数排序：当日高价 = 两个最大值的平均，当日低价 = 中间两个值的平均。

可选：先在本脚本内依次运行两个训练脚本再计算（默认）；或仅读取已有 CSV 计算。
"""

import os
import sys
import subprocess
import argparse
import pandas as pd

# cwd 常为 pybroker_integration：先保证上级 ma_strategy_project 的 config/data 优先
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
if _PROJECT_ROOT in sys.path:
    sys.path.remove(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)
try:
    from path_bootstrap import prefer_ma_strategy_project_root

    prefer_ma_strategy_project_root(os.path.join(_PROJECT_ROOT, "data", "fetcher.py"))
except Exception:
    pass

from train_model_symbols import load_train_model_shift_symbols, normalize_a_share_symbol
from prediction_kline_chart import (
    CHART_SYMBOL_COUNT,
    COMBINED_HIGHLOW_HISTORY_CSV,
    COMPARE_JSON_NAME,
    HISTORY_DAYS,
    MODEL_LABEL_COMBINED,
    RESULT1_WALKFORWARD_CSV,
    RESULT2_WALKFORWARD_CSV,
    build_charts_json,
    build_combined_highlow_history_csv,
    compute_high_low_from_preds,
)
from stock_names import resolve_stock_names
from prediction_kline_signal import SIGNAL_CSV_NAME, run_signal_pipeline


# ---------- 可配置路径（可通过环境变量或命令行覆盖）----------
SCRIPT_DIR = _SCRIPT_DIR

# 结果1/结果2 的 CSV（由两个训练脚本生成）
RESULT1_CSV = os.path.join(SCRIPT_DIR, 'result1_last.csv')
RESULT2_CSV = os.path.join(SCRIPT_DIR, 'result2_last2.csv')

# 股票名称：默认通过 Tushare / AkShare 接口解析（见 stock_names.py）
# 可选本地 CSV 覆盖（symbol, name），环境变量 SYMBOL_NAMES_CSV
SYMBOL_NAMES_CSV = os.environ.get('SYMBOL_NAMES_CSV', os.path.join(SCRIPT_DIR, 'symbol_names.csv'))

# 交易所交易日历（可选）：CSV 需包含 date 列（YYYY-MM-DD）。若设置，结果2只保留 date 在此表中的行，再取每只股票最后两个交易日。
# 可通过环境变量 TRADING_DAYS_CSV 覆盖路径；为空则不按交易日筛选，按自然日取最后两条。
TRADING_DAYS_CSV = os.environ.get('TRADING_DAYS_CSV', '')  # 例如: os.path.join(SCRIPT_DIR, 'trading_days.csv')


def load_symbol_names(path: str) -> dict:
    """可选：从 CSV 加载 symbol -> 名称 覆盖项（接口结果之上合并）。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        df = pd.read_csv(path, encoding='utf-8-sig')
    except Exception:
        return {}
    if 'symbol' not in df.columns or 'name' not in df.columns:
        return {}
    return {
        normalize_a_share_symbol(str(k)): str(v)
        for k, v in zip(df['symbol'].astype(str), df['name'].astype(str))
    }


def resolve_display_names(symbols: list[str], csv_path: str | None = None) -> dict[str, str]:
    """接口拉取名称，并用可选 CSV 覆盖。"""
    names = resolve_stock_names(symbols)
    overrides = load_symbol_names(csv_path or "")
    for sym, name in overrides.items():
        if name and str(name).strip():
            names[sym] = str(name).strip()
    return names


def load_trading_dates(path: str) -> set:
    """从 CSV 的 date 列加载交易日集合（字符串 YYYY-MM-DD）。空路径或失败返回空 set（表示不筛选）。"""
    if not path or not os.path.isfile(path):
        return set()
    try:
        df = pd.read_csv(path, encoding='utf-8-sig')
    except Exception:
        return set()
    if 'date' not in df.columns:
        return set()
    return set(pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d').astype(str))


def run_training_scripts(script_dir: str) -> bool:
    """依次执行 train_model_shift.py、train_model_shift-2.py，成功返回 True。"""
    train1 = os.path.join(script_dir, 'train_model_shift.py')
    train2 = os.path.join(script_dir, 'train_model_shift-2.py')
    if not os.path.isfile(train1) or not os.path.isfile(train2):
        print(f"未找到训练脚本: {train1} 或 {train2}")
        return False
    for name, path in [('结果1', train1), ('结果2', train2)]:
        print(f"正在运行 {name}: {path}", flush=True)
        ret = subprocess.run(
            [sys.executable, path],
            cwd=script_dir,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        if ret.stdout:
            print(ret.stdout, end='' if ret.stdout.endswith('\n') else '\n', flush=True)
        if ret.returncode != 0:
            print(f"运行失败，退出码: {ret.returncode}", flush=True)
            if ret.stderr:
                print(ret.stderr, end='' if ret.stderr.endswith('\n') else '\n', flush=True)
            return False
        if ret.stderr:
            # 成功时也透出警告，便于线上排查
            print(ret.stderr, end='' if ret.stderr.endswith('\n') else '\n', flush=True)
    return True


def normalize_date_series(s: pd.Series) -> pd.Series:
    """将日期列转为 YYYY-MM-DD 字符串。"""
    return pd.to_datetime(s, errors='coerce').dt.strftime('%Y-%m-%d')


def main():
    parser = argparse.ArgumentParser(description='运行两套训练并计算当日高低价，或仅从已有 CSV 计算')
    parser.add_argument('--no-run-training', action='store_true', help='不运行训练脚本，仅读取已有 result1_last.csv / result2_last2.csv 计算')
    parser.add_argument('--symbol-names', type=str, default=None, help='股票名称 CSV 路径（默认使用配置或环境变量 SYMBOL_NAMES_CSV）')
    parser.add_argument('--trading-days', type=str, default=None, help='交易日历 CSV 路径（默认使用环境变量 TRADING_DAYS_CSV）；空表示不按交易日筛选')
    args = parser.parse_args()

    script_dir = SCRIPT_DIR
    result1_path = RESULT1_CSV
    result2_path = RESULT2_CSV
    symbol_names_path = args.symbol_names or SYMBOL_NAMES_CSV
    trading_days_path = args.trading_days if args.trading_days is not None else (TRADING_DAYS_CSV or None)

    if not args.no_run_training:
        if not run_training_scripts(script_dir):
            sys.exit(1)
        print()

    if not os.path.isfile(result1_path):
        print(f"未找到 result1_last.csv，请先运行 train_model_shift.py 或去掉 --no-run-training。路径: {result1_path}")
        sys.exit(1)
    if not os.path.isfile(result2_path):
        print(f"未找到 result2_last2.csv，请先运行 train_model_shift-2.py 或去掉 --no-run-training。路径: {result2_path}")
        sys.exit(1)
    r1 = pd.read_csv(result1_path, encoding='utf-8-sig')
    r2 = pd.read_csv(result2_path, encoding='utf-8-sig')

    # 结果2：按「交易所交易日」筛选（若配置了交易日历）
    trading_dates = load_trading_dates(trading_days_path) if trading_days_path else set()
    if trading_dates:
        r2['date_str'] = normalize_date_series(r2['date'])
        r2 = r2[r2['date_str'].isin(trading_dates)].copy()
        r2 = r2.drop(columns=['date_str'])
        if r2.empty:
            print("按交易日历筛选后结果2无数据，请检查 TRADING_DAYS_CSV 或日期列。")
            sys.exit(1)
    # 结果1：每只股票一行
    r1 = r1.rename(columns={'current_price': 'yesterday_price', 'predicted_price': 'result1_pred'})
    r1 = r1[['symbol', 'date', 'yesterday_price', 'result1_pred']]

    # 结果2：按 symbol, date 排序，每组取前一条为 earlier，后一条为 last（最后两个交易日）
    r2 = r2.sort_values(['symbol', 'date'])
    r2_earlier = r2.groupby('symbol').first().reset_index()[['symbol', 'date', 'predicted_price']]
    r2_last = r2.groupby('symbol').last().reset_index()[['symbol', 'date', 'predicted_price']]
    r2_earlier = r2_earlier.rename(columns={'predicted_price': 'result2_earlier_pred', 'date': 'result2_earlier_date'})
    r2_last = r2_last.rename(columns={'predicted_price': 'result2_last_pred', 'date': 'result2_last_date'})
    r2_earlier = r2_earlier[['symbol', 'result2_earlier_pred']]
    r2_last = r2_last[['symbol', 'result2_last_pred']]

    merge_df = r1.merge(r2_earlier, on='symbol', how='inner').merge(r2_last, on='symbol', how='inner')

    # 待计算序列前两个 + 两个计算价
    merge_df['computed1'] = merge_df['result2_last_pred'] + merge_df['yesterday_price'] - merge_df['result1_pred']
    merge_df['computed2'] = merge_df['result2_last_pred'] + merge_df['yesterday_price'] - merge_df['result2_earlier_pred']

    # 四元组排序：当日高价=(两最大)平均，当日低价=(中间两个)平均
    def high_low(row):
        hi, lo = compute_high_low_from_preds(
            row['yesterday_price'],
            row['result1_pred'],
            row['result2_earlier_pred'],
            row['result2_last_pred'],
        )
        return pd.Series({'today_high': hi, 'today_low': lo})

    merge_df = merge_df.join(merge_df.apply(high_low, axis=1))

    # 中间文件
    intermediate_path = os.path.join(script_dir, 'today_prices_intermediate.csv')
    out_cols = [
        'symbol', 'date', 'yesterday_price', 'result1_pred', 'result2_earlier_pred', 'result2_last_pred',
        'computed1', 'computed2', 'today_high', 'today_low'
    ]
    merge_df[out_cols].to_csv(intermediate_path, index=False, encoding='utf-8-sig')
    print(f"中间数据已写入: {intermediate_path}")

    # 股票名称（Tushare / AkShare 接口，可选 CSV 覆盖）
    sym_list = [
        normalize_a_share_symbol(str(s))
        for s in merge_df['symbol'].astype(str).tolist()
    ]
    names = resolve_display_names(sym_list, symbol_names_path)
    merge_df['stock_name'] = merge_df['symbol'].astype(str).map(
        lambda s: names.get(normalize_a_share_symbol(s), s)
    )

    # 最终结果：仅股票名称与高低价及买卖档（不含 symbol 列）
    # 列序从高到低：卖三→卖一 | 名称/高价/差价/低价 | 买一→买三
    # 区间宽度固定用 high_low_diff；为 0 时各档重合（不区分档位）
    final = merge_df[['stock_name', 'today_high', 'today_low']].copy()
    final['today_high'] = final['today_high'].round(2)
    final['today_low'] = final['today_low'].round(2)
    final['high_low_diff'] = (final['today_high'] - final['today_low']).round(2)
    hi = final['today_high']
    lo = final['today_low']
    w = final['high_low_diff']
    final['卖一'] = (hi + w).round(2)
    final['卖二'] = (hi + 2 * w).round(2)
    final['卖三'] = (hi + 3 * w).round(2)
    final['买一'] = (lo - w).round(2)
    final['买二'] = (lo - 2 * w).round(2)
    final['买三'] = (lo - 3 * w).round(2)
    final = final[
        ['卖三', '卖二', '卖一', 'stock_name', 'today_high', 'high_low_diff', 'today_low', '买一', '买二', '买三']
    ]
    high_low_override = {
        normalize_a_share_symbol(str(s)): (float(h), float(l))
        for s, h, l in zip(merge_df['symbol'], merge_df['today_high'], merge_df['today_low'])
    }
    final_path = os.path.join(script_dir, 'today_high_low_result.csv')
    final.to_csv(final_path, index=False, encoding='utf-8-sig')
    print(f"当日高低价结果已写入: {final_path}\n")

    print("=" * 60)
    print("当日预测高价 / 低价（按股票）")
    print("=" * 60)
    for _, row in final.iterrows():
        print(f"{row['stock_name']}  高价: {row['today_high']:.2f}  低价: {row['today_low']:.2f}")
    print("=" * 60)

    # 网页预测 K 线：结果1+2 综合高低，列表前 CHART_SYMBOL_COUNT 只，20 历史 + 1 未来
    wf1_path = os.path.join(script_dir, RESULT1_WALKFORWARD_CSV)
    wf2_path = os.path.join(script_dir, RESULT2_WALKFORWARD_CSV)
    combined_history = os.path.join(script_dir, COMBINED_HIGHLOW_HISTORY_CSV)
    compare_json = os.path.join(script_dir, COMPARE_JSON_NAME)
    try:
        n_combined = build_combined_highlow_history_csv(
            wf1_path,
            wf2_path,
            combined_history,
            trading_days_path=trading_days_path,
            today_high_low_override=high_low_override,
        )
        if n_combined:
            print(f"综合预测高低 K 线 CSV 已写入: {combined_history}（{n_combined} 行）")
        chart_symbols = load_train_model_shift_symbols()[:CHART_SYMBOL_COUNT]
        chart_names = resolve_display_names(chart_symbols, symbol_names_path)
        payload = build_charts_json(
            combined_history,
            chart_symbols,
            compare_json,
            symbol_names=chart_names,
            history_n=HISTORY_DAYS,
            max_charts=CHART_SYMBOL_COUNT,
            model_label=MODEL_LABEL_COMBINED,
        )
        if payload:
            chart_labels = [
                c.get("symbol_name") or names.get(c.get("symbol", ""), c.get("symbol", ""))
                for c in payload.get("charts", [])
            ]
            print(
                f"预测 K 线（结果1+2 综合高低）JSON 已写入: {compare_json}"
                f"（{len(chart_labels)} 只: {', '.join(chart_labels)}）"
            )
            signal_csv = os.path.join(script_dir, SIGNAL_CSV_NAME)
            try:
                n_sig_rows, n_sig, sig_list = run_signal_pipeline(
                    script_dir,
                    symbols=chart_symbols[:CHART_SYMBOL_COUNT],
                    fetch_real=True,
                    stock_names=chart_names,
                )
                if n_sig_rows:
                    print(
                        f"K 线序列涨跌信号 CSV 已写入: {signal_csv}（{n_sig_rows} 行）；"
                        f"预测 K 线 JSON 已附加 signal 字段"
                    )
                    for sig in sig_list:
                        print(
                            f"  {sig.get('stock_name', sig['symbol'])}  "
                            f"T+1{sig['t1_pred_direction_label']} → 预测{sig['predicted_direction_label']}"
                        )
                else:
                    print(f"未生成 K 线序列涨跌信号（请检查 {COMBINED_HIGHLOW_HISTORY_CSV} 与真实 OHLC）")
            except Exception as e:
                print(f"生成 K 线序列涨跌信号失败: {e}")
        else:
            wanted = [normalize_a_share_symbol(s) for s in chart_symbols[:CHART_SYMBOL_COUNT]]
            print(
                f"未生成预测 K 线 JSON（{COMBINED_HIGHLOW_HISTORY_CSV} 中无匹配数据；"
                f"列表前 {CHART_SYMBOL_COUNT} 只: {', '.join(wanted)}）。"
                "请完整运行训练脚本或检查 walkforward CSV。"
            )
    except Exception as e:
        print(f"生成预测 K 线 JSON 失败: {e}")


if __name__ == '__main__':
    main()
