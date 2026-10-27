# 统计口径与准确性校验

## 1. 整体 GPU 耗时

| 指标 | 定义 | 说明 |
| --- | --- | --- |
| GPU 耗时合计 | `Σ dur`（`cat == "kernel"` 全部事件） | GPU 上所有 kernel 的累计执行时间 |
| profile 覆盖时长 | `max(ts+dur) - min(ts)` | 首个 kernel 到末个 kernel 的墙钟跨度 |
| GPU 忙碌率 | 合计 / 覆盖时长 | 越接近 100% 说明 GPU 越少空转 |

> 若 kernel 分布在多个并发流（报告里的「kernel 并发流数」> 1），`Σ dur` 会包含并发重叠，
> **不能**当作墙钟时间。此时墙钟请用「profile 覆盖时长」。

## 2. 阶段划分

只有 `cat == "gpu_user_annotation"` 且 name 以 `execute_` 开头的注解参与划分。
vLLM 的命名形如：

```
execute_context_1(12288)_generation_0(0)
         │        │            │       └── 括号内 = 生成长度
         │        │            └────────── generation 编号 / 括号内 = 实际 gen 数
         │        └─────────────────────── 括号内 = context 长度
         └──────────────────────────────── context 编号
```

判定用 `context_N(...)` 与 `generation_M(...)` 的**编号**：

| 条件 | 阶段 | 含义 |
| --- | --- | --- |
| N > 0 且 M == 0 | `p` | 纯 prefill（含 chunked prefill 的各个 chunk） |
| N == 0 且 M > 0 | `d` | 纯 decode |
| N > 0 且 M > 0 | `pd` | prefill+decode 混合段 |

阶段标签与报告中的名字：

| 标签 | 报告名 | 是否进入「阶段口径」 |
| --- | --- | --- |
| p | `prefilling` | 是（全部段求和） |
| pd | `prefilling+decoding` | 是（单列，避免和纯 prefill 混淆） |
| d（最后 5 个） | `decoding` | 是 |
| d（更早） | `decoding(excluded)` | 否，仅计入全量 |
| 阶段之间的空隙 | `before-dec` | 是 |
| 第一个阶段之前 | `before-pre` | 是 |
| 最后采样阶段之后 | `after-dec` | 是 |

## 3. decode 采样

- 默认 **只取时间线上最后 5 个纯 decode 段**（`--decode-num` 可调）。
- 报告与 Excel 的 `Summary` 都会写明「decode 采样数量 = 5」，避免读者误以为是全量。
- 采样原因：decode 段数量取决于 profile 抓取步数，动辄几十上百段，逐段统计既慢又没有比较价值。

## 4. 为什么逐 kernel 唯一归属

每个 kernel 只被分配到一个 stage 标签，因此：

```
Σ(各 stage 的 kernel 耗时) == GPU 耗时合计
```

报告最后一行会做这条自校验。若你自己写脚本分析，请保持同样的不重不漏原则。

## 5. 与 `profiler_out_*.txt` 交叉校验

torch profiler 同时会导出 `profiler_out_0.txt` 之类的 `key_averages` 表。可以粗对：

1. 打开该文件，取 **`Self CUDA` 列**（不是 `CUDA total`，后者对上层算子会重复计数）。
2. 全表 `Self CUDA` 之和 ≈ tpa 的「GPU 耗时合计」（允许 1~3% 误差，原因是 profiler 的
   `Memset`/`Memcpy` 是否计入、以及 key_averages 的取整）。
3. `# of Calls` 之和 ≈ tpa 的「kernel 事件数」。

tpa 只统计 `cat == kernel`，**不含** `gpu_memset` / `gpu_memcpy`。若需要把 memset 也算进来，
可在 `parse_trace()` 里把这两个 cat 一并收集（会影响与历史报表的可比性，谨慎）。

## 6. 大类按 prefill / decode 拆分

报告与 Excel 的 `Classes` 表除总耗时外，还给出两组列：

| 列 | 含义 | 分母 |
| --- | --- | --- |
| `prefill_ms` / `pct_of_prefill` | 该大类在 `prefilling` 阶段的耗时及占 prefill 总耗时比例 | `stage_us[prefilling]` |
| `decode_ms` / `pct_of_decode` | 该大类在 `decoding`（最后 5 段采样）的耗时及占比 | `stage_us[decoding]` |
| `pd_ms` | 该大类在 `prefilling+decoding` 混合段的耗时 | — |

注意：

- `prefill + decode + pd + 其他阶段` 之和 = 该大类总耗时，不会重复计。
- decode 列只含采样段；`decoding(excluded)` 中的耗时不在该列。
- 想算「某个大类的全部 decode 开销」需自行加回 `decoding(excluded)` 部分（只在 `Kernels`/
  `Stages` 维度可拆，`Classes` 表未单独给出）。

## 7. 性能参考
| 数据规模 | 单文件耗时 |
| --- | --- |
| 约 250 万事件 / 2.8 万 kernel / 46MB gz | 约 8–10 秒 |
| compare（两个上述文件） | 约 16 秒 |
| 500 万事件级 | 30 秒量级 |

瓶颈是 gzip 解压 + ijson 流式解析，内存占用很低（只保留 kernel 与注解）。
不要改成 `json.load`，大 trace 会直接吃掉几 GB 内存甚至 OOM。
