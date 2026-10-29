# 算子分类体系与扩展方法

## 1. 两级分类

| 级别 | 字段 | 含义 |
| --- | --- | --- |
| 大类 | `kernel_class` | 算子家族（attention / gemm / moe …） |
| 子类 | `kernel_type` | 家族内的实现或语义细分 |

报告与 Excel 都以 `(kernel_class, kernel_type, kernel_name)` 三级展开，父级自动带合计行。

## 2. 匹配前先做名字规范化

`normalize_kernel_name()` 会剥掉 `<...>` 与 `(...)` 内的模板参数/实参，例如：

```
void flash_fwd_kernel<Flash_fwd_kernel_traits<192, 128, 64, 4, true, true,
     mctlass::bfloat16_t, ...>, false, false, ...>
  →  void-flash_fwd_kernel
```

**这一步是准确性的关键**：模板参数里会出现 `mctlass::bfloat16_t`、`gemm` 等字样，
不剥离就会被错误归类（例如 flash attention 被识别成 mctlass GEMM）。

特殊规则：`void mctlass::Kernel<...>` 规范化后会丢失信息，因此单独补后缀：

- 原始名含 `MacaGemmMoe` → `void-mctlass::Kernel-moe`
- 其他 `mctlass::Kernel` → `void-mctlass::Kernel-gemm`

## 3. 当前规则表（顺序敏感）

`scripts/tpa.py` 顶部的 `CLASS_RULES`，**自上而下第一条命中即返回**：

| 顺序 | 大类 | 子类 | 关键字（小写子串匹配） |
| --- | --- | --- | --- |
| 1-2 | **tilelang** | mhc / other | `mhc`, `tilelang` |
| 3-11 | **torch** | moe_sum / moe_topk / moe_align_block / moe_sort_tokens / indexer / kv_cache / quant / silu_and_mul / layernorm | `moe_sum`, `topkgating`+`topk_softplus_sqrt`, `moe_align_block`, `count_and_sort_expert_tokens`, `topkperrow`+`top_k_per_row`+`cp_gather_indexer_k_quant_cache`+`indexer`（统一归 `torch/indexer`）, `qnormrope`, `dynamic_scaled_int8_quant`, `silu_and_mul`, `rms_norm_cached` |
| 12-20 | **triton** | indexer / mhc / rope / engram / kv_cache / sampling / silu / other / generated | `fused_indexer_q_rope_int8_quant`+`int8_mqa_logits`+`topkindices`+`candidate`+`indexer`（统一归 `triton/indexer`）, `hc_head`+`mhc`, `_inv_rope`, `engram_lookup`, `zero_kv_blocks`, `gumbel`, `silu`, `save_compress_norm`, `triton` |
| 21-22 | moe | mctlass / other | `void-mctlass::kernel-moe`, `macagemmmoe`, `fused_moe_kernel`, `moe_gemm`, `moe` |
| 23-27 | communication | all_reduce / all_gather / all_to_all / send_recv / other | `allreduce`, `allgather`, `alltoall`, `broadcast`, `mccl` |
| 28-29 | gemm | mctlass / mcblas | `mctlass`；`mcblas`, `gemv`, `cublas`, `cutlass`（**只分两类**） |
| 30 | attention | sparse_attn | `sparse_attn_global_fwd`, `sparse_mla`, `flash_fwd_splitkv_sparse` |
| 31 | attention | kv_cache | `concat_and_cache`, `reshape_and_cache`, `cache_mla`, `kv_cache` |
| 32-35 | attention | attn_merge / mla / flash_attn / paged_attn | `merge_attn_states`, `_mla_`, `flash_fwd`, `paged_attention` |
| 36-37 | norm | rms_norm / layer_norm | `rmsnorm`, `layernorm` |
| 38-40 | activation | silu_and_mul / gelu / other | `silu_and_mul`, `gelu`, `silu` |
| 41-44 | elementwise | copy / add / fill / other | `direct_copy`, `functor_add`, `fillfunctor`, `elementwise` |
| 45-46 | sampling | topk / other | `mbtopk`, `bitonicsort`, `topk` |
| 47 | softmax | softmax | `softmax` |
| 48 | **torch** | custom_op | `void-vllm::`, `vllm::`（兜底，**必须在业务规则之后**） |
| 兜底 | other | other | — |

**关于 moe / gemm 的子类命名**（用户 2026-10-29 口径）：

- `gemm` **只分两类**：`gemm/mctlass` 与 `gemm/mcblas`（`gemv` / `cublas` / `cutlass` 并入 `mcblas`）。
- `moe` 的 GEMM 也是 mctlass 实现，所以子类叫 `moe/mctlass`，**不叫 `moe/gemm`**。
- `indexer` / `mhc` **不拆多个子类**：分别只留一个 `triton/indexer`、`torch/indexer`、`tilelang/mhc`、`triton/mhc`。

**为什么 moe 行放在 communication / gemm 之前**：`void mctlass::Kernel-moe` 本质是 MoE 的 GEMM，
放在 `moe/mctlass` 可以让「MoE 总开销」一眼可见；子类也写 `mctlass`（与 `gemm/mctlass` 同源）。
若你更希望把它算进 `gemm` 大类，把这条改成 `("gemm", "mctlass_moe", (...))`。

**为什么 communication 排在 gemm 前**：`mcclKernel_AllReduce_*` 名字里可能带 dtype 等字段，
先锁定通信更稳。

**为什么 indexer / mhc 排在 attention 与 sampling 之前**（2026-10-29 新增）：

- `sampling/topk` 的关键字是 `topk`，而 indexer 的 `_compute_global_topk_indices_and_lens_kernel`
  也带 `topk` —— 放后面会被错归成采样算子（实测就是这么错归的）。
- `attention/mla` 的关键字是 `_mla_`，与 indexer 的 `mqa_logits` 不同族，但两者都在稀疏注意力链路上，
  indexer 先用更具体的名字锁定，避免以后给 attention 加宽泛关键字时把 indexer 吞掉。
- `mhc_*` 与 `hc_head` 是残差/超连接（hyper-connection）的专用 kernel，与 attention/gemm 无名字冲突，
  但仍放在 gemm 之后：`mhc_pre_big_fuse_with_norm_tilelang_kernel` 里带 `norm`，若以后 `norm`
  关键字放宽（如只写 `norm`）会误吞。

## 4. indexer / mhc 的 kernel 对照（已按实现来源拆到子类）

这两个家族原本全部落在 `other`，靠下面的源码对照才能拆准。核对来源（DeepSeek-V4.1-Flash 项目）：

- `modelzoo/index_kernel/fused_indexer_q_int8.py`、`sparse_attn_indexer.py`、`sparse_attn_indexer_int8.py`
- `modelzoo/mhc_kernel/tilelang.py`、`warmup.py`

这些文件是被 `--pre-copy` 覆盖进容器的**打点版**：每个算子入口都调 `_log_shapes(tag, **tensors)`，
由 `IDX_SHAPE` / `MHC_SHAPE` 环境变量控制，打印 `[IDX-SHAPE] ...` / `[MHC-SHAPE] ...`。
⇒ 从打点 tag 可以反查「python 入口 → 底层 GPU kernel」的对应关系：

> ⚠ 下表是**历史拆分名**。按最新口径（2026-10-29）已合并：所有 `triton/indexer_*` → **`triton/indexer`**，
> `torch/indexer_topk|indexer_kv_cache` → **`torch/indexer`**，`tilelang/mhc_pre|mhc_post|mhc_fused_post_pre` →
> **`tilelang/mhc`**，`triton/mhc_head` → **`triton/mhc`**。下表保留细分名，仅用于说明 kernel 来源。

| 打点 tag / 源码函数 | trace 里的 kernel 名 | 本工具归类 |
| --- | --- | --- |
| `fused_indexer_q_rope_int8_quant` | `_fused_indexer_q_rope_int8_quant_kernel` | `triton/indexer_q_quant` |
| （index k 的 norm+rope+quant+store） | `_indexer_k_norm_rope_quant_store_kernel` | `triton/indexer_q_quant` |
| `int8_mqa_logits` / `int8_paged_mqa_logits` | `int8_mqa_logits_kernel` / `int8_paged_mqa_logits_kernel` | `triton/indexer_mqa_logits` |
| `top_k_per_row_prefill` / `_decode` / `cooperative_topk` / `persistent_topk` | 同名 + `_kernel`（torch 侧为驼峰 `topKPerRow*`） | `triton/indexer_topk` / **`torch/indexer_topk`** |
| `_merge_dcp_topk_global` | `_merge_dcp_topk_global_kernel` | `triton/indexer_topk` |
| （topk 索引与 lens） | `_compute_global_topk_indices_and_lens_kernel`、`_compute_swa_indices_and_lens_kernel` | `triton/indexer_topk` |
| `_select_candidate_blocks` / `_apply_candidate_mask` | `_candidate_flags_kernel` / `_mask_candidates_kernel` / `_block_scores_kernel` / `_store_candidates_kernel` | `triton/indexer_candidate_block` |
| （paged mqa 调度元数据） | `build_paged_mqa_schedule_metadata_kernel` | `triton/indexer_metadata` |
| `cp_gather_indexer_k_quant_cache` | `void-vllm::cp_gather_indexer_k_quant_cache_kernel` | **`torch/indexer_kv_cache`** |
| `mhc_pre_tilelang` / `mhc_pre_delayed_tilelang` / `mhc_pre_big_fuse_with_norm_tilelang`（`MHCPreNormKernel`） | `mhc_pre_big_fuse_with_norm_tilelang_kernel` 等 | **`tilelang/mhc_pre`** |
| `mhc_post_tilelang` | `mhc_post_tilelang_kernel` | **`tilelang/mhc_post`** |
| `mhc_fused_post_pre_tilelang` | `mhc_fused_post_pre_tilelang_kernel` | **`tilelang/mhc_fused_post_pre`** |
| `hc_head_fused_kernel_tilelang` | `_hc_head_reduce_store_kernel` | **`triton/mhc_head`**（triton 实现） |

要点：

- **shape 打点走的是 python 入口，不等于 trace 里的 kernel 名**：triton 侧一般是 `<函数名>_kernel`，
  tilelang 侧是 `<函数名>_kernel`（如 `mhc_pre_big_fuse_with_norm_tilelang_kernel`）。
- 打点只记 tensor 参数，且 `MHC_SHAPE`/`IDX_SHAPE` 未设置时不打印。⇒ **只用 trace 也能分类**，
  不依赖重跑打点。
- 本 trace 实测（Metax-TP8DP2-Profile-vllm-V2 / 20261009_18_36，4 case，GPU 合计 10,786 ms）：
  `mhc` 占 **6.07%**（pre 373.43 ms、post 280.06 ms、head 1.55 ms）、`indexer` 占 **1.81%**
  （topk 80.12 ms、mqa_logits 61.52 ms、candidate_block 28.07 ms、q_quant 20.25 ms、
  metadata 2.73 ms、other 2.20 ms），`other` 从 **25.5% 降到 18.3%**、
  `sampling` 从 0.77% 降到 0.16%（`topKPerRow*` 不再被当成采样）。

## 5. DSv4 各子系统看图对照表（2026-10-29 用 eager trace 核对）

DeepSeek-V4 的 attention 一层里有三块容易混淆的东西，看图时按这个顺序理解：

1. **indexer**（已拆为 `triton/indexer_*` + `torch/indexer_*`）——从整条 KV 里**选 top-k token**
   （int8 mqa logits → topk → candidate block）；
2. **sparse attention 本体**（`attention/sparse_attn`）——只在这 k 个 token 上做 attention，
   本质仍是 flash-attention 家族，只是加了稀疏索引 / mask；
3. **mhc**（已拆为 `tilelang/mhc_pre|mhc_post|mhc_fused_post_pre` + `triton/mhc_head`）——
   hyper-connection 的 pre/post 残差通路，**不是** attention。

| kernel | 归属 | 依据 |
| --- | --- | --- |
| `void-sparse_attn_global_fwd_kernel` | `attention/sparse_attn` | 模板参数 `Flash_fwd_kernel_traits<...>` + 入参类型 `SparsePrefillParams`；python 帧落在 `vllm_metax/models/deepseek_v4_1/metax/flashmla.py(278): _forward_prefill` |
| `void-flash_fwd_splitkv_sparse_mla_kernel` | `attention/sparse_attn` | decode 用的 split-kv 稀疏 MLA（`flash_mla_with_kvcache`） |
| `void-flash_fwd_splitkv_mla_combine_kernel` | `attention/mla` | 非稀疏 MLA 的 split-kv 归并 |
| `get_mla_metadata_kernel` | `attention/mla` | MLA 调度元数据 |
| `_dequantize_and_gather_int8_k_kernel` | `triton/kv_cache` | triton jit（profiler 表里单独成行、无 `_C::` 父 op）；int8 KV cache 里 K 的反量化 + gather |
| `fusedDeepseekV4QNormRopeKVRopeInt8G32Insert` | `torch/kv_cache` | cpu_op `_C::fused_deepseek_v41_qnorm_rope_kv_rope_int8_insert` ⇒ **torch 扩展算子**（Q 的 norm+rope+量化 与 KV 的 rope+插入 融合） |
| `_zero_kv_blocks_kernel` | `triton/kv_cache` | triton jit（名字形式 `_xxx_kernel`，无 `void vllm::` 前缀） |
| `dynamic_scaled_int8_quant_kernel_reg/sreg_opt` | `torch/quant` | cpu_op `_C::dynamic_scaled_int8_quant` ⇒ torch 扩展；kernel 名带 `void vllm::` 前缀 |
| `_inv_rope_kernel`、`_rope_quant_insert_kernel` | `triton/rope` | triton jit；调用栈有 `triton/runtime`，python 帧 `fused_inv_rope_quant.py: inv_rope` |
| `_engram_lookup_int8_kernel`、`_fused_engram_post_wkv_kernel` | `triton/engram` | triton jit；python 帧 `vllm_metax/models/deepseek_v4_1/engram.py(1140): prepare_embedding` |
| `_gumbel_sample_kernel` | `triton/sampling` | triton jit（投机解码的 gumbel 采样） |
| `void-vllm::silu_and_mul_clamp_flat_kernel`、`void-vllm::rms_norm_cached_kernel` | `torch/silu_and_mul` / `torch/layernorm` | torch 扩展 kernel（用户 2026-10-29 指定放 torch 下），业务子类仍写清楚；`torch/custom_op` 兜底必须放最后 |
| `Kernel`（裸名，无任何关键字） | `other` | tilelang 编译产物没带名字，**暂时无解**（只能靠同一时间段的其他 kernel 猜） |

实测效果（`20261009_18_36`，4 case 合计 10,786 ms，非 eager）：
`other` **0.81%**；`communication` 43.93%、`gemm` 12.83%（mctlass 9.40 + mcblas 3.43）、
`attention` 12.79%（sparse_attn 1,309.45 ms）、`moe` 10.63%（`moe/mctlass`）、**`torch` 6.98%**、
**`tilelang` 6.06%**（`tilelang/mhc`）、**`triton` 4.76%**。
主视图（大类 Top 12 + 子类 Top 3，均带 prefill / decode 占比）：`communication` 43.93%（all_reduce 56.82% / other 22.33% / all_gather 11.64%）、
`gemm` 12.83%（mctlass 71.93% / mcblas 28.07%）、`torch` 6.98%（moe_sum 25.06% / quant 21.68% / kv_cache 21.16%）、
`triton` 4.76%（kv_cache 35.99% / indexer 20.00% / engram 17.50%）。

## 6. 用 eager 模式 trace 核对归属（首选手段）

默认（cuda graph）trace 里只有 GPU kernel，看不出谁调的；**eager 模式**（`--enforce-eager`）
的 trace 额外有 `cpu_op` / `cuda_runtime` / `python_function`：

- `cpu_op` 直接给出自定义 op 名：`vllm::mx_sparse_attn_indexer_int8`、
  `_C::fused_deepseek_v41_qnorm_rope_kv_rope_int8_insert`、`_moe_C::topk_softplus_sqrt`、
  `_C::top_k_per_row_decode` …
- 关联链：`kernel.args.correlation` → `cuda_runtime.args.correlation` → 该 `cuda_runtime`
  时间点所在的 `cpu_op` 区间 → op 名。
- `python_function` 能给模块路径（如 `…/metax/flashmla.py(278): _forward_prefill`），
  但 kernel 常落到 `Event.synchronize` 这种空转帧上，**只能当辅助证据**。

```python
import gzip, bisect
from collections import defaultdict, Counter
import ijson

cpu, rt, kern = defaultdict(list), [], []
with gzip.open(TRACE_PATH, "rb") as f:
    for ev in ijson.items(f, "traceEvents.item"):
        cat = ev.get("cat")
        if cat == "cpu_op":
            ts = float(ev["ts"]); du = float(ev.get("dur") or 0)
            cpu[ev.get("tid")].append((ts, ts + du, ev.get("name", "")))
        elif cat == "cuda_runtime":
            a = ev.get("args") or {}
            rt.append((a.get("correlation"), float(ev["ts"]), ev.get("tid")))
        elif cat == "kernel":
            a = ev.get("args") or {}
            kern.append((a.get("correlation"), ev.get("name", ""), float(ev.get("dur") or 0)))

for t in cpu:
    cpu[t].sort()
starts = {t: [x[0] for x in v] for t, v in cpu.items()}

corr2op = {}
for corr, ts, tid in rt:
    arr = cpu.get(tid) or []
    if corr is None or not arr:
        continue
    i = bisect.bisect_right(starts[tid], ts) - 1
    for j in range(i, max(0, i - 60) - 1, -1):
        if arr[j][1] > ts:
            corr2op[corr] = arr[j][2]
            break

own = defaultdict(Counter)
for corr, nm, du in kern:
    own[nm][corr2op.get(corr, "<unresolved>")] += du
for nm, c in sorted(own.items(), key=lambda kv: -sum(kv[1].values()))[:40]:
    t = sum(c.values())
    print("%9.2f ms  %-50s <- %s" % (t / 1000, nm[:50],
          "; ".join("%s(%.0f%%)" % (o[:60], v / t * 100) for o, v in c.most_common(2))))
```

经验（Metax C588 / DSv4 INT8，实测）：

- 约 **70%** 的 kernel 耗时能解析到 cpu_op；`mccl*` 通信、`mhc_*`、`sparse_attn_*` 常是
  `<unresolved>`（metax runtime 直发），靠名字 + 上面的对照表判断。
- **eager 的绝对耗时不能和默认模式比**：同 case 的 `communication` 从 0.79 s 变成 4.4 s
  （无 cuda graph ⇒ kernel 数、同步点都变多），只能用来判断“谁调的谁”。
- `sparse_attn_global_fwd_kernel` 在 eager 下只有 **1 个名字**，但真实形状很多（grid/block 随 bs、seq 变），
  想拿 shape 仍需 `MHC_SHAPE`/`IDX_SHAPE` 那类打点，或按 `args.grid` / `args.block` 聚合。

### 6.1 怎么区分 torch 算子 / triton 算子（2026-10-29 用户口径）

用户明确的要求：**大类按实现来源走**，业务语义放子类。

| 判据 | torch 扩展算子 | triton jit kernel |
| --- | --- | --- |
| kernel 名 | 带 `void vllm::…`（或 `vllm::…`）前缀，如 `void-vllm::dynamic_scaled_int8_quant_kernel_reg_opt` | `_xxx_kernel` 形式，**没有** `void vllm::` 前缀，如 `_inv_rope_kernel`、`_engram_lookup_int8_kernel` |
| 上层 cpu_op | 有对应的 `_C::xxx` / `_moe_C::xxx`（如 `_C::dynamic_scaled_int8_quant`、`_C::fused_deepseek_v41_qnorm_rope_kv_rope_int8_insert`） | 没有 `_C::` 父 op；profiler 表里**单独成行** |
| 调用栈 | `torch/` 或 `vllm_metax/…` 的 python 封装 | 有 `triton/runtime/…` 帧 |

另外 `*_tilelang_kernel`（tilelang/jit 编译）单列为 `tilelang` 大类，子类写业务（如 `mhc_pre`）。

两个容易反的坑：

1. **别把 `_kernel` 后缀当 triton 判据**：torch 扩展的 kernel 也叫 `xxx_kernel`。
2. **`torch/custom_op` 的 `void-vllm::` / `vllm::` 兜底必须放在规则表最后**：
   否则 `void-vllm::silu_and_mul_clamp_flat_kernel`、`void-vllm::rms_norm_cached_kernel`
   会被先抓成 `torch/custom_op`，丢掉 `activation` / `norm` 的业务语义（实测踩过）。

## 7. 从 `other` 里挖新家族的标准动作

1. dump 一次 `other` 名单（按耗时排序）：

```python
import sys; sys.path.insert(0, "<skill>/scripts")
import tpa
from collections import Counter
cand = tpa.select_candidate(tpa.collect_candidates("<trace目录>"), 0, None)
td = tpa.parse_trace(cand)
agg = Counter()
for k in td.kernels:
    if tpa.classify_kernel(k)[0] == "other":
        agg[k.norm] += k.dur
for n, us in agg.most_common(30):
    print("%9.2f ms  %s" % (us / 1000, n))
```

2. 拿 kernel 名去源码里搜对应的 python 入口 / 打点 tag，确认属于哪个模块。
3. 选**唯一**子串写进 `CLASS_RULES`，并确保它排在会误吞它的宽泛规则之前。
4. 重跑对比：`other` 的下降量应≈新家族耗时，且其它大类数值不变。

示例：新增 vLLM 的 `merge_attn_states_kernel`

```python
("attention", "attn_merge", ("merge_attn_states",)),
```

（提示：`_compute_global_topk_indices_and_lens_kernel` 曾被 `sampling/topk` 吞掉——这就是
「宽泛关键字（`topk`）必须排在专有家族之后」的实例。）

## 8. 切换/新增厂商

- MetaX（mctlass / mcblas / mccl）：当前规则已覆盖。
- NVIDIA（cutlass / cublas / nccl / flash-attn 上游 kernel 名）：`cublas`/`cutlass`/`nccl`
  已在规则内，遇到未覆盖的名字按第 4 节补。
- 新增关键词时**只加子串**，不改匹配函数，避免破坏既有口径。
