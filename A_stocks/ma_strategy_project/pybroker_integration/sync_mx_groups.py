#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把桌面自选分组 txt 同步到 config/mx_groups（港机只读仓库这份）。不回写桌面。"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

from mx_self_select import (
    DEFAULT_MX_GROUPS_DIR,
    group_txt_path,
    load_group_symbols_txt,
)

DEFAULT_GROUPS = ("M加", "Q", "M减", "量能", "估值因子", "23M减")


def _desktop_dir(explicit: str = "") -> str:
    if explicit:
        return os.path.abspath(explicit)
    env = str(os.environ.get("MX_DESKTOP_DIR", "") or "").strip()
    if env:
        return os.path.abspath(env)
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "桌面"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "OneDrive", "桌面"),
    ]
    for d in candidates:
        if os.path.isdir(d):
            if any(os.path.isfile(os.path.join(d, f"{g}.txt")) for g in DEFAULT_GROUPS):
                return d
    for d in candidates:
        if os.path.isdir(d):
            return d
    return candidates[0]


def _desktop_group_path(desktop: str, group: str) -> str:
    return os.path.join(desktop, f"{group}.txt")


def _format_repo_txt(group: str, codes: Sequence[str]) -> str:
    lines = [
        f"# 自选分组 {group} · 从桌面拷贝，工作流只读此文件、不回写桌面",
        f"# source_encoding=gb18030 count={len(codes)}",
        *list(codes),
        "",
    ]
    return "\n".join(lines)


def _diff_codes(old: Sequence[str], new: Sequence[str]) -> Tuple[List[str], List[str], bool]:
    old_set, new_set = set(old), set(new)
    added = [c for c in new if c not in old_set]
    removed = [c for c in old if c not in new_set]
    order_changed = list(old) != list(new) and old_set == new_set
    return added, removed, order_changed


def sync_one(
    group: str,
    *,
    desktop: str,
    groups_dir: str,
    write: bool,
) -> int:
    src = _desktop_group_path(desktop, group)
    dst = group_txt_path(group, groups_dir)
    print("-" * 72)
    print(f"【{group}】")
    print(f"  桌面: {src}")
    print(f"  仓库: {dst}")
    if not os.path.isfile(src):
        print("  跳过：桌面没有该文件，不覆盖仓库")
        return 0
    new_codes, notes = load_group_symbols_txt(src)
    for line in notes:
        print(f"  {line}")
    if not new_codes:
        print("  跳过：桌面未解析到代码，不覆盖仓库")
        return 2
    old_codes, _ = load_group_symbols_txt(dst) if os.path.isfile(dst) else ([], [])
    added, removed, order_changed = _diff_codes(old_codes, new_codes)
    if not added and not removed and not order_changed:
        print(f"  与仓库一致（{len(new_codes)} 只），未改写")
        return 0
    for code in added:
        print(f"  + {code}")
    for code in removed:
        print(f"  - {code}")
    if order_changed:
        print("  顺序已按桌面调整")
    print(f"  {len(old_codes)} 只 → {len(new_codes)} 只")
    if not write:
        print("  预览模式，未写入")
        return 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(_format_repo_txt(group, new_codes))
    print(f"  已写入 {dst}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="同步桌面自选分组 txt 到 config/mx_groups")
    parser.add_argument("--desktop", default="", help="桌面目录（默认自动探测 Desktop/桌面）")
    parser.add_argument(
        "--groups",
        default=",".join(DEFAULT_GROUPS),
        help="逗号分隔分组名，默认 M加,Q,M减,量能,估值因子,23M减",
    )
    parser.add_argument(
        "--groups-dir",
        default="",
        help="仓库分组目录（默认 config/mx_groups）",
    )
    parser.add_argument("--check", action="store_true", help="只对比，不写文件")
    args = parser.parse_args(list(argv) if argv is not None else None)

    desktop = _desktop_dir(str(args.desktop or "").strip())
    groups_dir = os.path.abspath(str(args.groups_dir or "").strip() or DEFAULT_MX_GROUPS_DIR)
    groups = [g.strip() for g in str(args.groups or "").split(",") if g.strip()]
    print("=" * 72)
    print("同步桌面自选分组 → config/mx_groups（不回写桌面）")
    print(f"桌面: {desktop}")
    print(f"仓库: {groups_dir}")
    print("=" * 72)
    if not groups:
        print("✗ 未指定分组")
        return 2
    worst = 0
    for g in groups:
        rc = sync_one(g, desktop=desktop, groups_dir=groups_dir, write=not args.check)
        worst = max(worst, rc)
    print("-" * 72)
    if worst:
        print("有分组未同步成功。改完桌面文件后再跑一次，然后 git add / commit，由你手动 push。")
    else:
        print("下一步：git add config/mx_groups && git commit，由你手动 push 上港机。")
    return worst


if __name__ == "__main__":
    sys.exit(main())
