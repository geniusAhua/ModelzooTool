# Skills（agent 技能）

本目录存放 agent 技能真身，随仓库一起评审、演进、复用。
遵循 VS Code Agent Skills 规范：一个技能 = 一个目录 + 必需的 `SKILL.md`。

## 目录约定

```
skills/<skill-name>/
├── SKILL.md          # 必需；name 必须与目录名一致
├── references/       # 按需加载的文档、模板（从 SKILL.md 一层可达）
├── scripts/          # 可选：可执行脚本
└── assets/           # 可选：模板、样板
```

## SKILL.md 规范（摘自官方 agent-customization）

- **frontmatter 必需字段**：`name`（小写 + 连字符，**与目录名一致**）、`description`
- **description 是唯一的发现入口**：写清「做什么 + 什么时候用」，埋入触发关键词；
  含冒号时用引号包裹
- **可选字段**：`argument-hint`（斜杠调用时的提示）、`user-invocable: false`（不显示为斜杠命令）、
  `disable-model-invocation: true`（不许模型自动加载）
- **正文 < 500 行**；超了就把细节拆进 `references/`，主文件只留流程 + 索引
- **资源引用一律相对路径**（`./references/xxx.md`），且**只引用一层**（references 之间可互链，
  不要再往下套两级）
- 正文建议顺序：做什么 → 什么时候用 → 步骤 → 产出 → 参考资源

## 安装（让 agent 能发现它）

技能真身放仓库里，每台机器在 agent 的全局技能目录放一个**相对软链**指过来：

```bash
REPO=$(git rev-parse --show-toplevel)     # 本仓库根目录
NAME=modelzoo-config-builder              # skills/ 下的技能目录名
DEST=~/.agents/skills                     # agent 读取全局技能的目录

mkdir -p "$DEST"
ln -sfn "../../$(realpath --relative-to="$HOME" "$REPO")/skills/$NAME" "$DEST/$NAME"
```

验证（能打印出 SKILL.md 的头部即成功）：

```bash
head -n 3 ~/.agents/skills/$NAME/SKILL.md
```

注意事项：

- **必须用相对路径**。同一份文件在不同平台看到的路径不同（Linux 侧 `/sw_home/<user>/...`，
  Windows 侧 `C:\Users\<user>\...`），绝对路径在另一端解析不了。
- `~/.agents/skills` 下若已有同名**目录**，`ln -s` 不会覆盖 —— 先 `rm -rf ~/.agents/skills/$NAME` 再建链接。
- **仓库目录改名会让软链悬空**（历史教训：`skill/` → `skills/`），改完立刻用
  `readlink -f ~/.agents/skills/$NAME` 复查。
- 新增技能不用改这里：放进 `skills/<name>/`，对每个技能重复上面两条命令即可。

## 卸载

```bash
rm -f ~/.agents/skills/<skill-name>
```

## 现有技能

| 技能 | 用途 |
|------|------|
| `modelzoo-config-builder` | 为 ModelzooTool 生成 `config.jsonc` 与执行脚本（含 NVIDIA / MetaX 双厂商） |
| `trace-analyzer` | 分析 torch.profiler trace（支持 zip/tar.gz 等压缩包，无需解压）：算子分类耗时（大类+子类，按 prefill/decode 拆分）、整体 GPU 耗时、阶段耗时、Markdown 报告 + Excel，含对比模式；**多 case 合并为一份报告/一份 Excel（表格带 case 列）**、多 rank 先弹框选 rank（默认 rank0） |
| `git-commit` | Git 提交规范（类型前缀、英文 msg、fix 写 root cause/solution、提交前审核） |
| `project-knowledge-base` | 项目知识库：接手任何项目前先读/生成 `.project-kb/PROJECT_KNOWLEDGE.md` |
