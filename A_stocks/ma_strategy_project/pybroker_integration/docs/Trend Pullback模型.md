如果你的目标是**程序化识别“主升浪中的震荡下沿”**（类似你图中的紫色均线附近反复支撑区域），不要直接找最低点，而应该识别：

> 主升趋势成立 → 回调 → 回调结束 → 支撑确认

这是量化里比较经典的 **Trend Pullback（趋势回踩）模型**。

---

# 一、先定义主升阶段

图中明显属于：

* 20日均线向上
* 60日均线向上
* 股价远离120日均线
* 成交量放大

可以先建立：

```python
MA20 > MA60
MA60 > MA120

MA20斜率 > 0
MA60斜率 > 0

Close > MA60
```

进一步加强：

```python
(最高价 - 60日最低价) / 60日最低价 > 30%
```

即：

```text
60日涨幅超过30%
```

说明已经进入主升。

---

# 二、寻找震荡下沿

观察你的图：

182元见顶
↓
回踩到160附近
↓
再次反弹

160就是震荡下沿。

本质上是：

```text
最近N天最低点附近被多次验证
```

代码条件：

```python
window = 20

support = LOW.rolling(window).min()
```

然后判断：

```python
abs(Close - support) / support < 3%
```

即：

```text
距离20日最低点不超过3%
```

---

# 三、用均线代替支撑位（更稳定）

主升浪里真正有意义的支撑往往是：

* MA10
* MA20
* MA30

而不是绝对价格。

你的图中：

```text
股价多次踩MA20
```

因此可以定义：

```python
Close > MA20

(Low - MA20)/MA20 < 2%
```

即：

```text
最低价触碰20日线
```

---

# 四、识别“回调结束”

这是最关键的一步。

很多人买在下跌途中。

应该增加：

### 条件1：缩量

```python
VOL < MA5_VOL
```

说明抛压减弱。

---

### 条件2：跌幅有限

主升浪回调一般：

```text
5%-15%
```

很少超过20%。

计算：

```python
pullback = (近期最高价 - 当前价) / 近期最高价
```

要求：

```python
5% < pullback < 15%
```

---

### 条件3：止跌阳线

例如：

```python
Close > Open
```

或者

```python
Close > 昨日最高价
```

即：

```python
反包
```

---

# 五、识别震荡下沿（推荐）

综合条件：

```python
# 主升趋势

MA20 > MA60
MA60 > MA120

# 回调

Close < HHV(Close,20)

回调幅度:
5% ~ 15%

# 下沿

Low <= MA20*1.02

# 缩量

VOL < MA5(VOL)

# 止跌

Close > Open
```

满足后：

```text
主升浪震荡下沿
```

触发信号。

---

# 六、如果你想识别图中这种“箱体下沿”

更推荐使用：

```python
最近20天

最高价 = HHV(HIGH,20)

最低价 = LLV(LOW,20)
```

计算：

```python
position =
(Close - 最低价)
/
(最高价 - 最低价)
```

当：

```python
position < 0.3
```

说明：

```text
股价位于箱体下沿30%区域
```

再叠加：

```python
MA20 > MA60
```

即可认定：

```text
主升趋势中的震荡下沿
```

---

如果是A股中长期实战，我建议用下面这个组合，效果通常比单纯均线更好：

```python
1. MA20 > MA60 > MA120

2. 60日涨幅 > 30%

3. 当前距20日高点回撤
   5%~15%

4. Low接近MA20
   （误差2%以内）

5. 成交量低于5日均量

6. 收阳线
```

这套逻辑本质上抓的是：

**“主升浪第一次或第二次回踩20日线形成的震荡下沿买点”**，对应很多牛股最容易出现二波启动的位置。

---

# 七、项目内实现（pybroker_integration）

脚本：`fetch_trend_pullback.py`（工作流步骤 **主升震荡下沿（Trend Pullback）**）

**双路径（满足其一即历史命中，`signal_path` 列标注）：**

| 路径 | 场景 | 要点 |
|------|------|------|
| A `ma20_pullback` | 主升浪浅回踩 MA20 | 6 条组合；**60 日**收盘高点回撤约 **4%～22%**（默认可覆盖更深回踩） |
| B `box_lower` | 高位震荡箱体下沿 | 主升未坏 + 20 日 `position<0.35` + **20 日**高点回撤约 **4%～25%** + 贴 MA20/30（容差略放宽） |

- **默认**：`config/trend_pullback_range.yaml` 历史区间用于寻找最近下沿命中；主表 `trend_pullback_scan.csv` 经筹码硬过滤后按 `score_total` 排序。
- **第三层筹码**（`trend_pullback_chips.py`，Tushare `cyq_chips`）：
  - 口诀3「高位单峰底仓空」、口诀4「多峰分散无主力」→ **硬过滤，不进表**
  - 口诀2「上涨多峰底不动，回踩主峰」→ 回踩主峰加分
  - 口诀1「低位单峰底仓稳，放量突破」→ **主升突破** 独立信号
  - 「可能新主升」仅作展示标签（未满足主升突破时的补充识别）
  - 评分 = 下沿结构(30%) + 回踩主峰(25%) + 主升突破(25%) + 筹码质量(20%)
- 工作流：自选列表 + 回测区间 → `trend_pullback_scan.csv`（`signal_type` 列区分两类）。
- 需完整历史逐日命中：`--hits-csv 路径`；控制台命中列表：`--print-hits`。
- 重显已算好的最近下沿参考（命中日收盘，仅控制台）：YAML `PRINT_BACKTEST_LOWER: true` 或 `--print-backtest-lower`。
- 仅截止日：`--snapshot`。

```bash
python pybroker_integration/fetch_trend_pullback.py
python pybroker_integration/fetch_trend_pullback.py --symbols 600563
```
