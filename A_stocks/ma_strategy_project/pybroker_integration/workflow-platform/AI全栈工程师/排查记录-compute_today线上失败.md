# 排查记录 · compute_today 线上失败 / 本地正常

日期：2026-08-05

## 现象

线上「做 T 止盈止损」日志：

```
正在运行 结果1: .../train_model_shift.py
运行失败，退出码：1
[exit_code=0]   ← UI 仍显示成功
```

## 根因（两层）

### 1. 退出码未向上传递（已修）

`compute_today_prices.run_training_scripts` 失败后 `main()` 只 `return`，进程仍以 **0** 退出。  
`workflow_server` 的 `merged_log_stderr=on_error` 因此**不展示 stderr**，真实报错（如 `ModuleNotFoundError: pybroker`）被藏掉。

### 2. 线上依赖缺口（高概率）

`requirements-server.txt` 原先写明 **不含 pybroker**；而 `train_model_shift.py` 硬依赖：

- `lib-pybroker`（import pybroker）
- `scikit-learn`
- `numba`
- `matplotlib`

本地有完整环境；香港 ECS `.venv` 若只装了精简 requirements，子进程会在 import 阶段 exit 1。

## 修复

| 项 | 改动 |
|----|------|
| 退出码 | 训练失败 / 缺 CSV → `sys.exit(1)` |
| 日志 | 子进程 stdout/stderr 捕获后打到父进程 stdout，网页可见 |
| 依赖 | `requirements-server.txt` 增加 `scikit-learn` / `numba` / `lib-pybroker` |

## 部署后验证

1. 推送并等 HK ECS Deploy 绿  
2. 重跑 `compute_today`：若仍失败，日志应出现**完整 traceback**  
3. SSH 可选自检：  
   `/root/.../pybroker_integration/.venv/bin/python -c "import pybroker,sklearn,numba"`
