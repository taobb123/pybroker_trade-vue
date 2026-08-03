# 实现记录 · M6 限流与订单 failed

> 纪要：`../产品经理/协作纪要/005-MVP闭环规则-基于1.2.md`  
> 规则：`MVP闭环规则-v1.md` §4.6

## 交付

| 项 | 说明 |
|----|------|
| 限流 | `rate_limit.py`：每用户每 60 秒 ≤ 10 次（`MVP_RUN_RATE_LIMIT`） |
| API | `/api/quota/consume` 超限返回 **429**，不扣日配额 |
| 订单态 | 渠道回调失败 → **failed**；用户/Admin 取消 → **cancelled** |
| 纠偏 | Admin 对 `pending` / `failed` 可 mark paid 或 cancel |

## 验收

- [x] 连续刷跑第 11 次被拒（限流文案）  
- [x] 模拟回调失败订单为 `failed`  
- [x] Admin 可将 `failed` 标记已付并开通会员  

## MVP 闭环进度

M1–M6 规则切片已齐；后续为联调与产品化增强。
