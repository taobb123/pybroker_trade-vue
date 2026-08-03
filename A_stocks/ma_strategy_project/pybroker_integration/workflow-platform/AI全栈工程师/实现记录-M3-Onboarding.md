# 实现记录 · M3 Onboarding

> 纪要：`../产品经理/协作纪要/005-MVP闭环规则-基于1.2.md`  
> 规则：`MVP闭环规则-v1.md` §4.2

## 交付

| 项 | 路径 |
|----|------|
| API | `onboarding_api.py`：`GET /api/onboarding/status` · `POST /api/onboarding/complete` |
| 规则 | 推荐 `roc_20`；当日 `bonus_runs=+3`；仅首次；身份可跳过 |
| 前端 | `/onboarding` 三步页；登录后未完成强制跳转 |
| 安全 | `/api/quota/bonus` 改为仅 admin（用户走 complete） |

## 验收

- [x] 未完成引导用户无法进入工作台（路由门控）  
- [x] 完成写入 `onboarding_done=1` + 当日 +3  
- [x] 再次调用 complete 不重复加 bonus  
- [x] 完成后跳转推荐策略 `?step=roc_20`  

## 重测演示账号

若 demo 已完成引导，库内执行：

```sql
UPDATE users SET onboarding_done=0, persona=NULL WHERE email='demo@workflow.local';
```

## 下一刀

M4 五类事件埋点 + 漏斗查询。
