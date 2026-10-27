# 常见问题与坑

## 多 case 相关

**Q：有 3 个 case 要分析，要跑 3 次吗？**
不要。一次传入所有输入：`tpa.py analyze <caseA> <caseB> <caseC>`，
只产出**一份** md + **一份** xlsx，每张表都带 `case` 列，报告开头有“总览”表。
逐 case 循环会产生一堆 `xxx_report.md` / `xxx.xlsx`，既难汇总又浪费磁盘。

**Q：合并产物的文件名怎么来的？**
默认取各输入的**公共父目录名**（如 `20261027_15_15+shape1027b`）；父目录不一致时用
`multi_case`；可用 `--name` 覆盖。

## 输入相关

**Q：目录里有多张卡的 trace，能直接分析吗？**
能，但**必须先问用户用哪个 rank**。标准动作：`tpa.py list <输入> --json` → 用弹框让用户选
（rank0 标推荐）→ 再 `--rank N` 显式传参。只有 1 个 GPU trace 时才可以直接继续。
不要把多个 rank 相加当作“总耗时”，那是 4 张卡各自的耗时。

**Q：日志目录里有 5 个 trace，默认分析哪个？**
默认选 `rank0`（`--rank` 可改），并自动排除 `async_llm` 这类非 GPU rank 文件。
排序规则：先按 rank 过滤 → 再按文件大小取最大。用 `list` 子命令可先看清楚。

**Q：压缩包需要先解压吗？**
不需要。支持 `.json` / `.json.gz` / `.zip` / `.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tar.xz` / 目录，
全部流式读取，不落盘。zip/tar 成员本身还是 `.gz`（torch 默认导出）也能处理，会自动再解一层。

**Q：`--trace` 和 `--rank` 冲突？**
`--trace` 先做子串过滤，`--rank` 在过滤结果里再选。同名多 rank 想指定某一个时用
`--trace rank2` 最直接。

## 阶段相关

**Q：报错 `decode 阶段只有 N 个，少于需要的 5 个`**
profile 抓的步数不够。把 profile 的 output/steps 调大（README 与历史经验推荐 **32**）重抓；
或本次就 `--decode-num N` 降低采样数（报告会写明实际采样数量，不会假装是 5）。

**Q：`prefilling+decoding` 占比很大，正常吗？**
正常。这是 `context>0 且 generation>0` 的混合段（chunked prefill 与 decode 交织，
或 profile 窗口跨了多个请求）。它不是纯 prefill 也不是纯 decode，所以单列，不混进任何一边。

**Q：为什么 prefill 有 4 段？**
chunked prefill 会把一次长 prompt 拆成多个 chunk，每 chunk 一个注解。tpa 把**全部纯 prefill 段**
相加作为 `prefilling`；只取最后一段会低估 prefill 耗时。

**Q：`before-dec` 的「阶段跨度」为什么是 `-`？**
这些是散落在阶段之间空隙里的 kernel，首尾跨度没有物理意义，故不展示。

## 分类相关

**Q：`others` 占比很高**
不是 bug，是关键字没覆盖。看 Excel `Kernels` sheet 里 `other/other` 的算子名，往
`CLASS_RULES` 补关键字（见 `classification.md`）。

**Q：`void mctlass::Kernel` 被拆成 -moe / -gemm 两种？**
这是有意为之：模板参数被剥离后原名无法区分，按是否含 `MacaGemmMoe` 打后缀。

## 准确性相关

**Q：怎么证明统计是对的？**
三条自检：
1. 报告最后一行「各 stage 之和 == GPU 耗时合计」；
2. 报告「kernel 事件数」应等于 trace 里 `cat=kernel` 的条目数（可用 `list` + 一次小脚本核对）；
3. 有 `profiler_out_*.txt` 时，用 `Self CUDA` 列合计粗对（见 `metrics.md` 第 5 节）。

**Q：为什么不用 `CUDA total` 校验？**
`CUDA total` 会把上层算子（如 `execute_*`、`vllm::moe_forward`）的耗时重复计入，
天然大于 kernel 累加值。

**Q：耗时单位？**
trace 的 `dur` 是**微秒**。Excel `*_Time` 列沿用原项目的微秒口径（兼容历史报表），
同时提供 `*_Time_ms`；Markdown 一律用毫秒。

## 环境相关

**Q：`ModuleNotFoundError: ijson` / `openpyxl`**
`pip install ijson openpyxl`。不需要 pandas。

**Q：解析要多久？**
46MB 的 `.gz`（约 250 万事件）约 8–10 秒。几十秒内都正常，不要中途 Ctrl-C 重跑。
