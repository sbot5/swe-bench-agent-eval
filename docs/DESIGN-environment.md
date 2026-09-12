# environment.py 设计档案

> 441 行（代码 157 + docstring 285）。本人逐行手写，Claude 只给判据、跑实测、审代码、补 docstring。
> 行为验收 22/22。写于 2026-09-08，`79ec241`。
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

## 四、决策清单（28 条）

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

### 容器生命周期（6 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 8 | 容器起在 `__enter__`，不在 `__init__` | 构造与资源获取分开 → 不存在半构造状态。**比 mini 好**：它在 `__init__` 起，代价是 cleanup 必须写 `getattr(self, "container_id", None)` 防御（`docker.py:155`） |
| 9 | `sleep 2h` 保活，不用 `tail -f /dev/null` | **泄漏的代价要有上界**。`--rm` 只在进程退出时触发，`tail -f` 永不退出 → 漏一个就 Up 到 Docker 重启 |
| 10 | `--name swebench-agent-<uuid8>` | 让 `docker rm -f $(docker ps -aq --filter name=swebench-agent-)` 这条命令能写出来 |
| 11 | 名字里**不带**实例 id | 四步判据第 4 条：`docker ps` 的 `{{.Image}}` 已经带着实例身份，同一事实两个来源删掉一个 |
| 12 | uuid 而非固定名 | 实测重名直接 `Conflict` 失败 → 一次泄漏会让后续全部起不来 |
| 13 | `docker run` 加 `timeout=120` | 镜像不在本地时 docker 会自动 pull，能拉几分钟 |

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

### execute（7 条）

| # | 决定 | 判据 |
| --- | --- | --- |
| 22 | 命令交给 `bash -c`，整条作为一个参数 | 六个工具需要 shell：`run_tests` 要 `cd && pytest`，`list_files` 要 `find \| head` |
| 23 | **这一层不做命令 allowlist / 路径白名单** | ① 容器即沙箱 ② allowlist 会制造「被自己工具挡住」的假失败，污染实验结论 ③ 模型给的是**参数**不是整条命令 → 引用参数的义务归工具层 |
| 24 | 显式 `-w /testbed` | 镜像自带 WORKDIR 但只在 2 个镜像上验过（共 500 个），依赖它是隐式契约。且实测 **`cd` 不跨 exec 持久** |
| 25 | `encoding="utf-8"` + `errors="replace"` | 实测不加 `errors` 碰到二进制输出直接 `UnicodeDecodeError`，一次解码失败炸掉整条实例 |
| 26 | `_safe_decode` 做成模块级独立函数 | 可单独测；execute 保持一个职责。同 `observation.py` 的 `_truncate` |
| 27 | `time.monotonic()` 不用 `time.time()` | 墙上时钟会被 NTP 校时调整，极端情况下 duration 算出负数 |
| 28 | 容器没起来抛 `RuntimeError`，**不用 `assert`** | 否决 mini 的 `assert self.container_id`（`docker.py:105`）—— `python -O` 会把 assert 整个编译掉。assert 是给内部不变量的，「忘了用 with」是调用方会犯的错 |

## 五、已纠正的错误

### 设计判断被实测推翻的（2 条）

| 原判断 | 实测 | 结论 |
| --- | --- | --- |
| 「`wc -l` 对末尾无换行的文件少算 1，写进已知边界」 | 文件 `'a\nb\nc'`：awk `NR` = **3**（对），`wc -l` = **2** | awk 版本没这个问题，**该边界作废** |
| 「别解析 stderr 文本，用 `exit_code` 分类」 | 「文件不存在」和「路径是目录」**退出码都是 2** | `exit_code` 不够用。改为**前置 `test` 守卫 + 自定义退出码（90+）**，仍然不解析文本 |

### 代码 bug，11 个

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

## 六、实测数据（全部 2026-09-08，astropy-12907 镜像）

| 事实 | 值 | 用在哪 |
| --- | --- | --- |
| `docker exec` 固定开销 | **≈ 32ms** | 1000 次调用 = 32 秒，可忽略 → 「要不要合并命令省调用」这问题不用再想 |
| `TimeoutExpired` 的 output/stdout/stderr | **全是 bytes**（即使传了 encoding）；零输出时是 `None` | `_safe_decode` 的三个分支 |
| 超时后容器内进程 | **还活着**（`sleep 987654` 仍在跑） | 已知边界 |
| `cd` 跨 `docker exec` | **不持久** | 显式 `-w`；且要告诉模型 |
| `docker rm -f <不存在的 id>` | **返回 0**（幂等） | `returncode != 0` 是无假警报的信号 |
| `sleep` 版本 | GNU coreutils 8.32，接受 `2h` | 决定 9 |
| 管道退出码 | `cat -n 不存在 \| sed` → **exit 0** | 工具层不用管道，或加 `set -o pipefail` |
| 不 `shlex.quote` 路径 | `a b;whoami.py` 中 `;` 后被当第二条命令执行 | 命令注入的活样本 |
| astropy 911 个 `.py` 行数 | p50=154 p75=425 p90=1003 p99=3019 max=4473 | `read_file` 默认 limit ≈ 200（与 `MAX_CONTENT_CHARS=10000` 自洽） |

## 七、已知边界与待办

- **超时后容器内进程存活**。不处理 —— 容器生命周期本身止损（`sleep 2h` + `rm -f`），且一个容器只服务一条实例。mini 也没处理。⚠️ 若 S4 发现某些实例越跑越慢，回来看这条
- **`container_timeout=2h` 与 `max_steps` 的跨文件约束**：`2h > max_steps × execute timeout + max_steps × LLM 延迟`。按 60s / 40 步 / 8s 估 ≈ 45 分钟，余量 2.6 倍。**`loop.py` 定 `max_steps` 时回来核对**
- **软链接逃逸**：`tools.py` 的路径检查用 Python 侧 `posixpath.normpath`（只防 `../`，0 次 execute）。容器里 `realpath` 能连软链接一起解析，但模型没有造软链接的动机，不值得为它多一次调用
- `ExecResult` 五个字段全是位置参数，`stdout`/`stderr` 相邻且同为 `str` —— 写反了类型检查器不吭声。只在 `execute()` 一处构造，暂不加 `*`

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
