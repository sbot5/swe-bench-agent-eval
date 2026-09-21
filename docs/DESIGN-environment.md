# environment.py 设计档案

> 初版 441 行（代码 157 + docstring 285）。本人逐行手写，Claude 只给判据、跑实测、审代码、补 docstring。
> 行为验收 22/22（§六末）。写于 2026-09-08，`79ec241`。
>
> **2026-09-15 起代码里的 docstring 只写契约**（同 `DESIGN-tools.md` 的约定）：原先内嵌的决定、实测、纠错全部外移到本文 ——
> 表格装不下的展开写在 §四末「逐个对象的展开」。引用写函数名，不写行号。
>
> 配套：[`DESIGN-observation.md`](DESIGN-observation.md)（上一个模块）

## 一、它在系统里的位置

```
run.py           取实例 → 建 environment → 跑 loop → 收 patch
   │
loop.py          ReAct：拼 prompt → 调模型 → 解析动作 → 派给工具
   │                                    ↑ 把 Observation.render() 塞回上下文
tools.py         六个工具：拼命令 → 交给 environment → 把结果翻译成 Observation
   │
environment.py   ◀── 本模块
   │
Docker 容器       /testbed，仓库停在 base_commit
```

**这一层存在的理由不是「复用 docker exec 那几行」。**

是因为它上面三层可以全部是纯函数 —— 给定输入必然给定输出，可以离线测。
`environment.py` 是**唯一碰真实世界的地方**（子进程、会超时的东西、文件系统）。
把不确定性关进一个盒子，盒子外面才测得动。

**为什么 Agent 代码不跑在容器里**：容器里的 Python 是 3.6.13（配合被测仓库的年代），宿主机 venv 是 3.12。
所以每条实例一个容器，工具通过 `docker exec` 在里面执行。mini-SWE-agent 也是这么做的。

## 二、为什么第二个写它

`observation.py` 定了「工具怎么说话」，这一层定「工具怎么做事」。
六个工具全部依赖它 —— 它错一点，六个一起错。先写它，六个工具才能真跑。

## 三、两个类，三个职责

| | 谁产出 | 给谁看 | 有没有 render |
| --- | --- | --- | --- |
| `ExecResult` | environment | **工具层的代码** | 没有，模型永远看不到 |
| `Observation` | tools | **模型** | 有 |

`DockerEnvironment` 的三个职责，各对应一个方法：

- `_start_container()` —— 起容器（`__enter__` 调）
- `execute()` —— 跑一条命令，返回 `ExecResult`
- `cleanup()` —— 销毁容器（`__exit__` 调）

## 四、决策清单（33 条；29–31 是 09-15 外移 docstring 时补录的，原先只写在代码里；32 是 09-21 加的 `execute_to_file`）

### ExecResult（7 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 1 | 自建 dataclass，不用 `subprocess.CompletedProcess` | 实测 `hasattr(r, "timed_out")` 是 `False` —— 它**表达不了超时**，只能塞 `returncode=-1`，于是超时和「docker 自己挂了」变成同一个值。而归因表里 `TIMEOUT` 和 `IO_ERROR` 是两行 |
| 2 | stdout / stderr **分开存** | **不可逆性**：分开之后想合随时能合，合并了就再也分不开。mini 合并（`stderr=STDOUT`），本项目在这里与它不同 |
| 3 | 超时用 `timed_out: bool` 字段 | 否决哨兵退出码（一个字段两种含义）；否决抛异常（六个工具各写一遍 try/except，漏一个就是 loop 崩） |
| 4 | 超时时 `exit_code = None` | 命令根本没退出，没有退出码。约定写死在 docstring |
| 5 | 要 `duration` | loop 层记的是整个 step（含 LLM 几秒），粒度答不了「`run_tests` 平均跑多久」。调超时阈值需要真实分布 |
| 6 | `frozen=True` | 子进程结束那一刻的快照，改它没有物理含义。全字段是标量，没有「frozen 挡不住 list.append」那个洞 |
| 7 | `__post_init__` 强制两条互斥契约 | 不强制的话 `timed_out=False` + `exit_code=None` 能构造出来 → 工具层 `if exit_code != 0` 把超时误判成命令失败 → **归因表串行且不报错** |

### 容器生命周期（7 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 8 | 容器起在 `__enter__`，不在 `__init__` | 构造与资源获取分开 → 不存在半构造状态。**比 mini 好**：它在 `__init__` 起，代价是 cleanup 必须写 `getattr(self, "container_id", None)` 防御（`docker.py:155`） |
| 9 | `sleep 2h` 保活，不用 `tail -f /dev/null` | **泄漏的代价要有上界**。`--rm` 只在进程退出时触发，`tail -f` 永不退出 → 漏一个就 Up 到 Docker 重启 |
| 10 | `--name swebench-agent-<uuid8>` | 让 `docker rm -f $(docker ps -aq --filter name=swebench-agent-)` 这条命令能写出来 |
| 11 | 名字里**不带**实例 id | 四步判据第 4 条：`docker ps` 的 `{{.Image}}` 已经带着实例身份，同一事实两个来源删掉一个 |
| 12 | uuid 而非固定名 | 实测重名直接 `Conflict` 失败 → 一次泄漏会让后续全部起不来 |
| 13 | `docker run` 加 `timeout=120` | 镜像不在本地时 docker 会自动 pull，能拉几分钟 |
| 30 | `2h` 写死在 `_start_container`，不做成构造参数 | 只有 `run.py` 一个调用点，没有第二个取值的需求；真出现了再提参数 |
| 32 | **`docker run` 加 `--network=none`**（09-18，为 P2 的 `run_python` 加） | `run_python` 让模型能执行任意 Python，`import socket` 在**语言层拦不住**（monkeypatch 会被 `importlib.reload` 绕开，`os.system('curl …')` 根本不过 socket 模块）—— 沙箱边界只能由容器给。不加的话就是 P1 抓到的那条路：下载上游 PR 的 `.patch` 再 `git apply`（`docs/EVAL-S5-baseline-nonet.md`）。**负对照实测**：同镜像默认网络打 github.com 得 `REACHED THE NETWORK`，加了之后 `gaierror [Errno -3]` —— 顺带证明此前我方容器**一直联得上外网**（当时无害，因为六个工具没一个能发请求，但那是运气不是设计）。loopback 不受影响，要起本地端口的测试照常跑（真容器验过）；断网后 6 个仓库各抽 1 条测试仍通过（`scripts/p2_nonet_run_tests_probe.py`），两条 FAIL 已用有网/无网对拍排除网络因素 |

### 错误处理（8 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 14 | `CalledProcessError` 包装成 `RuntimeError`，拼进 `e.stderr` | `str(e)` 只有 "returned non-zero exit status 125"，真正的原因（"Unable to find image"）只在 `e.stderr` 里 |
| 15 | `raise ... from e` | 不写 → traceback 说 "another exception occurred"（像你的错误处理有 bug）；写了 → "direct cause"（事实） |
| 16 | `FileNotFoundError` / `TimeoutExpired` **不包装** | 它们的默认信息已经说清楚了，且属于环境问题而非实例问题 |
| 17 | try 块只包 `subprocess.run` 一个调用 | try 越小，except 捕到的越确定。大 try 块会把不相干的 bug 一起吞掉 |
| 18 | cleanup 失败**只打警告，不抛异常** | `__exit__` 里抛新异常会让 traceback 最后一行变成清理错误，**盖住真正的失败原因**。原则：清理代码不该盖过它正在清理的那个失败 |
| 19 | 警告里带 `container_id` + `Action required: docker rm -f <id>` | 和给模型写 `next_actions` 同构：根因 + 恢复指令 |
| 20 | cleanup `timeout=30` 阻塞等待 | 否决 mini 的后台化（`docker.py:156` 的 `timeout 60 … &` + `Popen`）——它永不阻塞但**永远不知道清理有没有成功**。25 条 × 最坏 30 秒 = 12.5 分钟，换「知道有没有泄漏」 |
| 21 | 捕获收窄到 `SubprocessError` | `TimeoutExpired` 和 `CalledProcessError` 的共同父类。顺带保证 `KeyboardInterrupt` / `SystemExit` 能穿过去（实测：它们不是 `Exception` 的子类） |
| 31 | `docker run` 退出码 0 但 stdout 为空 → `RuntimeError` | 防「成功了却没拿到 id」的静默失败；否则 `container_id` 是 `""`，后面 `execute()` 的 `if not self.container_id` 会把它当成「忘了用 with」，根因指错 |

### execute（7 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 22 | 命令交给 `bash -c`，整条作为一个参数 | 六个工具需要 shell：`run_tests` 要 `cd && pytest`，`list_files` 要 `find \| head` |
| 23 | **这一层不做命令 allowlist / 路径白名单** | ① 容器即沙箱 ② allowlist 会制造「被自己工具挡住」的假失败，污染实验结论 ③ 模型给的是**参数**不是整条命令 → 引用参数的义务归工具层 |
| 24 | 显式 `-w /testbed` | 镜像自带 WORKDIR 但只在 2 个镜像上验过（共 500 个），依赖它是隐式契约。且实测 **`cd` 不跨 exec 持久** |
| 25 | `encoding="utf-8"` + `errors="replace"` | 容器输出不保证是合法 UTF-8（grep 命中二进制文件、`.pyc`、latin-1 测试固件）。实测不加 `errors` 直接 `UnicodeDecodeError`，一次解码失败炸掉整条实例，而它和要研究的东西毫无关系。同 mini `docker.py:120-121` |
| 26 | `_safe_decode` 做成模块级独立函数 | 可单独测；execute 保持一个职责。同 `observation.py` 的 `_truncate` |
| 27 | `time.monotonic()` 不用 `time.time()` | 墙上时钟会被 NTP 校时调整，极端情况下 duration 算出负数 |
| 28 | 容器没起来抛 `RuntimeError`，**不用 `assert`** | 否决 mini 的 `assert self.container_id`（`docker.py:105`）—— `python -O` 会把 assert 整个编译掉。assert 是给内部不变量的，「忘了用 with」是调用方会犯的错。和 `ExecResult.__post_init__` 用 `ValueError` 是同一个判断 |
| 29 | `execute(timeout=60)` | 与 mini 的 `swebench.yaml` 一致 —— **控制变量**：这不是本项目的实验变量，不要动（同 `DESIGN-observation.md` 决定 22） |

### execute_to_file（1 条，2026-09-21 加）

| # | 决定 | 判据 |
| --- | --- | --- |
| 32 | 大输出的命令走 `execute_to_file`：容器里自己重定向进文件，宿主机只 `tail -c` 取预算内的尾部；`execute()` 一行不动 | `execute()` 是 `capture_output=True`，整份 stdout 先进宿主机内存（P1 实测 mini 单条 trajectory 到 204MB）；`_keep_tail` 是**截断之后**才做的，那一份早就在内存里了。**09-21 实测**：50MB 输出走新路径，宿主机峰值 **+0.0 MB**。溢写文件放 `/tmp/agent-overflow`（**不**放 `/testbed`，理由同 Y9：`git_diff` 会把它列成未跟踪文件）。代价是 `read_file` 的路径白名单要开一个窄口子，见 `DESIGN-tools.md` Y12 |

⚠️ **这一条只改了 `run_python` 那条路。** `run_tests` 仍走 `execute()`；`read_file` 读一个超长单行文件时宿主机峰值同样会爆（09-21 实测 50MB 单行 **+190.9 MB**）。「输出不进宿主机内存」目前**不是**这一层的普遍保证，只是 `run_python` 的保证 —— 见「已知边界」。

### 逐个对象的展开（2026-09-15 从 docstring 外移）

**`DockerEnvironment`**

- 决定 8 的代价：多一层 `with`，调用方不能拿一个「已经可用」的对象到处传。对本项目无所谓 —— 只有 `run.py` 一个调用点，
  且它本来就是一条实例一个作用域
- `container_id` 的生命周期：`__init__` → `None`；`__enter__` → 64 位十六进制 id；`cleanup` 删完后在 `finally` 里**无条件复位回 `None`**。
  复位是为了让 cleanup 幂等 —— `__exit__` 调一次，将来若加 `__del__` 再调一次，第二次直接从头部返回，不会去删一个已经不存在的 id

**`_start_container()` 的失败路径**

| 情况 | 结局 | 理由 |
| --- | --- | --- |
| 镜像不存在 / docker 拒绝 | `RuntimeError`，带镜像名、退出码、`e.stderr` | 决定 14、15 |
| docker 没装 | `FileNotFoundError` 原样抛 | 决定 16 |
| 拉镜像超过 120 秒 | `TimeoutExpired` 原样抛 | 决定 13、16 |
| 退出码 0 但 id 为空 | `RuntimeError` | 决定 31 |

**`cleanup()`** —— `check=False` 时命令失败**不抛异常**，只体现在 `returncode` 上（09-08 实测）。所以两条路都要走：
查 `returncode`（命令失败）+ `except SubprocessError`（进程异常，如超时）。只做其中一条就是聋的。
配合 §六「`docker rm -f` 幂等」：`returncode != 0` 是没有假警报的信号

**`execute()`**

- 本层只有两种结局：跑完了（`timed_out=False`）和被超时打断了（`timed_out=True`）。非 0 退出码是正常返回值（`check=False`）——
  命令失败是模型要看的信息，不是本层要处理的错误
- 它是六个工具的唯一出口，它错一点，六个一起错
- 超时分支必须自己 decode：`TimeoutExpired` 上没有 `returncode`（§六），所以 `exit_code` 只能是 `None` —— 这就是 `ExecResult`
  「超时则 `exit_code is None`」那条契约的由来

**`_safe_decode()`** —— 把 `None` / `bytes` / `str` 统一成 str

| 形态 | 处理 | 什么时候出现 |
| --- | --- | --- |
| `None` | `""` | 超时前命令一个字都没输出（不是 `b""`） |
| `bytes` | UTF-8 decode，`errors="replace"`（理由同决定 25） | `TimeoutExpired` 的正常形态 |
| `str` | 原样 | `CompletedProcess` 的正常形态 —— 目前不走这条，留着以后能直接复用 |

不 decode 直接拼进 f-string，模型看到的是 `b'\xe5\x87...'` 这种十六进制 —— **一次超时的观察，正是模型最需要读懂的时候**。

## 五、已纠正的错误

### 设计判断被实测推翻的（2 条）

| 原判断 | 实测 | 结论 |
| --- | --- | --- |
| 「`wc -l` 对末尾无换行的文件少算 1，写进已知边界」 | 文件 `'a\nb\nc'`：awk `NR` = **3**（对），`wc -l` = **2** | awk 版本没这个问题，**该边界作废** |
| 「别解析 stderr 文本，用 `exit_code` 分类」 | 「文件不存在」和「路径是目录」**退出码都是 2** | `exit_code` 不够用。改为**前置 `test` 守卫 + 自定义退出码（90+）**，仍然不解析文本 |

### 代码 bug，12 个（09-15 更正：原标题写成 11 个，下面实际编号到 12）

**语法错（3 次，全是同一个手势）**

1. `self.container_id = str | None = None` —— 标注用冒号不用等号；Python 读成链式赋值，`str | None` 不能当赋值目标
2. `timeout=120` 后少逗号
3. `timeout=30` 后少逗号

> ⚠️ **linter 遇到语法错就停止分析。** 「ruff 只报了 1 条」其实是「它只能看到这么多」。
> 对策：保存后先跑 `python -c "import ast; ast.parse(open(...).read())"`，或让 VS Code 的 Problems 面板常驻。

**不报错只是全错（8 个）**

4. `def _start_container():` 少 `self` → F821 × 3
5. `ExecResult.timed_out` 用类名访问 —— 实测不对称：**没有默认值**的字段访问 → `AttributeError`（响的）；**有默认值**的字段 → 静静返回默认值（哑的）。规律：`__post_init__` 里读字段一律 `self.`
6. `exit_code` 裸写（应 `self.exit_code`）→ NameError
7. `if exit_code is not int:` —— **恒真**。实测 `5 / 0 / None / True` 全部 `is not int → True`。第三次踩 `is` 这一类（前两次：`or` 取值、`is []`）
8. `subprocess.run(...)` 不接返回值却用 `result.returncode` —— **和 `observation.py` 的 `_truncate` 同一类**。区别：那次 ruff 抓不到（裸调用合法），这次抓到了，纯粹因为后面用了未定义名
9. `sys` 没 import
10. `capture_output=True` 忘了 `text=True` → `result.stderr` 是 bytes，警告信息打成 `b'\xe7\x9c\x9f...'` ——**出事时唯一的线索变成十六进制**
11. `instance()` 写成了 `isinstance()` 的漏字版 —— 只在超时且 output 是 bytes 时触发，happy path 测一百遍发现不了

**🔴 最严重的那个（单列）**

12. `subprocess.run(cmd, ...)` 传的是**命令字符串**，而不是拼好的 `exec_cmd` 列表。

实测后果：

```
pwd                 → exit=0, stdout='/home/zixu/swe-bench-eval\n'   ← 跑在【宿主机】上
ls /testbed         → FileNotFoundError
ls /testbed | head  → FileNotFoundError
```

`shell=False` 时字符串被当成**可执行文件路径**。单个词的命令恰好能在宿主机 PATH 上找到
→ 退出码 0、有输出、看起来完全正常，但**容器从头到尾没参与**。

若这样跑起 Agent：模型读到的是笔记本的文件系统，`git diff` 提取的是自己仓库的改动。
25 条全 0 分，而归因表会说「模型定位不到文件」。

**ruff 只报一条 `F841 Local variable 'exec_cmd' is assigned but never used`。**

### 教训（4 条）

1. **`F841` 几乎从不是清理建议。** 变量赋了值没人用 = 你用了别的东西。这条比大多数 lint 规则更值得停下来看
2. **lint 干净 ≠ 逻辑对。** 第 12 条 ruff 只给一条看似无关痛痒的提示，靠**行为验收测试**才抓出来
3. **别 grep ruff 的输出。** 语法错打印成小写的 `invalid-syntax:`，`grep '^[A-Z]'` 会把它全滤掉，看起来像「干净」
4. **命名太像会助推 bug。** 参数 `cmd: str` 和局部 `exec_cmd: list` 只差一个前缀，而同一文件里另外两个方法的 `cmd` 都是列表 —— 同名不同类型本身就是陷阱

## 六、实测数据（除注明外全部 2026-09-08，astropy-12907 镜像）

### 容器事实（2026-09-06 实测 `sweb.eval.x86_64.django_1776_django-11138`，09-08 于 astropy-12907 复核）

| 事实 | 值 | 用在哪 |
| --- | --- | --- |
| 工作目录 | `/testbed`，仓库停在 `base_commit`，工作区干净；镜像自带 `WORKDIR /testbed` | 决定 24 仍显式传 `-w` |
| 没有 `rg` | 用 `git grep`（只搜跟踪文件，自动跳过 `.git` 和构建产物） | `search_code` |
| 有 | `grep` `find` `git` `sed` `awk` `patch` `python`（3.6.13） | 六个工具拼命令 |
| 评分测试 | **不在容器里** —— `test_patch` 是评测时才应用的，Agent 看不到。已实测确认，评测没有被污染 | — |
| 镜像名规律 | `swebench/sweb.eval.x86_64.<repo>_1776_<instance 后半段>`；实际的用 `docker images \| grep sweb` 看 | `run.py` |
| 残留容器 | `docker rm -f $(docker ps -aq --filter name=swebench-agent-)` | 决定 10 |

### 执行层

| 事实 | 值 | 用在哪 |
| --- | --- | --- |
| `sleep 4` + `--rm` | 到期后容器自动消失；同镜像 `tail -f /dev/null` 起的容器 3 秒后仍是 Up | 决定 9 |
| `bash -c` | `ls /testbed \| head -3`、`echo A && echo B`、`cd /testbed && git rev-parse --short HEAD` 三条都正常 | 决定 22 |
| 非 UTF-8 输出 | `printf '\xff\xfe\x00hello'`：不加 `errors` → `UnicodeDecodeError`；加了 → `'��\x00hello'` | 决定 25 |
| 超时时的部分输出 | 容器内 `echo 出来一半; sleep 30` 配 `timeout=2`：`type(e.output)` 是 bytes，值 `b'\xe5\x87\xba\xe6\x9d\xa5\xe4\xb8\x80\xe5\x8d\x8a\n'` | `_safe_decode` |
| `check=False` 的失败 | 不抛异常，只体现在 `returncode` | `cleanup` 两条路都查 |
| `docker exec` 固定开销 | **≈ 32ms** | 1000 次调用 = 32 秒，可忽略 → 「要不要合并命令省调用」这问题不用再想 |
| `TimeoutExpired` 的 output/stdout/stderr | **全是 bytes**（即使传了 encoding）；零输出时是 `None` | `_safe_decode` 的三个分支 |
| 超时后容器内进程 | **还活着**（`sleep 987654` 仍在跑） | 已知边界 |
| `cd` 跨 `docker exec` | **不持久** | 显式 `-w`；且要告诉模型 |
| `docker rm -f <不存在的 id>` | **返回 0**（幂等） | `returncode != 0` 是无假警报的信号 |
| `sleep` 版本 | GNU coreutils 8.32，接受 `2h` | 决定 9 |
| 管道退出码 | `cat -n 不存在 \| sed` → **exit 0** | 工具层不用管道，或加 `set -o pipefail` |
| 不 `shlex.quote` 路径 | `a b;whoami.py` 中 `;` 后被当第二条命令执行 | 命令注入的活样本 |
| astropy 911 个 `.py` 行数 | p50=154 p75=425 p90=1003 p99=3019 max=4473 | `read_file` 默认 limit ≈ 200（与 `MAX_CONTENT_CHARS=10000` 自洽） |
| **行为验收**（22/22） | 起容器 → exec → 销毁；with 内抛异常时容器仍被清掉；`execute("pwd")` 返回 `/testbed` 而不是宿主机路径；管道 / `&&` 可用；非 0 退出码原样返回；超时返回可读文本且 `exit_code=None` | 本模块验收 |

⚠️ 验收脚本当时写在 `scratchpad/test_execute.py`，**没进仓库，现已不存在**（09-15 查：`git ls-files` 无、目录不在）——
与 `DESIGN-tools.md` §七「验收脚本没进仓库」是同一个问题，定 `tests/` 取舍时一起处理。

## 七、已知边界与待办

- **超时后容器内进程存活**。不处理 —— 容器生命周期本身止损（`sleep 2h` + `rm -f`），且一个容器只服务一条实例。mini 也没处理。⚠️ 若 S4 发现某些实例越跑越慢，回来看这条
- **`container_timeout=2h` 与 `max_steps` 的跨文件约束**：`2h > max_steps × execute timeout + max_steps × LLM 延迟`。按 60s / 40 步 / 8s 估 ≈ 45 分钟，余量 2.6 倍。**`loop.py` 定 `max_steps` 时回来核对**
- **软链接逃逸**：`tools.py` 的路径检查用 Python 侧 `posixpath.normpath`（只防 `../`，0 次 execute）。容器里 `realpath` 能连软链接一起解析，但模型没有造软链接的动机，不值得为它多一次调用
- `ExecResult` 五个字段全是位置参数，`stdout`/`stderr` 相邻且同为 `str` —— 写反了类型检查器不吭声。只在 `execute()` 一处构造，暂不加 `*`
- ⚠️ **「输出不进宿主机内存」只覆盖了 `run_python`（2026-09-21）**。决定 32 修的是产出大输出的那一侧，另外两个部位仍在：
  - `read_file` 读**超长单行**文件时，`awk` 把整行吐给 `execute()` —— 09-21 实测读那份 50MB 单行日志，宿主机峰值 **+190.9 MB**（同一次验收里 `run_python` 只 +0.0 MB）。它有行数和字符预算，但预算是在**输出已经回到宿主机之后**才生效的，和 `_keep_tail` 当初那个坑一模一样
  - `run_tests` 仍走 `execute()`。它的输出受测试套件规模约束，不是任意大，所以排在后面
  → 所以**不要**把「决定 32」读成「这一层现在不会爆内存了」。它现在的保证是：**模型主动 print 出来的东西**不会爆。

### 压在 tools.py 上的四条义务（机器强制不了）

| 来源 | 义务 | 不做的后果 |
| --- | --- | --- |
| `observation.py` | 每条错误路径要有**停止条件** | 模型在同一个错误上原地打转 |
| 决定 23 | 拼参数用 **`shlex.quote()`** | 命令注入 → 归因污染 |
| 决定 24 | 告诉模型 **`cd` 不持久** | 模型以为切了目录，后续全错 |
| 实测（管道） | 不用管道，或 `set -o pipefail` | `exit_code` 失效，失败走进 happy path |

后三条不做的后果**都是归因污染而不是崩溃** —— 实例会失败，而表会说「模型能力不足」。

## 八、这个模块想证明什么

1. **能把不确定性隔离在一层里。** 上面三层因此可以离线测 —— 这是「你为什么这样分层」的实答案
2. **知道资源管理该怎么做。** `with` 协议、幂等 cleanup、泄漏有上界、清理不盖过原始失败 —— 四条都有明确理由和被否决的替代方案
3. **知道 subprocess 的坑在哪。** argv vs 字符串、超时异常上的 bytes、管道吞退出码、`text=True` 不覆盖异常属性 —— 全部实测过，不是背的
4. **每条与 mini 不同的地方都说得出理由。** 分开存 stderr、`sleep` 保活、阻塞式 cleanup、不用 assert —— 四处不同，四个判据
