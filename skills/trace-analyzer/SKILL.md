---
name: trace-analyzer
description: 分析 torch.profiler 导出的 trace（单个 .json / .json.gz / .pt.trace.json.gz，或包含它们的 zip / tar.gz / 目录，无需手动解压），输出算子分类（大类+子类）耗时、整体 GPU 耗时、prefill/decode 各阶段耗时，生成 Markdown 报告与 Excel；同时支持对照组/实验组对比。适用于「分析 profile」「算子耗时统计」「prefill decode 耗时」「解码阶段耗时」「算子分类占比」「trace.json.gz 报告」「对比两次 profile」等场景。
argument-hint: "<trace 文件|目录|压缩包>  或  compare <ctl> <exp>"
---

# Torch Profile 分析（tpa）

把 torch.profiler trace 变成**可读报告**：算子分类耗时 + 阶段耗时 + 整体 GPU 耗时 + Excel 明细。
支持**直接吃压缩包，不需要手动解压**；单组分析不需要对照组；对比功能保留。

> 安装位置：`~/.agents/skills/trace-analyzer`（相对软链到 `~/project/ModelzooTool/skills/trace-analyzer`）。
> 下文 `<skill>` 均指该目录，脚本为 `<skill>/scripts/tpa.py`。

## 什么时候用

- 有一份 `*.pt.trace.json.gz` / `*.json` / 压缩包 / 日志目录，想知道 GPU 时间花在哪。
- 想知道 prefill / decode 各阶段耗时、decode 单步耗时。
- 想按算子大类 / 子类看占比（attention / gemm / moe / communication / norm …）。
- 想比较两次 profile（改动前后）的算子耗时差异。

## 步骤 0（强制）：先探测 trace，再确认 rank

**用户只给一个路径并要求“分析一下”时，不要直接跑 analyze。** 先做两件事：

### 1. 探测候选 trace

```bash
python <skill>/scripts/tpa.py list <输入路径> --json
```

JSON 里关键字段：`candidates[].rank` / `size_mb` / `is_async_llm` / `recommended`，以及顶层的
`gpu_rank_count`（排除 `async_llm` 后的 GPU trace 数）和 `recommended`（默认候选）。

### 2. 询问用户用哪个 rank

| 探测结果 | 动作 |
| --- | --- |
| `gpu_rank_count == 1` | 告诉用户“仅发现 1 个 GPU trace（rankN），将使用它”，然后直接继续，**不要打断** |
| `gpu_rank_count > 1` | **必须弹框询问**（见下），默认推荐 **rank0** |
| `gpu_rank_count == 0` | 说明没找到 GPU trace（可能只有 `async_llm` 或格式不支持），列出候选让用户确认 |

**弹框要求：**

- 用 `vscode_askQuestions` 弹出**可点选**的对话框，不要用纯文本提问；
- 标题 / 问题 / 选项一律用**中文**；
- 选项逐个列 rank（来自 `list` 结果），`rank0` 标 `recommended: true`；
- 对比模式**一次弹框问两个问题**（`CTL 用哪个 rank` / `EXP 用哪个 rank`），各自推荐 rank0；
- 用户跳过或未答 → 采用推荐值（rank0）。

**弹框示例（对比模式）：**

| header | 问题 | 选项 |
| --- | --- | --- |
| 对照组 rank | 对比的对照组（CTL）使用哪个 rank？ | `rank0（推荐）` / `rank1` / `rank2` / `rank3` |
| 实验组 rank | 对比的实验组（EXP）使用哪个 rank？ | `rank0（推荐）` / `rank1` / `rank2` / `rank3` |

### 3. 显式传 rank

拿到答案后**显式**传参，不要依赖默认值：

```bash
python <skill>/scripts/tpa.py analyze <input> --rank 0 ...
python <skill>/scripts/tpa.py compare <ctl> <exp> --rank-ctl 0 --rank-exp 0 ...
```

> 若用户选的 rank 在某一侧不存在，脚本会打印告警并回退到默认候选，需在回复中告知用户。

## 一条命令

```bash
# 单组分析（输入可以是：trace 文件 / .gz / zip / tar.gz / 目录）
python <skill>/scripts/tpa.py analyze <input> \
  --outdir <输出目录> --name <名字> --summary-json <输出目录>/<名字>_summary.json

# 多 case 分析：一次传多个输入，只输出【一份】md + 【一份】xlsx
python <skill>/scripts/tpa.py analyze <caseA> <caseB> [<caseC> ...] \
  --outdir <输出目录> --summary-json <输出目录>/<父目录名>_summary.json

# 对比（ctl=对照组基线，exp=实验组新版本）
python <skill>/scripts/tpa.py compare <ctl_input> <exp_input> \
  --outdir <输出目录> --name <对比名>

# 不确定输入里有哪些 trace（多 rank / async_llm 混杂时）
python <skill>/scripts/tpa.py list <input> --json
```

> **硬规则：有多个 case 时，必须用上面第 2 条一次性批量分析，禁止对每个 case 循环调用 `analyze`。**
> 逐 case 分析会产生一堆 `xxx_report.md` / `xxx.xlsx`，既难汇总也浪费磁盘与 token。
> 合并产物的每张表都带 `case` 列，总览表在报告最前面。

## 产物

| 产物 | 内容 |
| --- | --- |
| `<name>_report.md` | **主交付物**：整体 GPU 耗时、阶段表、**「主视图」（大类 Top 12 + 每类子类 Top 3）**、Top 算子、口径与校验 |
| `<name>.xlsx` | 6 个 sheet：`Summary` / `Stages` / **`Types`（class/type 全量明细，按耗时降序）** / `Classes` / `Kernels` / `Hierarchy`（层级合计，兼容原工具风格） |
| `<name>_summary.json` | 极小摘要（约 50 行），给 agent / 自动化用；`classes` = **全量大类**，`top_kernels` 覆盖每个大类 |
| 多 case 模式 | **仍然只有一份** `<stem>_report.md` + 一份 `<stem>.xlsx` + 一份 `<stem>_summary.json`；`<stem>` 默认为各输入的公共父目录名（如 `20261027_15_15+shape1027b`），可用 `--name` 覆盖 |
| `compare` 模式 | `*_compare.md` + `*_compare.xlsx`（`Compare` sheet 沿用原项目列名与 `Performance[kernel_class\|kernel_type](%)` 口径） |

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--rank N` | 优先选 `rankN` / `epN` 的 trace，默认 `0`；**用户选定后请显式传** |
| `--rank-ctl` / `--rank-exp` | compare 模式下两侧分别指定 rank |
| `--trace SUBSTR` | 文件名子串精确指定（多 rank 时最稳） |
| `--decode-num N` | decode 采样段数，默认 **5**（报告会写明采样数量） |
| `--top N` | Markdown 表格行数，默认 15（想省 token 就调小） |
| `--outdir` | 输出目录，默认 `./tpa_out` |
| `--summary-json` | 额外输出极简 JSON 摘要 |
| `--json` | 仅 `list`：输出结构化候选列表，供生成弹框选项 |

## 产物

| 产物 | 内容 |
| --- | --- |
| `<name>_report.md` | **主交付物**：整体 GPU 耗时、阶段表、**「主视图」（大类 Top 12 + 每类子类 Top 3）**、Top 算子、口径与校验 |
| `<name>.xlsx` | 6 个 sheet：`Summary` / `Stages` / **`Types`（class/type 全量明细，按耗时降序）** / `Classes` / `Kernels` / `Hierarchy`（层级合计，兼容原工具风格） |
| `<name>_summary.json` | 极小摘要（约 50 行），给 agent / 自动化用；`classes` = **全量大类**（含 `indexer` / `mhc`），`top_kernels` 覆盖每个大类 |
| `compare` 模式 | `*_compare.md` + `*_compare.xlsx`（`Compare` sheet 沿用原项目列名与 `Performance[kernel_class|kernel_type](%)` 口径） |

## 统计口径（报告里也会重复声明）

- **整体 GPU 耗时** = 全部 `cat == "kernel"` 事件的 `dur` 累加；同时给出 profile 覆盖时长与 GPU 忙碌率。
- **阶段划分**来自 `cat == "gpu_user_annotation"` 且 name 以 `execute_` 开头的注解：
  `context_N(...)` 与 `generation_M(...)`：`N>0 且 M==0` → prefill；`N==0 且 M>0` → decode；两者都 >0 → 混合段。
- **prefill** = 所有纯 prefill 段之和（chunked prefill 会有多段）。
- **decode = 只取时间线上最后 5 个纯 decode 段**，更早的 decode 段标记 `decoding(excluded)`，只计入全量。
- 阶段之外的空隙不丢：分别落到 `before-pre` / `before-dec` / `after-dec`。
- **算子大类表按 prefill / decode 拆分**：每个大类同时给出「prefill 耗时 + 占 prefill」与「decode 耗时 + 占 decode」；`prefilling+decoding` 混合段单列提示，Excel `Classes` 有 `pd_ms` 列可查。
- **自校验**：各 stage 的 kernel 耗时之和必须等于 GPU 耗时合计（逐 kernel 唯一归属）。

## 给 agent 的省 token 约定（重要）

1. **只读 `*_report.md` 或 `--summary-json`**。不要 `cat` trace 文件、不要读 `.xlsx`、不要自己写 Python 重新统计。
2. 一次命令跑完；不要为了探索而逐段读 JSON。需要细节时先看摘要，再定向追问脚本。
3. **`list --json` 只跑一次**：候选列表拿到就用于弹框，不要反复扫描目录（大目录 + 多个归档会累积耗时）。
4. **多 case 一次跑**：多个输入写在同一行命令里，产物只有一份 md + 一份 xlsx；不要把多个 case 拉成多次调用。
5. 表格太长就 `--top 8`；用户没要求明细就不要把整张表贴回对话。
6. 需要某个具体算子的数值时，用 `--summary-json` 里的 `top_kernels`，或让脚本输出一次（不要手算）。
7. 默认只分析 **rank0** 一个 trace（除非用户在弹框里选了别的）；不要批量跑全部 rank。

## 分类体系（简要）

**大类 = 实现来源，子类 = 业务**（用户 2026-10-29 口径）。报告主视图就按 `class/type` 汇报，
这样才能直接定位到“该找哪个优化团队”。

- 实现来源大类：**`torch`**（C++/CUDA 扩展，eager trace 里 cpu_op 形如 `_C::xxx`）/
  **`triton`**（`@triton.jit`，调用栈有 `triton/runtime`）/ **`tilelang`**（`*_tilelang_kernel`）
- 库 / 框架大类：`communication`（mccl）、`gemm`（mctlass / mcblas）、`moe`（mctlass 的 moe gemm）、
  `attention`（flash-mla 的 sparse_attn / mla）、`sampling`、`elementwise`、`norm`、`activation`、
  `softmax`、`other`

> `indexer` / `mhc` **不再单独立大类、也不再拆多个子类**：它们的 kernel 分别属于
> triton / torch / tilelang，统一体现在各自的 `indexer`、`mhc` 子类上
> （`triton/indexer`、`torch/indexer`、`tilelang/mhc`、`triton/mhc`）。

子类示例：

- `torch → moe_sum | moe_topk | moe_align_block | moe_sort_tokens | indexer | kv_cache |
  quant | silu_and_mul | layernorm | custom_op`
  （`void-vllm::…` 扩展 kernel，cpu_op 为 `_C::…` / `_moe_C::…`）
- `triton → indexer | mhc | rope | engram | kv_cache | sampling | silu | generated | other`
  （`_fused_indexer_q_rope_int8_quant_kernel` / `int8_mqa_logits_kernel` / `topKPerRow*` 归 `indexer`；
  `_inv_rope_kernel`、`_engram_lookup_int8_kernel`、`_gumbel_sample_kernel`、`triton_poi_fused_*`）
- `tilelang → mhc | other`（`mhc_pre_big_fuse_with_norm_tilelang_kernel`、`mhc_post_tilelang_kernel`）
- `attention → sparse_attn | kv_cache | mla | flash_attn | attn_merge | paged_attn`
  （`sparse_attn` = DSv4 稀疏注意力的**本体计算**：prefill 走 `sparse_attn_global_fwd_kernel`
  （参数类型 `SparsePrefillParams`）、decode 走 `flash_fwd_splitkv_sparse_mla_kernel`）
- `communication → all_reduce | all_gather | all_to_all | send_recv | other`
- `gemm → mctlass | mcblas`（**只分这两类**；`gemv` / `cublas` 并入 `mcblas`）
- `moe → mctlass | other`（moe 的 GEMM 是 mctlass，子类也叫 `mctlass` 不叫 `gemm`；调度 kernel 归 `torch/moe_*`）
- `sampling → topk | other`（`mbtopk` 等 aten 采样算子）

> **来源块的规则必须排在最前**：`torch` / `triton` / `tilelang` 块放在 `moe` / `attention` /
> `sampling` 之前，否则 `triton_poi_fused_*silu*` 会被 `activation` 吃掉、`void-vllm::moe::*`
> 会被 `moe` 吃掉、`_compute_global_topk_indices_and_lens_kernel` 会被 `sampling/topk` 吃掉。
> 而 `torch/custom_op` 的 `void-vllm::` 兜底必须放在**最后**（它只该接住没被具体子类命中的）。

**呈现约定**（用户 2026-10-29 指定）：

- 报告里的标题就叫「**主视图**」，结构固定为两层：
  1. **大类 Top 12**（按总耗时降序，带占 GPU、prefill / decode 拆分）；
  2. **每个大类下子类 Top 3**（带占本类、占 GPU、prefill / decode 的耗时与占比）。
- Excel `Types` / `Classes` sheet 保留**全量**明细（不截断），作为主视图的下钻数据。
- 「单算子」表在 Top N 之外**额外补齐每个大类的最佳条目**，避免小类整段缺席。
- `--summary-json` 里 `classes` 是全量大类（`top_classes` 保留为 Top N 兼容字段）。

新增/调整规则：改 `scripts/tpa.py` 顶部的 `CLASS_RULES`（顺序敏感，先命中先返回）。
详见 `./references/classification.md`。

## 校验与排错

- 报告末尾「统计口径与校验」一节会自动列出：kernel 数、事件数、各阶段之和 = 总耗时、解析告警。
- 有 `profiler_out_*.txt` 时，可用其中 `Self CUDA` 的合计粗对总耗时（方法见 `./references/metrics.md`）。
- 报「decode 阶段只有 N 个」→ profile 抓的步数不够，把 output/steps 调大（推荐 32）重抓，或 `--decode-num N` 降低采样。
- 更多坑见 `./references/pitfalls.md`。

## 依赖

`ijson`（流式解析，必需）+ `openpyxl`（写 Excel）。不需要 pandas。

```bash
pip install ijson openpyxl
```
