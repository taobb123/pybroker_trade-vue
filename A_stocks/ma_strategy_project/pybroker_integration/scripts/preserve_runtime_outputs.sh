#!/usr/bin/env bash
# 部署 git reset --hard 前后备份/恢复工作流运行产物，避免网站观察表被仓库旧快照覆盖。
# 用法：
#   source preserve_runtime_outputs.sh
#   runtime_backup "$SRC" "$PRESERVE_DIR"
#   runtime_restore "$SRC" "$PRESERVE_DIR"

runtime_rel_items() {
  local src="$1"
  (
    cd "$src" || exit 0
    shopt -s nullglob
    local -a items=()
    items+=(
      vp_combo_watch_*.csv
      vp_six_combo_scan.csv
      dc_concept_ma5_scan.csv
      dc_concept_ma5_members.csv
      pattern_entry_*.csv
      vp_combo_23_*.csv
      vp_combo_23_vs_46_long_annual.md
      stocks_pool.txt
      config/fetch_vp_six_combo_symbols.txt
      config/fetch_pattern_entry_symbols.txt
      config/fetch_pattern_entry_symbols_*.txt
    )
    [[ -d market_neutral/archive/watch_pool ]] && items+=(market_neutral/archive/watch_pool)
    [[ -d market_neutral/output/latest ]] && items+=(market_neutral/output/latest)
    [[ -d market_neutral/output/combo23_latest ]] && items+=(market_neutral/output/combo23_latest)
    if ((${#items[@]})); then
      printf '%s\n' "${items[@]}"
    fi
  )
}

runtime_backup() {
  local src="$1"
  local dest="$2"
  mkdir -p "$dest"
  rm -f "$dest/runtime.tgz"
  [[ -d "$src" ]] || return 0
  local -a items=()
  mapfile -t items < <(runtime_rel_items "$src")
  ((${#items[@]})) || return 0
  tar czf "$dest/runtime.tgz" -C "$src" "${items[@]}"
  echo "runtime backup: ${#items[@]} paths → $dest/runtime.tgz"
}

runtime_restore() {
  local src="$1"
  local dest="$2"
  [[ -f "$dest/runtime.tgz" ]] || {
    echo "runtime restore: no backup, skip"
    return 0
  }
  mkdir -p "$src"
  tar xzf "$dest/runtime.tgz" -C "$src"
  echo "runtime restore: $dest/runtime.tgz → $src"
}
