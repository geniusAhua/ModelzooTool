#!/usr/bin/env bash
#
# 提取每个 case 的 rank0 profile 文件并解压到指定目录
#
# 目录结构约定:
#   .../<task>/Profiler/<日期目录>/<case>/
#       <case>/.../dp0_pp0_tp0_dcp0_ep0_rank0.<ts>.pt.trace.json.gz   <- rank0 profile
#   task 名称 = Profiler 目录的上一级目录名
#
# 用法:
#   ./extract_rank0_profiles.sh <日期目录|Profiler目录> <输出目录>
#
# 示例:
#   ./extract_rank0_profiles.sh \
#       /sw_home/m01088/workarea/JD/JoyAI/H200/ShapeInfo_log/H200-JoyAI-LLM-Flash-TP4-chunk12k/Profiler/20260828_11_41 \
#       /sw_home/m01088/workarea/JD/JoyAI/H200/ShapeInfo_log/rank0_profiles
#
# 输出文件命名: {task}-{case}-rank0.pt.trace.json

set -euo pipefail

INPUT="${1:?用法: $0 <日期目录|Profiler目录> <输出目录>}"
OUT="${2:?用法: $0 <日期目录|Profiler目录> <输出目录>}"

# ---------- 1. 确定要处理的日期目录列表 ----------
if [ "$(basename "$INPUT")" = "Profiler" ]; then
    # 传入 Profiler 目录: 处理其下所有日期目录
    mapfile -t DATE_DIRS < <(find "$INPUT" -mindepth 1 -maxdepth 1 -type d | sort)
else
    DATE_DIRS=("$INPUT")
fi

if [ "${#DATE_DIRS[@]}" -eq 0 ]; then
    echo "错误: 未找到任何日期目录: $INPUT" >&2
    exit 1
fi

# ---------- 2. 自动创建输出目录 ----------
mkdir -p "$OUT"

# ---------- 3. 处理单个日期目录 ----------
extract_one() {
    local date_dir="$1"
    # task 名称 = Profiler 的上一级目录名
    local task
    task="$(basename "$(dirname "$(dirname "$date_dir")")")"

    echo "== task: $task | 日期目录: $(basename "$date_dir")"

    local found=0
    for case_dir in "$date_dir"/*/; do
        [ -d "$case_dir" ] || continue
        local case_name
        case_name="$(basename "$case_dir")"

        # 递归查找该 case 下第一个 rank0 trace 文件
        local src
        src="$(find "$case_dir" -name '*rank0*.pt.trace.json.gz' \
                     -not -path '*/.snapshot/*' | head -n 1 || true)"
        if [ -z "$src" ]; then
            echo "  [跳过] $case_name: 未找到 rank0 profile"
            continue
        fi

        # 输出命名: {task}-{case}-rank0.pt.trace.json
        local dst="$OUT/${task}-${case_name}-rank0.pt.trace.json"
        gzip -dc "$src" > "$dst"
        echo "  [完成] $case_name -> ${dst##*/}"
        found=1
    done

    [ "$found" -eq 1 ] || echo "  (该日期目录下没有任何 case 提取到 rank0 profile)"
}

# ---------- 4. 主流程 ----------
for d in "${DATE_DIRS[@]}"; do
    extract_one "$d"
done

echo "全部处理完成，输出目录: $OUT"
