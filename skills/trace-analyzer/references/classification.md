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
| 1 | moe | gemm | `void-mctlass::kernel-moe`, `macagemmmoe`, `fused_moe_kernel`, `moe_gemm` |
| 2 | moe | align_block | `moe_align_block` |
| 3 | moe | sort_tokens | `count_and_sort_expert_tokens` |
| 4 | moe | topk | `single_group_topk`, `moe_topk` |
| 5 | moe | sum | `_moe_sum`, `moe_sum`, `moe_finalize` |
| 6 | moe | other | `moe` |
| 7-11 | communication | all_reduce / all_gather / all_to_all / send_recv / other | `allreduce`, `allgather`, `alltoall`, `broadcast`, `mccl` |
| 12-15 | gemm | gemv / mctlass / mcblas / cublas | `gemv`, `mctlass`, `mcblas`, `cublas` |
| 16-20 | attention | kv_cache / attn_merge / mla / flash_attn / paged_attn | `concat_and_cache`, `merge_attn_states`, `_mla_`, `flash_fwd`, `paged_attention` |
| 21-22 | norm | rms_norm / layer_norm | `rmsnorm`, `layernorm` |
| 23-25 | activation | silu_and_mul / gelu / other | `silu_and_mul`, `gelu`, `silu` |
| 26-29 | elementwise | copy / add / fill / other | `direct_copy`, `functor_add`, `fillfunctor`, `elementwise` |
| 30-31 | sampling | topk / other | `mbtopk`, `bitonicsort`, `topk` |
| 32 | triton | triton | `triton` |
| 33 | softmax | softmax | `softmax` |
| 兜底 | other | other | — |

**为什么 moe 排在最前**：`void mctlass::Kernel-moe` 本质是 MoE 的 GEMM，放在 `moe/gemm`
可以让「MoE 总开销」一眼可见；子类仍然标明它是 GEMM。若你更希望把它算进 `gemm` 大类，
把第 1 条改成 `("gemm", "mctlass_moe", (...))` 即可。

**为什么 communication 排在 gemm 前**：`mcclKernel_AllReduce_*` 名字里可能带 dtype 等字段，
先锁定通信更稳。

## 4. 怎么加规则

1. 跑一次 `analyze`，看报告第 5 节「单算子耗时」和 Excel 的 `Kernels` sheet 有没有落到 `other`。
2. 从规范化名里挑一个**稳定且唯一**的子串（不要用会跨家族出现的词）。
3. 插到 `CLASS_RULES` 合适位置（越具体越靠前）。
4. 重跑，确认 `other` 占比下降且没有误吞别的家族。

示例：新增 vLLM 的 `merge_attn_states_kernel`

```python
("attention", "attn_merge", ("merge_attn_states",)),
```

## 5. 切换/新增厂商

- MetaX（mctlass / mcblas / mccl）：当前规则已覆盖。
- NVIDIA（cutlass / cublas / nccl / flash-attn 上游 kernel 名）：`cublas`/`cutlass`/`nccl`
  已在规则内，遇到未覆盖的名字按第 4 节补。
- 新增关键词时**只加子串**，不改匹配函数，避免破坏既有口径。
