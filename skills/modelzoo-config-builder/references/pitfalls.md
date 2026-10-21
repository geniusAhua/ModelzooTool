# 常见坑

> 由 `SKILL.md` 按需加载。生成配置/脚本前建议先扫一遍。

## 6. 常见坑

- **⚠️ `useradd` 千万不要把 HOME 指到宿主目录**（宿主与容器共享同一块盘时最容易踩）：
  容器内的执行用户只用 `-m`（home 落在容器内 `/home/<user>`），**不要**用 `-d <宿主 HOME>`，
  `su` 时也**不要**再显式传 `HOME=`。理由：HOME 一旦指到共享盘里的宿主目录，容器内进程
  就会去读写宿主的 `~/.bashrc` / `~/.config/pip` / `~/.cache` / `~/.local`，后果：
  ① pip 配置、缓存、甚至 `pip install --user` 装出来的包会落到宿主目录（污染宿主环境）；
  ② 宿主 HOME 下若出现 `.local/lib/python3.X/site-packages`，它会插到 `sys.path` **最前面**，
  可能把镜像自带的 numpy / torch / vllm / sglang 顶掉（版本或 ABI 不匹配就 import 失败）。
  只对齐 **uid/gid**（保证产物属主正确）就够了 —— 正确写法见 [run_template.sh](./run_template.sh)：
  `useradd -m -l -u ${uid} -s /bin/bash ${user}`（`-m` 不指向任何宿主路径）。
- **⚠️ 切用户一律用 `su - <user>`（login shell），不要用 `su -s /bin/bash <user> -c "PATH='$PATH' …"`**
  （两平台统一）；属组统一 **`video` + `root`**（要再加别的组必须先问用户）；
  HOME 只对齐 uid/gid、**不迁移**（见上一条）。
  **为什么不再用非 login 写法**（实测，两个沐曦镜像）：`su -` 确实会重置 PATH，但**镜像自带的 conda
  配置在 `/etc/profile.d/`，login shell 会读** ⇒ `/opt/conda/bin` 仍在 PATH 里
  （`python3`/`pip3`/`vllm`/`sglang` 都能找到，`HOME=/home/<user>`）。
  真正会被清掉的是 **Docker ENV 里额外追加的目录**：MetaX 的 `/opt/maca/*`、`/opt/mxdriver/bin`，
  以及某些镜像的 `/opt/sglang/bin`、`/usr/local/cuda/bin` ⇒ **统一做法是：切用户后由一份 `USER_ENV`
  显式补回来**（MetaX 见 [vendors.md](./vendors.md) §7.2；NVIDIA 只需把「框架 CLI / python 所在目录」前置回 PATH）。模式见 [delivery.md](./delivery.md) §4.2。
  附带坑：`su - <user> -c ...` 是 login 但**非交互** —— `/etc/profile.d/*.sh` 会读，而
  `~/.bashrc` 在开头的 `case $- in *i*) ;; *) return;; esac` 处直接 return。所以「迁 HOME 换
  conda/ais_bench 可用」在自动化编排里**根本不成立**（只有手动交互登录才生效），别为了这个去动 HOME。
- **任务段缺 `type`** → 工具直接报「缺少 type 字段」，整个任务不执行。
- **字面量 `{}` 未转义** → 渲染期 `Missing` 报错。写成 `{{}}`。
- **保留名被 task_info 覆盖**：`input`/`output`/`bs`/`port` 等别和保留名冲突。
- **`type: e2e` 的 server 只启一次**：e2e 段里的 server `extra_args` 只在首个 case 生效，
  依赖 per-case 的 `{bs}{input}{output}` 的 server 参数不会逐 case 变化；需要逐 case
  独立 server 请用 `type: pair`。
- **非 vLLM 服务卡在等待就绪**：默认 `readyTag` 是 vLLM 的日志，其他服务匹配不到会
  一直等（工具**不设等待超时**，会一直挂住）。按该服务自身就绪日志在任务段配 `readyTag`
  —— ⚠️ **只能填单个字符串**，填数组会在加载配置时 `ValueError`。
- **⚠️ 必问清单没问全就动手**：先问**形态组**（client/server/框架 · host/container · user+uid · 易变参数），
  再问**口径组**（cudagraph / prefix cache / mem-fraction 或 gpu-util / `readyTag` / `--ignore-eos` /
  环境变量复核 / 命令参数复核）—— 漏问任何一项都可能让整轮 8 卡任务白跑或白写一个脚本。
  见 [heuristics.md](./heuristics.md)「⚠️ 必问清单」。
- **抓 triton 忘开清缓存**：想要旧 `TritonDump` 的效果，任务段加
  `"cleanTritonCache": true`。
- **client 固定命令 vs 覆盖命令**：只想改参数就用 `extra_args`，想换整条命令才写 `cmd`。
- **`$((...))` 不要被 JSON 转义破坏**：保持原样写进字符串即可。
- **容器内脚本用 `su - <user> -c "<命令字符串>"` 传递**（不再用 heredoc），所以字符串里的 `$` 要
  注意转义层级：让它在**切用户后才展开**就写 `\$PATH`；想在**当前 shell 就展开**就直接写 `${VAR}`。
  `USER_ENV` 里的 `${MACA_PATH}` / `$PATH` 属于前者（延迟展开）—— 写错了会得到一堆空值而不是报错。
- **config 文件名即 `{__FILE_NAME__}`**：会给日志目录带来一层以文件名命名的子目录，
  命名时保持可读。
- **client 若调用 AISBench（mmengine 系工具），别在它的配置文件里 `import os` 后用环境变量**：
  `mmengine.Config.fromfile()` 默认 `use_lazy_import=True`，配置里的 `import xxx` 会被换成
  LazyObject/LazyAttr，任何**调用**（`os.environ.get(...)`）都直接 `RuntimeError`，工具侧再包成
  `TMAN-CFG-001 invaild syntax in config content`。可用 `_os = __import__("os")`（内建函数、
  不是 import 语句，不会被 lazy 化）后再 `_os.environ.get(...)`。

- **⚠️ 生成的脚本必须区分厂商（NVIDIA / MetaX）**：只写 NVIDIA 的 `--gpus all` 在沐曦机器上起不来
  （设备节点、补组、环境变量、镜像来源全都不同），反之亦然。对照表、MetaX 默认环境变量与常见坑见 [vendors.md](./vendors.md)。
- **外部评测工具（AISBench 等）的环境变量放它自己的 `xxx_env.sh`，不要写进 jsonc 的 `client.env`**：
  实测这类「客户端环境」（`AIS_BENCH_BIN` / `AIS_BENCH_ROOT` / 数据缓存目录等）在 NVIDIA 与 MetaX
  机器上**完全一样**，写进 jsonc 只会把机器路径混进两家共用的配置、还要同步两处。
  推荐：机器相关的值集中在 `accuracy/aisbench_env.sh` 这类环境文件里，运行脚本发现变量为空时 source 它
  （`XXX_ENV_FILE` 可覆盖路径、置空可禁用），jsonc 里写 `"env": {}`。
  换言之 `client.env` 只留给**真正随配置变**的东西（例如只有某任务才需要的开关）；
  平台/模型相关的性能开关则相反（见 [vendors.md](./vendors.md) §7.4）。

**脚本形态 / 复杂度相关的坑（详见 [gate.md](./gate.md)）**：

- **没问平台 / host-container / 镜像就开始写** → 先问 A0 平台，再问 A2 跑在哪（host 还要问镜像）：容器内只需 1 个脚本，宿主机必须 2 个、分两步（① 起容器 + ② 容器内）。
  这条**不分厂商**（NVIDIA / MetaX 同一规则）；合并成一个"全能脚本"后就无法在「只有容器可用」时复用，直接返工。
- **在 client / server 脚本里写 `useradd` / `su` / uid 判断** → 职责越界；执行用户只由**框架脚本**负责，且必须问用户。
- **把环境变量塞进 `cmd`（`FOO=1 bash xxx.sh`）** → 与 config 的 `env` 重复、任务级覆盖关系看不清；
  固定变量一律写 `env`，易变值（端口/并发/条数/fewshot/输出目录）做成脚本参数或顶部变量。
- **给 client/server 脚本堆功能**（结果汇总、重试、轮询、参数解析器）→ 偏离"只负责拉那条命令"的定位；
  用户明确要才加。
- **为了"验证"去装依赖 / 起容器 / 真跑任务** → 用户只要求模板时不要现场验证；
  潜在问题先问用户并给建议（[gate.md](./gate.md) §0-F）。
