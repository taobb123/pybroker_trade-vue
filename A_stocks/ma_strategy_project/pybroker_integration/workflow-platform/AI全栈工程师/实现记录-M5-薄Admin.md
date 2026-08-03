# 实现记录 · M5 薄 Admin

> 纪要：`../产品经理/协作纪要/005-MVP闭环规则-基于1.2.md`  
> 规则：`MVP闭环规则-v1.md` §4.5

## 交付

| 项 | 路径 |
|----|------|
| 表 | `admin_actions` |
| API | `/api/admin/users*` · `/api/admin/orders*` |
| 种子 | `admin@workflow.local` / `admin1234`（`role=admin`，已完成引导） |
| 前端 | `/admin` 用户/订单两页签 |

## 能力

- 用户：邮箱 / plan / status / 今日 used  
- 设 Free / Pro30 / Team；当日 +3；启用/禁用；重置引导  
- 订单：按状态筛选；pending → 标记已付 / 取消  

## 验收

- [x] 非 admin 访问 `/admin` 被拒  
- [x] admin 可改会员与额度  
- [x] 操作写入 `admin_actions`  

## 下一刀

M6：run 限流 + 订单 failed 态。
