import re
import sys
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def parse_namespace_line(line: str) -> tuple[int | None, int | None]:
    """从 Namespace 行提取 input_len 和 output_len"""
    match = re.search(r'\binput_len=(\d+).*?\boutput_len=(\d+)', line)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def parse_benchmark_block(lines: list[str]) -> dict:
    """解析 Serving Benchmark Result 块"""
    result = {}
    for line in lines:
        line = line.strip()
        if not line or ':' not in line:
            continue
        try:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip().split()[-1]
            result[key] = value
        except:
            continue
    return result


def extract_batch_size(parsed: dict) -> int | None:
    """从已解析的 block 中提取 Batch Size"""
    if "Maximum request concurrency" in parsed:
        return int(float(parsed["Maximum request concurrency"]))
    if "Max request concurrency" in parsed:
        return int(float(parsed["Max request concurrency"]))
    return None


def display_dynamic_table(result_list: list, model_name: str, output_file: str):
    """动态 Rich 表格 + CSV（使用同一数据源）"""
    if not result_list:
        console.print("[red]没有可展示的数据[/red]")
        return

    # 1. 构建 DataFrame
    df = pd.DataFrame(result_list)

    # 2. 把 Batch Size、Input Len、Output Len 放到最前面
    priority_cols = ["Batch Size", "Input Len", "Output Len"]
    other_cols = [col for col in df.columns if col not in priority_cols]
    df = df[priority_cols + other_cols]

    # ==================== Rich 表格（动态列） ====================
    table = Table(
        title=f"Benchmark Result - {model_name}",
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )

    for field in df.columns:
        table.add_column(field, justify="right")

    for _, row in df.iterrows():
        row_values = []
        for col in df.columns:
            val = row[col]
            if isinstance(val, float):
                row_values.append(f"{val:.2f}")
            else:
                row_values.append(str(val))
        table.add_row(*row_values)

    console.print(table)

    # ==================== 保存 CSV（与终端使用同一数据） ====================
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    console.print(f"\n[green]结果已保存到: {output_file}[/green]")


def main():
    parser = argparse.ArgumentParser(description="vLLM Benchmark Log Parser")
    parser.add_argument("-i", "--input_file", help="输入的 benchmark log 文件路径")
    parser.add_argument("--model_name", help="模型名称")
    parser.add_argument("-o", "--output", help="输出CSV路径（默认与输入同名.csv）", default=None)

    args = parser.parse_args()

    input_path = Path(args.input_file)
    model_name = args.model_name
    output_path = Path(args.output) if args.output else input_path.with_suffix(".csv")

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    all_results = []          # 改为 list，保留每一次 case
    current_input_len = None
    current_output_len = None
    result_start = -1
    JD_bs = None

    for idx, line in enumerate(lines):
        if "Traffic request rate:" in line:
            JD_bs = int(float(line.strip().split(' ')[-1]))

        if "Namespace(" in line:
            il, ol = parse_namespace_line(line)
            if il is not None and ol is not None:
                current_input_len = il
                current_output_len = ol

        # 找到结果块开始
        if "Serving Benchmark Result" in line and result_start == -1:
            assert current_input_len is not None and current_output_len is not None, "无法解析到input_len或者output_len"
            result_start = idx + 1
            continue

        # 找到结果块结束
        if result_start > 0 and "==================================================" in line:
            result_lines = lines[result_start:idx]
            parsed = parse_benchmark_block(result_lines)

            if parsed and current_input_len is not None and current_output_len is not None:
                out_bs = extract_batch_size(parsed)
                
                bs = int(out_bs or JD_bs)

                # 构建当前 case 数据
                case_data = {}
                case_data["Batch Size"] = bs
                case_data["Input Len"] = current_input_len
                case_data["Output Len"] = current_output_len
                
                for k, v in parsed.items():
                    try:
                        case_data[k] = float(v)
                    except:
                        case_data[k] = v

                # 直接保留每一次的结果，不再合并/取平均
                all_results.append(case_data)

            result_start = -1
            current_input_len = None
            current_output_len = None
            JD_bs = None

    display_dynamic_table(all_results, model_name, str(output_path))


if __name__ == "__main__":
    main()