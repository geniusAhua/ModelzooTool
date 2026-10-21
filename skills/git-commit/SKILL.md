---
name: git-commit
description: Git 提交规范。任何 git commit 前使用：msg 必须以 [refine/fix/doc/refactor/feature/test/chore/perf/build/ci] 之一开头；**msg 一律使用英文，不得出现中文（避免乱码）**；非 fix 只写一行摘要；fix 需空行后写 root cause 与 solution；一次 commit 只能有一种类型，混合必须拆成多次提交；提交前必须把 msg 交给用户审核，通过后才可提交；**所有提问（含 msg 审核）必须用 vscode_askQuestions 弹出可点击选项的对话框**，不要用纯文本提问；**对话框的标题、问题、选项一律用中文**（英文只用于 commit msg 本身）。
argument-hint: 一句话说明这次改了什么（用于生成待审 msg）
---

# Git 提交规范

适用于任何仓库的每一次 `git commit`。目标：让历史一眼能看出「做了什么类型的改动」，并且每次提交只做一件事。

## 1. 类型前缀

msg 开头必须是方括号包裹的类型，取最贴切的一个：

`[refine]` `[fix]` `[doc]` `[refactor]` `[feature]` `[test]` `[chore]` `[perf]` `[build]` `[ci]`

| 类型 | 用于 |
|------|------|
| `[feature]` | 新增功能/新脚本/新配置项 |
| `[fix]` | 修 bug、修错误行为 |
| `[refactor]` | 不改行为的结构调整/重命名/拆分 |
| `[refine]` | 小改进、补细节、调措辞 |
| `[doc]` | 只改文档/注释 |
| `[test]` | 只改测试 |
| `[chore]` | 杂项（依赖、忽略规则、脚手架） |
| `[perf]` | 性能优化 |
| `[build]` / `[ci]` | 构建脚本 / 流水线 |

## 2. msg 一律使用英文（只限 msg 本身）

- commit msg（含标题、正文、`root cause` / `solution` 内容）**只能使用英文**。
- 不得出现中文或全角标点，避免终端/终端编码不一致时出现乱码。
- 专有名词、路径、参数名照原样保留（如 `readyTag`、`--no-enable-prefix-caching`）。
- ⚠️ **本条只约束 msg**：向用户提问时的 `header`、`question`、`options.label`、
  `options.description`、`message` **一律用中文**（见 §7），不要把审核对话框也写成英文。

## 3. 非 fix 类型：只写一行

```
[refactor] Extract command building logic into CommandBuilder
[doc] Document the readyTag resolution order
```

- 只有标题一行，**不写正文**。
- 一行内说清「做了什么」，不写原因分析、不写改动清单。

## 4. fix 类型：标题 + 空行 + root cause + solution

```
[fix] Fix client not starting after server becomes ready

root cause: readyTag did not match the actual startup log printed by the image
solution: Override readyTag in that task section with the real startup line
```

- 标题写「修了什么」。
- 标题与正文之间**空一行**。
- 正文固定两行：`root cause:`（为什么出问题）、`solution:`（改了什么），各自一句话。
- 不要贴大段日志、不要写排查过程。

## 5. 一次 commit 只能有一种类型

- 同一次提交里出现两类改动（例如既修 bug 又加功能）→ **必须拆成两次提交**。
- 这通常说明之前的改动没有及时提交；拆分时按类型分组 `git add`（必要时用 `git add -p`），逐组提交。
- 拆完后各自按对应格式写 msg。

## 6. 提交前必须经用户审核

流程固定：

1. 先给出「拟提交的类型 + 完整 msg」，并说明本次包含哪些文件/改动（先 `git status` 看真实变更）。
   **msg 草稿要单独放在一个代码块里**，不要和审核对话框的字段混在一起。
2. **用 `vscode_askQuestions` 弹对话框审核**（见 §7），选项用中文，如：`同意并提交` / `改写 msg` / `先不提交`。
3. 用户确认后才执行 `git commit`。

未经审核不得自行提交；也不要在审核前先 commit 再补说明。

## 7. 有疑问先问，并给建议（必须用可点击对话框）

以下情况先提问，不要自行拍板：

- 类型拿不准（例如 `[refine]` 还是 `[fix]`）。
- 不确定是否该拆成多个 commit。
- msg 措辞有多种合理写法。

**提问方式（硬要求）**：调用 `vscode_askQuestions`，让用户在 VS Code 聊天里**点选**，不要用纯文本问。

| 要点 | 做法 |
|------|------|
| 给选项 | 每个问题带 2–4 个 `options`，不要只给开放式提问 |
| 标默认 | 推荐项加 `recommended: true`，用户一眼能选 |
| 一题一义 | 每个 question 只问一件事；一次 1–4 题，不要连续打断 |
| 多选 | 需要用户勾多项时设 `multiSelect: true` |
| 补充说明 | 用 `message`（markdown）放 msg 草稿、文件列表等上下文 |
| 语言 | `header` / `question` / `options.label` / `options.description` / `message` **一律中文**；只有 msg 草稿本身是英文 |
| 分块 | **msg 草稿单独成块**（`text` 代码块），对话框参数另起一块（`yaml`）；两者混在一段里看起来整段都像 msg |

### 示例（① 与 ② 是两样东西，只有 ① 会进 git）

**① 拟提交的 msg —— 唯一进 git 的内容，英文**

```text
[refactor] Move skills dir and rewrite modelzoo-config-builder rules
```

**② 审核对话框参数 —— 只用于在聊天里展示，不进 git，全部中文**

```yaml
header: 提交审核                 # 短标题，不是 msg 的一部分
question: 这条 commit message 可以提交吗？
message: |
  【拟提交的 msg】
  [refactor] Move skills dir and rewrite modelzoo-config-builder rules

  【涉及文件 / 改动】
  - skill/*（已删除）
  - skills/modelzoo-config-builder/*（新增）
options:
  - label: 同意并提交            # recommended: true
  - label: 改写 msg
  - label: 先不提交
```

> ⚠️ `message` 里的「【拟提交的 msg】」「【涉及文件 / 改动】」只是**给用户看的标注**，
> 不是 msg 的一部分。真正执行 `git commit -m` 时只取 ① 那一段；
> `header` / `question` / `options` 也永远不进 git。

若工具不可用或用户不回复，**暂停提交**并把 msg 贴出来等确认；不要自行 commit。

## 8. 提交前自检

- [ ] 开头有且只有一个类型前缀
- [ ] **msg 全部是英文，无中文/全角标点**
- [ ] **审核对话框的 header / 问题 / 选项 / 说明全是中文**（英文只出现在 msg 草稿里）
- [ ] **msg 草稿单独成块**，没有和对话框字段混在一起（别让人把整段当成 msg）
- [ ] 非 fix：只有一行；fix：空行 + `root cause` + `solution`
- [ ] 本次提交只包含一种类型
- [ ] msg 已由用户审核通过
