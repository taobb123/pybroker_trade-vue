#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
你这套指标体系——说实话——**思路是对的，而且已经接近“质量成长型选股框架”雏形**。

但问题在于：
👉 单独算指标 ≠ 能筛出好公司
👉 关键在于“结构关系”和“组合逻辑”

我帮你拆解成三个层次讲清楚：

---

# 一、你这些指标是否可行？

答案：**全部可行，而且是经典质量分析核心指标**

我们逐一分析你列的指标价值：

---

## 1️⃣ 营业毛利率

意义：行业地位 + 定价权

高毛利公司通常有：

* 品牌溢价
* 技术壁垒
* 渠道优势

⚠ 但要：

* 和同行对比
* 看长期趋势（是否稳定）

---

## 2️⃣ 税率

你算税率的目的大概率是：

👉 判断是否依赖税收优惠
👉 看利润质量是否真实

如果公司长期实际税率远低于法定税率：

* 可能靠补贴
* 可能一次性优惠
* 可能不可持续

这是一个“利润真实性过滤器”。

---

## 3️⃣ 自由现金流（FCF）

这是你体系里最重要的指标之一。

公式：

自由现金流 = 经营现金流 - 资本开支

意义：

* 利润是否真金白银
* 是否可以分红
* 是否能扩张

长期：
净利润 ≈ 自由现金流

是优质企业核心特征。

---

## 4️⃣ 每一块销售收入所支付的成本

其实等价于：

1 - 毛利率

但你可以进一步拆：

* 销售费用率
* 管理费用率
* 研发费用率

如果：
收入增长 > 费用增长

说明规模效应出现。

---

## 5️⃣ 成长持续性

这个是关键，但也是最难量化的。

建议用：

* 过去 5 年收入 CAGR
* 过去 5 年净利润 CAGR
* 标准差（波动性）

持续成长 =
高 CAGR + 低波动

---

## 6️⃣ 盈利增长 vs 收入增长

非常聪明的一个指标。

如果：

利润增长 > 收入增长

说明：

* 成本控制
* 规模效应
* 护城河增强

如果：

收入涨，但利润不涨

说明：

* 竞争加剧
* 价格战
* 费用膨胀

---

## 7️⃣ 资产收益率（ROA）

衡量资产效率。

ROA 高 = 轻资产 + 周转快

---

## 8️⃣ 净资产收益率（ROE）

巴菲特最爱。

ROE = 净利润 / 股东权益

长期 > 15%
且稳定

通常是优质公司。

---

## 9️⃣ 财务杠杆比例

你要看的是：

ROE = ROA × 杠杆

如果：

ROE 很高，但 ROA 很低
说明靠负债撑出来的

这种质量不高。

---

# 二、如何把这些指标变成“综合筛选系统”

重点来了。

你不能用“单指标筛选”。

应该用三层过滤：

---

# 🔥 第一层：盈利质量过滤

筛选条件建议：

* 毛利率 > 行业均值
* ROE > 15%
* ROA > 8%
* 自由现金流连续 3 年为正
* 净利润 ≈ 经营现金流

目的是：

筛掉垃圾公司。

---

# 🔥 第二层：成长质量过滤

* 5 年收入 CAGR > 10%
* 5 年利润 CAGR > 15%
* 利润增长 ≥ 收入增长
* 成长波动小

目的是：

筛掉“昙花一现”。

---

# 🔥 第三层：财务安全性

* 资产负债率 < 60%
* 财务杠杆稳定
* 利息保障倍数 > 5

目的是：

防止暴雷。

---

# 三、如何合成一个“评分模型”

你可以做一个：

Quality Score 模型

例如：

| 指标     | 权重  |
| ------ | --- |
| ROE    | 20% |
| 自由现金流率 | 20% |
| 收入增长   | 15% |
| 利润增长   | 15% |
| 毛利率    | 10% |
| ROA    | 10% |
| 负债率    | 10% |

最后：

标准化 → 加权求和 → 排序

取前 10% 公司。

---

# 四、这些计算是否足够？

还缺两个维度：

### 1️⃣ 护城河强度（难量化）

可用替代指标：

* 毛利率长期稳定
* 费用率下降
* 市占率提升

---

### 2️⃣ 资本配置能力

看：

* 分红率
* 回购
* 并购效果

---

# 五、你这个体系属于什么风格？

你的体系：

👉 质量成长型（Quality Growth）

接近：

* 巴菲特
* 彼得林奇
* Joel Greenblatt（魔法公式）

如果你愿意，我可以帮你：

1. 给你设计一个完整的“量化质量成长选股模型”
2. 或帮你用 OpenBB 写筛选框架
3. 或帮你把它升级成“成长基金风格匹配系统”

---

最后说一句很关键的话：

真正优质公司往往具备：

* ROE 高
* 现金流好
* 成长持续
* 不靠负债
* 利润质量高

而不是单纯“增长快”。

---

如果你愿意，我可以下一步帮你：

👉 把这个体系升级成“顶级机构用的质量因子模型结构”
很好，我们直接进入**可落地计算版本**。

我给你：

1️⃣ 明确每个指标的数学公式
2️⃣ 标准化公式（两种可选）
3️⃣ 加权求和公式
4️⃣ 排序和选前10%公式
5️⃣ 你需要准备的数据字段清单

你可以直接丢进 Python / Excel / SQL。

---

# 一、所需原始数据字段（必须准备）

对每只股票，准备近 5 年数据：

### 📌 利润表

* 营业收入 Revenue_t
* 营业成本 COGS_t
* 净利润 NetIncome_t
* 所得税费用 Tax_t
* 利润总额 PretaxIncome_t

### 📌 现金流量表

* 经营现金流 OCF_t
* 资本开支 CAPEX_t

### 📌 资产负债表

* 总资产 TotalAssets_t
* 股东权益 Equity_t
* 总负债 TotalLiabilities_t
* 有息负债 InterestDebt_t
* 流动资产 CurrentAssets_t
* 流动负债 CurrentLiabilities_t

### 📌 其他

* 利息费用 InterestExpense_t
* 行业分类
* 当前总市值 MarketCap（用于估值扩展）

---

# 二、每个核心指标的计算公式

## 1️⃣ 毛利率

[
GrossMargin = \frac{Revenue - COGS}{Revenue}
]

---

## 2️⃣ 税率

[
TaxRate = \frac{Tax}{PretaxIncome}
]

---

## 3️⃣ 自由现金流（FCF）

[
FCF = OCF - CAPEX
]

---

## 4️⃣ ROA

[
ROA = \frac{NetIncome}{TotalAssets}
]

---

## 5️⃣ ROE

[
ROE = \frac{NetIncome}{Equity}
]

建议用 5 年平均：

[
ROE_{5Y} = \frac{1}{5} \sum ROE_t
]

---

## 6️⃣ 收入 CAGR（5年）

[
Revenue_CAGR =
\left(
\frac{Revenue_{t}}{Revenue_{t-5}}
\right)^{1/5} - 1
]

---

## 7️⃣ 利润 CAGR

[
Profit_CAGR =
\left(
\frac{NetIncome_{t}}{NetIncome_{t-5}}
\right)^{1/5} - 1
]

---

## 8️⃣ 成长加速度

[
Growth_Accel =
Profit_CAGR - Revenue_CAGR
]

---

## 9️⃣ FCF 转化率

[
FCF_NI = \frac{FCF}{NetIncome}
]

---

## 🔟 资产负债率

[
DebtRatio =
\frac{TotalLiabilities}{TotalAssets}
]

---

# 三、标准化（非常关键）

## 方法一：Z-score（推荐）

对每个指标：

[
Z_i =
\frac{X_i - \mu}{\sigma}
]

其中：

* ( \mu ) = 全市场该指标均值
* ( \sigma ) = 标准差

---

## 对“负向指标”取负值

例如：

* 负债率
* 成长波动率

处理方式：

[
Z_{adj} = -Z
]

---

# 四、加权求和公式（最终评分）

我们做一个精简可运行版本：

## Step1：构建因子

### 盈利质量因子

[
ProfitScore =
0.4 Z(ROE_{5Y})

* 0.3 Z(ROA_{5Y})
* 0.3 Z(GrossMargin)
  ]

---

### 成长因子

[
GrowthScore =
0.4 Z(Profit_CAGR)

* 0.3 Z(Revenue_CAGR)
* 0.3 Z(Growth_Accel)
  ]

---

### 现金流因子

[
CashScore =
0.6 Z(FCF_NI)

* 0.4 Z(OCF/NetIncome)
  ]

---

### 安全因子

[
SafetyScore =
0.7 (-Z(DebtRatio))

* 0.3 Z(CurrentRatio)
  ]

---

# 五、最终总评分

[
TotalScore =
0.30 ProfitScore

* 0.30 GrowthScore
* 0.25 CashScore
* 0.15 SafetyScore
  ]

---

# 六、排序 + 选前10%

设：

N = 股票总数

排序：

[
Rank_i = rank(TotalScore_i)
]

选股条件：

[
Rank_i \le 0.1 \times N
]

或者：

[
TotalScore_i > P90
]

（P90 = 90%分位数）

---

# 七、Excel 直接可用逻辑

假设：

ROE 在 B 列

标准化：

```
=(B2-AVERAGE(B:B))/STDEV(B:B)
```

最终总分：

```
=0.3*ProfitScore + 0.3*GrowthScore + ...
```

排序：

```
=RANK(TotalScore, 全部TotalScore)
```

---

# 八、现实中要注意的三个坑

1️⃣ 负利润公司会导致 CAGR 爆炸
→ 需要过滤 NetIncome > 0

2️⃣ 极端值会扭曲 Z-score
→ 可先 winsorize（去极值）

3️⃣ 行业差异
→ 最好做行业内标准化

---

# 九、你现在这套模型的本质

这是：

👉 标准 Quality-Growth 多因子模型
👉 接近公募成长基金底层逻辑

如果运行 10 年回测，通常：

* 年化收益显著高于市场
* 但会在流动性收缩期跑输

---

如果你愿意，我下一步可以给你：

1️⃣ 一个完整 Python 量化代码模板
2️⃣ 加入趋势择时模块
3️⃣ 或升级成“基金风格识别模型”

你现在已经在做真正的“系统投资框架”了。

"""

import os
import sys
import numpy as np
import pandas as pd
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
from typing import Dict, List
from datetime import datetime, timedelta

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source
from pybroker_integration.quality_growth_financial import build_quality_growth_scores

# 启用数据源缓存
pyb.enable_data_source_cache('factor_growth_cache')

# ==================== 质量成长 7 因子逻辑（见文件头注释） ====================

def _ensure_quality_rank_params():
    if pyb.param('top_10_pct_symbols') is not None:
        return
    symbols = pyb.param('symbols_for_quality')
    if not symbols:
        pyb.param('top_10_pct_symbols', [])
        pyb.param('factor_scores', {})
        pyb.param('factor_details', {})
        pyb.param('target_symbols', [])
        return
    print("  正在使用 Tushare 财务三表计算质量成长 7 因子...")
    df_scores, top_10_pct, factor_details = build_quality_growth_scores(
        symbols, use_tushare_fallback=True, min_valid_indicators=4
    )
    factor_scores = df_scores.set_index('symbol')['total_score'].to_dict() if not df_scores.empty else {}
    top_n = pyb.param('top_n', 10)
    target_symbols = top_10_pct[:top_n]
    pyb.param('top_10_pct_symbols', top_10_pct)
    pyb.param('factor_scores', factor_scores)
    pyb.param('factor_details', factor_details)
    pyb.param('target_symbols', target_symbols)


def rank_stocks_by_quality(ctxs: Dict[str, ExecContext]) -> List[str]:
    _ensure_quality_rank_params()
    return pyb.param('top_10_pct_symbols') or []


def execute_quality_strategy(ctx: ExecContext):
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


def main():
    """主函数：加载股票池 -> 财务数据计算 7 因子与前 10% -> 回测（仅行情）。"""
    print("=" * 80)
    print("质量成长 7 因子策略 - ROE/自由现金流率/收入增长/利润增长/毛利率/ROA/负债率")
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

    print(f"\n✓ 质量成长前 10% 共 {len(top_10_pct)} 只，实际持仓前 {len(target_symbols)} 只")

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
            print("质量成长 7 因子：代码排名与加权得分")
            print("=" * 80)
            sorted_stocks = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)
            n_ranked = len(sorted_stocks)
            rank_symbols = [s for s, _ in sorted_stocks]
            stock_names = get_stock_names(rank_symbols)
            stock_industries = get_stock_industries(rank_symbols)
            print(f"\n有效排名数量: {n_ranked} 只（按加权总分从高到低）")
            print(f"\n{'排名':<6} {'股票名称':<16} {'股票代码':<10} {'行业':<10} {'加权得分':<12} {'ROE%':<10} {'FCF率%':<10} {'收入增长%':<10} {'利润增长%':<10} {'毛利率%':<10} {'ROA%':<10} {'负债率%':<10}")
            print("-" * 150)
            for rank, (symbol, score) in enumerate(sorted_stocks, 1):
                name = stock_names.get(symbol, symbol)
                industry = stock_industries.get(symbol, "")
                d = factor_details.get(symbol, {})
                roe = d.get('roe')
                fcf = d.get('fcf_ratio')
                rev_g = d.get('revenue_growth')
                prf_g = d.get('profit_growth')
                gm = d.get('gross_margin')
                roa = d.get('roa')
                dr = d.get('debt_ratio')
                roe_s = f"{roe:.2f}" if pd.notna(roe) and np.isfinite(roe) else "-"
                fcf_s = f"{fcf:.2f}" if pd.notna(fcf) and np.isfinite(fcf) else "-"
                rev_s = f"{rev_g:.2f}" if pd.notna(rev_g) and np.isfinite(rev_g) else "-"
                prf_s = f"{prf_g:.2f}" if pd.notna(prf_g) and np.isfinite(prf_g) else "-"
                gm_s = f"{gm:.2f}" if pd.notna(gm) and np.isfinite(gm) else "-"
                roa_s = f"{roa:.2f}" if pd.notna(roa) and np.isfinite(roa) else "-"
                dr_s = f"{dr:.2f}" if pd.notna(dr) and np.isfinite(dr) else "-"
                name_show = (name[:14] + '..') if len(name) > 16 else name
                industry_show = (industry[:8] + '..') if len(industry) > 10 else industry
                print(f"{rank:<6} {name_show:<16} {symbol:<10} {industry_show:<10} {score:<12.4f} {roe_s:<10} {fcf_s:<10} {rev_s:<10} {prf_s:<10} {gm_s:<10} {roa_s:<10} {dr_s:<10}")

        if hasattr(result, 'trades') and result.trades is not None and not result.trades.empty:
            csv_file = os.path.join(script_dir, 'factor_growth_trades.csv')
            result.trades.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n✓ 交易记录已保存: {csv_file}")

        if factor_details and factor_scores:
            ranking_data = []
            # 复用上面获取到的名称和行业信息；若不存在则重新获取
            all_symbols = [s for s, _ in sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)]
            stock_names_all = get_stock_names(all_symbols)
            stock_industries_all = get_stock_industries(all_symbols)
            for rank, (symbol, score) in enumerate(sorted(factor_scores.items(), key=lambda x: x[1], reverse=True), 1):
                d = factor_details.get(symbol, {})
                ranking_data.append({
                    '排名': rank,
                    '股票代码': symbol,
                    '股票名称': stock_names_all.get(symbol, symbol),
                    '行业': stock_industries_all.get(symbol, ""),
                    '加权得分': score,
                    'ROE': d.get('roe'), '自由现金流率': d.get('fcf_ratio'),
                    '收入增长': d.get('revenue_growth'), '利润增长': d.get('profit_growth'),
                    '毛利率': d.get('gross_margin'), 'ROA': d.get('roa'), '负债率': d.get('debt_ratio'),
                })
            ranking_df = pd.DataFrame(ranking_data)
            # 所有数值列保留两位小数
            ranking_df = ranking_df.round(2)
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

