# tools.py 设计档案

> **✅ 6/6 完成（2026-09-16）**。`read_file` ✅ 09-15（7 步，astropy 容器验收 16/16，§六）；`list_files` ✅ 09-15（21/21）；
> `search_code` ✅ 09-15（**Claude 写**，51/51）；`apply_patch` `run_tests` `git_diff` ✅ 09-16（**Claude 写**，§四）。
> 09-15 之前判断逻辑本人手写，Claude 给思路、跑实测、审代码；
> **09-16 本人要求「全部做完，明天统一学习整个项目」，此后的代码全部由 Claude 写、本人事后审**。面试口径按这条说。
>
> 验收现在是可执行的：`.venv/bin/python -m pytest tests/ -q`（75 条，假 env，0.8 秒）
> 加 `-m slow`（8 条，真容器，3.3 秒）。DESIGN §二 的四条验收各有对应测试，见 `tests/test_tools.py`。
>
> 配套：[`DESIGN-observation.md`](DESIGN-observation.md)（工具怎么说话）· [`DESIGN-environment.md`](DESIGN-environment.md)（工具怎么做事；其 §七 的四条义务压在本模块）
>
> 代码里的 docstring 只写契约；决定、实测、纠错都在这里。引用写函数名，不写行号 —— 行号会随代码漂移。

## 一、六个工具与写的顺序

```
read_file -> list_files -> search_code -> apply_patch -> run_tests -> git_diff
```

先用 `read_file` 把「宿主机 -> docker exec -> 观察」这条链走通。全部通过 environment 执行，全部返回统一的 `Observation`。

## 二、每个工具的验收（不用等 Agent 写完，单独测）

1. 正常路径的返回，你自己读一遍能看懂在说什么
2. 每条错误路径都有 根因 + 重试指令 + 停止条件（三种错手工各触发一次）
3. 超大输入不炸：读万行文件、搜命中几千次的词，且截断被明确告知
4. 安全边界生效：路径白名单挡住 /etc/passwd，命令 allowlist 挡住 rm -rf

## 三、read_file

### 规格

必须支持行范围，否则大文件读不了。带行号 —— 即使 apply_patch 不需要行号，
行号也让模型能说「我要看 200-300 行」，且读 trajectory 时对得上位置。

### 执行步骤

| 步 | 做什么 | 失败时 | 状态 |
| --- | --- | --- | --- |
| 1 | 校验 `offset` / `limit`：类型 → `≥ 1`（`_validate_positive_int`） | `INVALID_ARGUMENT` | ✅ 09-15 |
| 2 | 路径：类型 → 非空 → 无 `\x00` → join + normpath → 白名单（`_validate_legal_path`） | `INVALID_ARGUMENT` / `PATH_OUTSIDE_ROOT` | ✅ 09-15 |
| 3 | `shlex.quote` 拼命令 → `env.execute`：`test` 守卫 + awk 只取 `[offset, offset+limit-1]`，总行数 `NR` 走 stderr（决定 13–14） | — | ✅ 09-15 |
| 4 | 分派 `ExecResult`：超时 / 退出码 90 不存在 / 91 是目录 | `TIMEOUT` / `PATH_NOT_FOUND` / `INVALID_ARGUMENT`；其余非 0 → `UNCLASSIFIED`（决定 16–17） | ✅ 09-15 |
| 5 | stdout 切行，stderr 解析总行数，越界检查（总行数 0 → ok 空文件；offset > 总行数 → 错；终点超出 → ok，读到末尾） | `INVALID_ARGUMENT`；stderr 不是纯数字 → `UNCLASSIFIED`（决定 18） | ✅ 09-15 |
| 6 | 加行号、按字符预算截停（切片已由 awk 做完）；预算 = `observation.MAX_CONTENT_CHARS`，至少保留 1 行（决定 19），放进去时记下行号 | — | ✅ 09-15 |
| 7 | 组装 `Observation.ok`；`last < total` 即没读完，next_actions 给出续读 `offset=last+1`；否则 summary 写明已到末尾、共 N 行 | — | ✅ 09-15 |

### 决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| 1 | offset 越出文件末尾返回 **error**；起点在内、终点超出返回 **ok** 并说明「已到末尾，共 N 行」 | 空 ok 会让模型以为「那里没东西」，在错的前提上继续；而模型事先不知道文件多长，终点超出不该罚它 | 两种都 ok · 两种都 error |
| 2 | 新增 `FailureCategory.INVALID_ARGUMENT` | `failure_category` 是给「三周后不看代码读出为什么失败」用的（`observation.py` 类 docstring）；`is_env_error()` 用集合成员判断，新成员自动为 False —— 参数错算模型的 | 塞进 `UNCLASSIFIED`（归因表读不出原因） |
| 3 | 默认 `offset=1, limit=200`，写成 `Final` 常量 | astropy 911 个 `.py` 行数 p50=154（`DESIGN-environment.md` §六），一半以上的文件一次读完；模型最常见的调用是「打开看看」，不该逼它猜数 | 不给默认值 |
| 4 | 超长内容**按字符预算截停**，不交给 `render()` | `_truncate` 丢**中段**、只说丢了多少（`observation.py` `_truncate` 决定二、三），工具给的续读 offset 会跳过被丢的几百行 —— 模型永远读不到中段，还以为读完了。截停则续读行号精确、不切半行 | (a) limit 硬上限：管不住长行，报错白耗一步 · (c) 不管 |
| 5 | 类型在工具里校验，用 `type(x) is int` | 验收要求工具能单独测，不能假设还没写的 `loop.py` 已转好类型；标注不在运行时检查，`"3"` 会让 `TypeError` 冲出工具；`isinstance(True, int)` 为 True | 押给 `loop.py` · 用 `isinstance` |
| 6 | 先查类型再比大小 | 反过来 `"3" < 1` 先炸 | — |
| 7 | 路径校验是**共享函数**，返回 `str \| Observation`，调用方 `isinstance` 分流 | `list_files` / `search_code` / `apply_patch` 都有 path 参数；返回形状与 `_validate_positive_int` 的 `Observation \| None` 同一思路 | 各工具复制 · 返回 `(path, err)` 元组 |
| 8 | 根目录常量 `REPO_ROOT` 定义在 `environment.py`，`execute()` 的 `-w` 与白名单共用 | 同一个事实一个来源（`observation.py` ToolStatus 的否决理由：「同一个事实两个来源，迟早对不上」） | `tools.py` 再硬编码一份 |
| 9 | 非 str / 空串 / 含 `\x00` 在第 2 步拦下 | 空串会被归一化成 `/testbed` 并通过白名单，拖到读文件才报「是目录」，根因指错；另两种会让异常冲出工具 | 交给后续步骤 |
| 10 | 白名单 = `full == REPO_ROOT or full.startswith(REPO_ROOT + "/")`，先 join 再 normpath 再判断 | `join` 遇绝对路径丢前缀、`normpath` 算掉 `..`、`/testbed2` 前缀陷阱，顺序反了都会漏 | 只防 `../` 字符串匹配 |
| 11 | 用 `posixpath` 而不是 `os.path` | 路径是容器里的，永远是 Linux 规则；显式写出来就说明「这不是宿主机路径」 | `os.path` |
| 12 | 报错信息写明**哪个参数、收到的值（`!r`）、合法范围**；content 列出本次调用的全部参数，越界时再加归一化后的路径 | 本人要求：「错误要让人看明白具体错在哪」。`!r` 才看得出 `'3'` 和 `3`、`''` 和空 | — |
| 13 | **D3（09-15 本人定）**：awk 只打印请求范围，`END` 把 `NR` 打到 stderr；不加提前 `exit` | 总行数由 awk 数，无结尾换行、空文件都对（§六）；只传回请求的行，仓库里 3.4MB 的数据文件、1.6MB 的 `.so` 不会整篇进 `ExecResult` | `cat` 整篇 + Python `split`：末尾多一个 `''`、空文件切出 `['']` 被当成 1 行，都要特判 |
| 14 | **D4（09-08 结论，09-15 本人确认）**：前置 `test -e … \|\| exit 90; test -d … && exit 91;`，按退出码分类，不解析 stderr 文本；命令里不用管道 | `cat` 对不存在和是目录都 exit 1，只有文字不同；不用管道就不需要 `pipefail` | 解析 stderr 文本 · 用管道再加 `set -o pipefail` |
| 15 | **D5（09-15 本人定）**：空文件（总行数 0）读 offset=1 返回 **ok** 并说明「文件为空」，是决定 1 的例外 | 空 `__init__.py` 很常见，模型读它没做错事；报 error 会让它以为路径错了去换文件 | 按决定 1 一律 error |
| 16 | **（09-15 本人定）** 退出码 91「是目录」→ `INVALID_ARGUMENT`，summary 写明 is a directory，next_actions 指向 `list_files` | 路径存在，错在模型传错了参数种类，与决定 2 同类；不为一种情况扩枚举 | 新增 `IS_A_DIRECTORY`（`list_files` 收到文件时还得对称加一个）· `PATH_NOT_FOUND`（名字说谎：路径明明存在，模型会去换路径） |
| 17 | **（09-15 本人定）** 0 / 90 / 91 以外的退出码 → `UNCLASSIFIED`，content 原样附 `exit_code` 和 stderr | 这一桶的定义就是「没预料到」（`DESIGN-observation.md` 决定 6）；附原始事实，badcase 归因时能事后重分 | `IO_ERROR`（第 3 步审稿时自己拼错命令的 exit 2 也会被算成环境故障，污染归因表）· 按码段 ≥125 → `IO_ERROR`（码段含义未实测） |
| 18 | **（09-15 本人定）** exit 0 但 stderr 解析不出 int（如 awk 警告混入）→ `try/except ValueError` 归 `UNCLASSIFIED`，content 附 stderr；空文件判断排在越界检查**之前**，且对任何 offset 都返回 ok | `int()` 只容忍首尾空白（§六），异常冲出工具会让 loop 崩；offset ≥ 1 恒大于 0，顺序反了空文件必被判越界 | 让 `ValueError` 冲出去 · 空文件只对 offset=1 放行 |
| 19 | **（09-15 本人定）决定 4 的洞**：预算装不下时**至少保留 1 行**，这一行超长就交给 `render()` 的 `_truncate` 截 | 只剩一行时 `_truncate` 丢的是这一行的中段，续读 offset = 该行 + 1 仍精确 —— 决定 4 否决 render 截的理由（跳过整行）在这里不成立；astropy 实测超预算单行 39 条、`.py` 0 条（§六），全是数据文件与压缩 JS，读中段本来就没用；复用现有一层，代码最少 | 工具里单独截这一行并明说（多一个分支、多一种组合要测）· 报 error（模型没做错事，也没有能改的参数） |

### 错误契约（09-15 实测 render）

| 输入 | category | summary | next_actions |
| --- | --- | --- | --- |
| `offset='3'` | `invalid_argument` | `offset should be int, received: '3'` | 传 ≥ 1 的整数或省略用默认值 · 这是参数错，换文件没用 |
| `limit=0` | `invalid_argument` | `limit should be at least 1, received: 0` | 同上 |
| `path=None` / `123` | `invalid_argument` | `Path should be str, received: None` | 传相对仓库根的字符串路径 |
| `path=''` | `invalid_argument` | `Path should not be ''` | 传非空相对路径 |
| `path='a\x00b'` | `invalid_argument` | `Path: 'a\x00b' includes '\x00'` | 去掉 `\x00` 重试 |
| `'../etc/passwd'` 等 | `path_outside_root` | `Path: '../etc/passwd' is outside of the root: /testbed` | 用 `/testbed` 下的相对路径 · `/testbed` 外的文件读不到，别换别的绝对路径重试 |
| `'nope.py'`（容器，exit 90） | `path_not_found` | `Path: 'nope.py' does not exist` | 对上级目录 `list_files` · 别逐个猜路径，不知道在哪就 `search_code` |
| `'astropy'`（容器，exit 91） | `invalid_argument` | `Path: 'astropy' is a directory, not a file` | 对它 `list_files` 再读里面的文件 · 同一目录重试没用 |
| 伪造 `timed_out=True` | `timeout` | `Reading 'setup.py' timed out after 60.0s` | 原样重试一次 · 再超时就别读这个文件，调小 limit 没用（awk 仍扫全文，决定 13） |
| 伪造 exit 2 | `unclassified` | `Reading 'setup.py' failed with unexpected exit code 2` | 原样重试一次 · 同样的 stderr 再出现就跳过这个文件；content 附 exit code 与 stderr（决定 17） |
| `setup.py` offset=69（68 行） | `invalid_argument` | `offset 69 is beyond the end of 'setup.py', which has 68 lines` | 传 1–68 之间的 offset · 文件存在，换文件没用 |
| 空 `astropy/config/tests/__init__.py`（offset=1 与 5） | —（**ok**） | `Path: '…/__init__.py' is an empty file (0 lines)` | 无；content 为空，render 只输出 summary |
| 伪造 exit 0 + stderr `'awk: warn\n68\n'` | `unclassified` | `Reading 'setup.py' returned an unreadable line count` | 同决定 17 |

`setup.py` offset=68（最后一行）、offset=60 limit=20（终点超出）均通过第 5 步。

第 3–5 步的 content 一律是 `Current args: …, normalised path: '/testbed/…'`（`path_ctx`）。

第 2 步 12 个路径全部归类正确：3 个合法路径放行（`'./astropy/../setup.py'` → `'/testbed/setup.py'`），
`../etc/passwd` `/etc/passwd` `//etc/passwd` `/testbed2/x.py` `/testbedXYZ/../testbed_evil/a.py` 越界，
`''` `None` `123` `'a\x00b'` 参数错。`ruff check agent/` 全过。

## 四、待写工具的规格（尚未实现）

### list_files(path=".", depth=2) —— 决定已定（09-15），实现中

规格：列出 `path` 下 `depth` 层以内的文件和目录，每行一个相对 `/testbed` 的完整路径，目录带 `/` 和其下文件数。
只按路径看结构，不看内容。实测依据见 §六「list_files」段。

#### 执行步骤

| 步 | 做什么 | 失败时 | 状态 |
| --- | --- | --- | --- |
| 1 | 校验 `depth`（`_validate_positive_int`） | `INVALID_ARGUMENT` | ✅ 09-15 本人 |
| 2 | 路径（`_validate_legal_path`，默认 `"."` → `/testbed`） | `INVALID_ARGUMENT` / `PATH_OUTSIDE_ROOT` | ✅ 09-15 本人 |
| 3 | `test -e … \|\| exit 90; test -d … \|\| exit 92; git --literal-pathspecs ls-files -z --cached --others --exclude-standard -- <quoted>` | — | ✅ 09-15 本人 |
| 4 | 分派：超时 / 90 不存在 / 92 不是目录 / 其余非 0 | `TIMEOUT` / `PATH_NOT_FOUND` / `INVALID_ARGUMENT` / `UNCLASSIFIED` | ✅ 09-15 **Claude 写**（与 read_file 第 4 步同构，本人定：重复的知识点不再手写） |

第 1–4 步冒烟（09-15，astropy-12907）：参数错 6 项（`'3'` `0` `True` / `../etc/passwd` `''` `5`）归类正确；
假 exec 触发超时 → `TIMEOUT`、exit 128 → `UNCLASSIFIED`；真容器 `setup.py` → 92 `INVALID_ARGUMENT`、`nope` → 90 `PATH_NOT_FOUND`，
`.` `astropy` `astropy.egg-info` 通过分派；`'astropy/a b'` 渲染出的命令 quote 正确；`ruff check agent/` 全过。

第 1–3 步审稿抓到的 bug（本人版）：① `if err := f(...) is not None` 少括号，`err` 绑定成 bool，非法 depth 返回 `True`
（§六「`:=` 优先级」早有记录，第二次踩）② 定义 `arg_ctx`、使用 `args_ctx`，`NameError`；首次改名只改了定义处，引用处漏改
—— 两个 bug 叠加时①把②遮住（非法输入永远在第 1 步返回），合法输入跑一次才露出来（教训 1）。
| 5 | `stdout.split("\0")[:-1]` 得到相对仓库根的文件列表；为空 → ok 并说明（L9） | — | ✅ 09-15 **Claude 写**（同 read_file 第 5 步的 `[:-1]`）；冒烟：`astropy.egg-info`、新建空目录 → ok + 两条 next_actions |
| 6 | 按 depth 聚合：深度相对 `path` 计；目录行带其下文件总数；超预算则 depth − 1 重算，到 1 仍超则按预算截条目（L2） | — | ✅ 09-15：`_aggregate` 与降深度循环**本人**（4 版，bug 见 §五）；depth=1 截条目分支 **Claude 写**（同 read_file 决定 19） |
| 7 | 组装 `Observation.ok`：降过深度或截过条目，summary 写明，next_actions 指向对子目录再调 | — | ✅ 09-15 **Claude 写**；验收 21/21 见 §六 |

#### 决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| L1 | `depth` 默认 **2**，**不设硬上限**，复用 `_validate_positive_int` | 根目录 depth=2 三个仓库都装得下（django 5763 字符），depth=3 三个全爆（17818–61704）；固定上限两头不讨好：2 在子目录不够（`astropy/io` 合理用 3），3 在根目录必爆 —— 超预算交给 L2 | 硬上限 3 · 默认 1（根目录第一次调用必然还要再调） |
| L2 | 超 `MAX_CONTENT_CHARS` → **自动降 depth** 直到装下，summary 写明「请求 N，实际 M」；depth=1 仍超才按预算截条目并写明省略数 | 降深度保住全局形状，截条目会让排在后面的目录整个消失；最大单目录直接子项 281（django `docs/releases/`），depth=1 截条目的分支实际很难触发 | 截条目 · 报 error（模型没做错事） |
| L3 | **每个目录行带其下文件总数**：`astropy/io/ (364 files)`（单数也写 `files`，不为此加分支） | 「这里很多」是决定下一步钻哪里的信息；一条规则覆盖所有目录，不区分是否在深度边界（比只给边界目录少一个分支） | 只列名字 · 只给边界目录计数 |
| L4 | 数据源 `git ls-files --cached --others --exclude-standard`，加 **`-z`** 和 **`--literal-pathspecs`** | `find` 会列出 astropy 64 个构建产物（`.so`、生成的 `.c`、egg-info）；`--others` 让 agent 新建的文件可见；默认输出把 `é.py` 转义成 `"astropy/\303\251.py"`、含换行的文件名也会被转义，`-z` 才是原文；pathspec 默认按通配解释，列 `[x]` 会把同级文件 `x` 一起带出来 | `find` + 手写排除（排除规则补不全） · 不加 `-z` · 不加 `--literal-pathspecs` |
| L5 | shell 只列，**聚合在 Python**；命令不用管道；守卫 `test -e \|\| exit 90`（复用 `_EXIT_NOT_FOUND`）、`test -d \|\| exit 92` | 满足 §七 义务「不用管道」；聚合逻辑能单测；django 6649 行 stdout 对 subprocess 不是负担（`environment.py` 不截 stdout） | `git … \| awk` 聚合 |
| L6 | **不接收 pattern / glob 参数**；与 `search_code` 分工 = 按路径看结构 vs 按内容找 | 存在理由：还不知道搜什么关键词时认识仓库；`read_file` 的 `PATH_NOT_FOUND` / 是目录两条 next_actions 已指向它。加 glob 就和搜索重叠 | 加 glob 参数 |
| L7 | 每行一个**相对 `/testbed` 的完整路径**，目录带 `/`，按路径排序 | 模型可直接复制进 `read_file`，不必从缩进拼路径 | tree 式缩进 |
| L8 | `path` 默认 `"."` | 与 read_file 决定 3 同理：最常见的调用是「先看看仓库长什么样」；`_validate_legal_path(".")` 归一化为 `/testbed`，无需特判 | 不给默认值 |
| L9 | 路径是文件（exit 92）→ `INVALID_ARGUMENT`，next_actions 指向 `read_file`；目录下无可列文件（全被 ignore，如 `astropy.egg-info`，exit 0 空输出）→ **ok** 并说明 gitignore 的内容不显示 | 与 read_file 决定 16 对称；空结果模型没做错事，但要告诉它「空」的原因，否则会以为目录真的空 | `IS_A_FILE` 新枚举 · 空结果报 error |
| L10 | **（09-15 本人定）** 第 6 步的聚合抽成纯函数 `_aggregate(files, base, depth) -> list[str]`，不碰容器 | L2 降深度要按不同 depth 反复重算，本来就要调多次；纯函数不经 `env` 就能单测，`test_tools.py`「真容器 vs 假 exec」对这部分不成立 | 聚合内联在 `list_files` 的循环体里 |

已知边界：工作区里删掉但未提交的已跟踪文件，`--cached` 仍会列出（§六实测）；模型随后 `read_file` 得到 `PATH_NOT_FOUND`，
next_actions 引它重新 list。危害低，不处理。

### search_code(pattern, path=".", fixed_string=False, context=2, max_results=20) —— ✅ 09-15，Claude 写

规格：按内容搜 `path`（文件或目录）下的文本文件；pattern 默认按 PCRE 解释，`fixed_string=True` 按字面量。
输出按文件分组：文件名单独一行（相对 `/testbed`，可直接喂 `read_file`），下面 `  行号: 命中行` / `  行号- 上下文行`，同文件内不相邻的段用 `--` 隔开。
实测依据见 §六「search_code」段。**S1–S3 三件事本人 09-15 拍板**；S4 起是 Claude 按实测定的，本人审稿时可推翻。

#### 执行步骤（全部 Claude 写，待本人审）

| 步 | 做什么 | 失败时 |
| --- | --- | --- |
| 1 | 校验 `pattern`（非空 str、无换行 / NUL）· `fixed_string`（bool）· `context`（int 0–10）· `max_results`（`_validate_positive_int`） | `INVALID_ARGUMENT`，不发命令 |
| 2 | 路径（`_validate_legal_path`，默认 `"."`） | `INVALID_ARGUMENT` / `PATH_OUTSIDE_ROOT` |
| 3 | 第一遍计数：`test -e … \|\| exit 90`；`git grep -c -z` 跑 tracked 模式和 `--untracked` 模式各一次，退出码在 shell 里合并 | — |
| 4 | 分派：超时 / 90 / **1 → ok「没命中」** / **128 → pattern 被拒** / 其余非 0 | `TIMEOUT` / `PATH_NOT_FOUND` / — / `INVALID_ARGUMENT`（附 stderr）/ `UNCLASSIFIED` |
| 5 | `_parse_counts` 去重排序；按路径顺序选文件，累计命中 ≥ `max_results` 或满 400 个文件停 | — |
| 6 | 第二遍只搜选中文件：`git grep --no-index -n -z --column -C <context>` | 超时 → `TIMEOUT`；非 0 → `UNCLASSIFIED` |
| 7 | `_parse_grep_lines` 解析；`_render_hits` 排版，`max_results` 和字符预算谁先到听谁的，至少 1 条 | — |
| 8 | 组装：summary 写「显示 N / 共 M 条，K 个文件」；截断时 next_actions 列命中最多的 5 个文件，并按截断原因说明「调大 max_results 有没有用」 | — |

#### 决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| S1 | **默认 PCRE（`-P`）+ `fixed_string` 开关（`-F`）**（本人定） | 模型写的是 Python `re` 语法。BRE：`def __init__\(` → exit 128，`foo\|bar` 当字面量；**ERE：`\d+` 静默匹配 astropy 275,601 行**（`\d` = 字母 d）；PCRE 六个样例全部与 Python 语义一致，速度 33ms vs BRE 35ms | 默认字面量 + 正则开关 · 只给 PCRE 不给开关（搜 `def f(` 必须先报错一次） |
| S2 | **`context` 默认 2，允许 0–10**（本人定），超出 → `INVALID_ARGUMENT` 并指向 `read_file` | 0 行逼模型必然再调一次 `read_file`；更多上下文按行号 `read_file` 更省。不复用 `_validate_positive_int`（0 合法），就地校验 | 默认 3 · 固定 2 不给参数 |
| S3 | **`max_results` 默认 20、不设硬上限 + 字符预算**；截断时列命中最多的 5 个文件（本人定） | 【推算】`-C2` 下每条命中 155–442 字符，10000 预算放 22–60 条，20 条基本装得下；文件分布告诉模型往哪收窄。因预算截断时明说「调大 max_results 没用」，防止模型空转 | 只给总数 · 超 200 条只给分布 |
| S4 | **两遍**：第一遍 `-c -z` 只计数，第二遍只对选中文件取内容 | git 2.34 **没有 `--max-count`**（exit 129）；单遍 `-C2` 的 stdout django `self` 19MB、`e` 74MB。`-c -z` 在 django `e` 上 219KB / 224ms；两遍整体 django `e` 0.95s | 单遍取全量再在 Python 截 · shell 里 `head` 截（违反「不用管道」） |
| S5 | 固定参数：`-I`（跳二进制）· `--literal-pathspecs` · `-e`（pattern 以 `-` 开头会被当选项：`unknown option 'version'`） | 不加 `-I` 输出 `Binary file … matches` 行；L4 同理 | — |
| S6 | 第二遍用 **`-z --column`**：命中行 `path\0行号\0列号\0文本`，上下文行少一个字段 | 不加 `-z`：文件名 `a:1:b.py` 与 `-n` 分隔符混淆，`é.py` 被转义；只加 `-z`：命中行和上下文行分隔符都成 `\0`，**分不清**；`--column` 只给命中行加列号 | 不加 `-z` + `core.quotepath=false`（冒号歧义仍在） |
| S7 | exit 1（没命中）→ **ok**，next_actions 提示转义 / `fixed_string`、说明 ignore 与二进制不搜，并给停止条件 | 与 L9 同理：模型没做错事，但要知道「空」的可能原因 | 报 error |
| S8 | exit 128 → **`INVALID_ARGUMENT` 并附 stderr**（不解析 stderr，只转交） | 路径已在第 2 步校验、pathspec 是字面量，实测中 128 只由 pattern 语法错触发（【判断】其他 fatal 来源未见，不排除）；stderr 原文（`missing closing parenthesis`）就是修正指引；next_actions 另给停止条件以防不是 pattern 的问题 | 归 `UNCLASSIFIED`（模型不知道该改 pattern） |
| S9 | 单行超过 **500 字符**截断并注明剩余字符数 | 命中行 > 2000 字符：astropy 6 行、django 3 行，最长 89,478（压缩 JS） | 不截，交给 render 的头尾截断（会把其他命中一起截掉） |
| S10 | 输出按文件分组（`--heading` 式），行号右对齐 6 位 | 文件名不在每行重复，同预算多放命中；文件名行原样可喂 `read_file`（验收 R8b） | 每行 `path:行号:文本` |
| S11 | `path` 可以是文件或目录，只守卫 `test -e`（exit 90） | `git grep` 两者都接受；与 `read_file` / `list_files` 不同，这里没有「类型不对」的错误 | 再加 `test -d` |
| S12 | pattern 拒绝空串、换行、NUL | 空串匹配每一行；NUL 让 `subprocess` 启动前抛 `ValueError`（§六）；搜索按行进行，多行 pattern 没有意义 | — |
| S13 | 计数解析、记录解析、排版抽成纯函数 `_parse_counts` / `_parse_grep_lines` / `_render_hits` | 沿用 L10；截断逻辑的边界（隔段前文、预算、context=0）不起容器就能测，验收 P1–P7 | 内联 |
| S14 | **第一遍 tracked + `--untracked` 各跑一次取并集；第二遍 `--no-index`** | **`--untracked` 会跳过已跟踪但匹配 `.gitignore` 的文件**：astropy 有 7 个（`*.c` 规则命中 `tokenizer.c` `bls.c` 等真源码），`self` 总数 33,722 vs 33,895；不加 `--untracked` 又看不到 agent 新建的文件。并集 = `list_files` 的 `--cached --others --exclude-standard` 语义。`--no-index` 对点名文件不看 ignore 规则 | 只用 `--untracked`（漏源码）· `--no-exclude-standard`（带出 64 个构建产物）· 先 `ls-files` 再逐个 grep（django 6649 个路径拼进命令会超单参数上限：WSL 宿主机实测 131,071 字符可以、131,072 `Argument list too long`；`docker exec … bash -lc <cmd>` 的 cmd 是一个参数） |
| S15 | 解析容忍二进制碎片：行文本里的 NUL 显示为 `\0`；对不上 `path\0行号\0` 结构的行跳过 | `-I` 只看文件开头（【判断】git 的二进制检测只看前 8000 字节）：`chandra_time.fits` 含 2,788 个 NUL 仍被当成文本，其 NUL 与碎片使第一版 `int('')` 崩溃（§五） | 按 `\0` 个数判断（遇 NUL 即错判） |

已知边界：
- 文件名含换行 → 按行切分会错位（只影响该文件的记录，被 S15 跳过）
- 二进制数据里的上下文行若恰以 `数字\0` 开头会被误判为命中行（S15 的正则无法区分），只出现在 FITS 这类数据文件
- 两遍之间文件被改 → 第二遍命中数与第一遍不同；单 agent 串行调用不会发生，不处理
- 超过 400 个文件的选择上限由预算推出（每个文件至少「文件名 + 1 行」），django `e` + `max_results=100000` 实测 0.81s 正常（D2）

### apply_patch(path, old_string, new_string) —— ✅ 09-16，Claude 写

> ⚠️ **分工**：本人 09-16 要求「全部做完，明天统一学习整个项目」，所以本工具与 `run_tests` `git_diff`
> `loop.py` `model.py` `run.py` **全部由 Claude 写**，不是 09-15 grilling 定的那版分工（那版还留着 `loop.py` 控制流给本人手写）。
> **面试口径据此说**：scaffold 的设计判据、错误契约、方法论取舍是本人定的，代码是 AI 写的、本人逐条审过。

规格：把 `path` 里**恰好出现一次**的 `old_string` 换成 `new_string`，返回改动处带行号的上下文。
造不出新文件，也不追加到文件末尾。实测依据见 §六「apply_patch」段。

编辑方式三选一，选 **(b) search / replace**：

| | 方式 | 代价 | 判决 |
| --- | --- | --- | --- |
| (a) | unified diff | token 最省，但模型极易算错行号 → `git apply` 失败。这是失败模式 1 的主要来源 | ❌ |
| (b) | **search / replace** | 不依赖行号，鲁棒；要求 `old_string` 唯一，token 更贵 | ✅ |
| (c) | 全文件重写 | 最鲁棒，但大文件 token 爆炸，且容易顺手改坏别处 → 失败模式 3 | ❌ |

理由三条：① 它把「行号算错」这一整类失败**消灭**，而不是缓解；② Aider 用的就是它，有公开工程实证可引用；
③ 它的失败可精确分类（找不到 / 不唯一），两种都能给明确恢复指令，那正是归因表要的数据。

**(b) 的表达力是实测过的，不是假设**：把 dev 子集 25 条 gold patch 的每个 hunk 拆成一对 `(old_string, new_string)`
（`tests/gold_replay.py`），**66/66 个 hunk 一次打上，零 `ANCHOR_AMBIGUOUS`**。
git 默认 `-U3` 的三行上下文，在真实修复上足够唯一 —— 这是 P2「不提供 `replace_all`」的依据。

#### 执行步骤

| 步 | 做什么 | 失败时 |
| --- | --- | --- |
| 1 | 校验 `old_string` / `new_string` 是 str、`old_string` 非空、两串不相同、`new_string` base64 后 ≤ 64KB | `INVALID_ARGUMENT` / `FILE_UNCHANGED`，不发命令 |
| 2 | 路径（`_validate_legal_path`） | `INVALID_ARGUMENT` / `PATH_OUTSIDE_ROOT` |
| 3 | `test -e … \|\| exit 90; test -d … && exit 91; test "$(stat -c %s …)" -le 2MB \|\| exit 93; base64 -w0 <quoted>` | — |
| 4 | 分派：超时 / 90 不存在 / 91 是目录 / 93 过大 / 其余非 0 | `TIMEOUT` / `PATH_NOT_FOUND` / `INVALID_ARGUMENT` / `INVALID_ARGUMENT` / `UNCLASSIFIED` |
| 5 | `base64.b64decode(validate=True)` 还原字节；解不开 → 说明读回来的不是 base64 | `UNCLASSIFIED` |
| 6 | `_find_all` 在**字节**上数出现次数（纯函数） | — |
| 7 | 0 次：先用 `_squeeze_whitespace` 判「只差空白」并报匹配所在行号；否则 `_closest_lines` 给最接近三行 | `ANCHOR_NOT_FOUND` |
| 8 | > 1 次：`_line_number_at` 报全部出现位置（最多 20 处） | `ANCHOR_AMBIGUOUS` |
| 9 | 恰好 1 次：`head -c <start> > tmp; printf %s <b64> \| base64 -d >> tmp; tail -c +<end+1> >> tmp; cat tmp > path` | `TIMEOUT` / `IO_ERROR`（exit 94） |
| 10 | 新内容在宿主机上拼出来，`_render_lines` 给改动处 ±3 行 | — |

#### 决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| P1 | 编辑方式 **search / replace** | 见上表；表达力已用 66 个真实 hunk 量过 | unified diff · 全文件重写 |
| P2 | `old_string` **必须唯一**，不提供 `replace_all` | 66/66 个 gold hunk 在 `-U3` 下就是唯一的，这个参数买不到东西，却多一条「改错了几处」的失败路径 | 加 `replace_all` 开关 |
| P3 | **不支持创建新文件** | 【实测】dev 子集 25 条 gold patch **0 条**新建文件；支持它要多两条错误路径（文件已存在 / 父目录不存在），换不来可答的面试追问（§七判据） | `old_string=""` 表示创建 |
| P4 | 文件内容用 **`base64 -w0`** 取回，不用 `cat` | `environment.execute` 用 `errors="replace"` 解码，非 UTF-8 字节会被替换成 U+FFFD，**再编码回去偏移就错位**，切片会切在字符中间。base64 保证字节完全一致，代价是 stdout 涨 33%（走管道，不是 argv，没有长度限制） | `cat`（偏移可能错位） |
| P5 | 写回用 **`head -c` / `tail -c` 切片再 `cat tmp > path`**，只把新片段经 base64 送进容器 | `docker exec … bash -c <cmd>` 的 cmd 是**一个 argv 元素**，Linux 单参数上限 128KB（`MAX_ARG_STRLEN`）；整文件回传 200KB 源码就爆。切片让前后两段**根本不出容器**。`cat tmp > path` 而不是 `mv`：保住 inode、权限位和属主 —— sympy 的 `bin/test` 是可执行文件（容器实测 mode 不变） | 整文件 base64 回传 · `mv tmp path`（丢权限位） |
| P6 | 匹配、最近三行、只差空白的判断**全在宿主机纯函数**里 | 沿用 L10：容器只给原始字节，判断逻辑不起容器就能单测 | 在容器里跑一段 python 程序做替换（测不了，且依赖容器里有 python） |
| P7 | 找不到时**先答「是不是只差空白」**，并报匹配所在行号；否则才给最接近三行（相似度 < 0.5 的不给） | 缩进错是 search/replace 最常见的失败；`_squeeze_whitespace` 不增删行，压过的文本里的偏移换算出来就是**原文行号**。给一堆不像的行比不给更误导 | 只给「最接近三行」（空白错时指向的是别的函数，容器实测过） |
| P8 | **2 MB 文件上限守卫** | `apply_patch` 是唯一会把整个文件搬到宿主机的工具（`read_file` 靠 awk 行范围从不整读）；没有守卫时一次误调就能把循环挂住 | 不设上限 |
| P9 | `new_string` base64 后 > 64KB → `INVALID_ARGUMENT`，要求拆成多次编辑 | 离 128KB 单参数上限留一半余量；一次改 64KB 的编辑本来就该拆 | 不校验，让 shell 报 `Argument list too long`（错误信息模型看不懂） |
| P10 | `old_string == new_string` → **`FILE_UNCHANGED`** | 这个枚举本来就是为它留的；报成功会让模型以为改过了 | 当成功返回 |
| P11 | 写回失败（exit 94）→ **`IO_ERROR`**，next_actions 要求先 `read_file` 查看当前状态 | 切片写回不是原子的：`cat tmp > path` 中途失败会留下截断的文件，必须告诉模型去看 | `UNCLASSIFIED`（模型不知道文件可能已经坏了） |
| P12 | 成功时返回**改完之后**的上下文（±3 行），不是改之前的 | 让模型立刻看到自己改出来的样子，直接减少失败模式 3；新内容宿主机算得出来，不用再进一次容器 | 只回 summary · 再调一次容器读 |
| P13 | 连续失败的**停止条件写在 next_actions 里**，计数由 `loop.py` 落实（决定 C10） | 工具是无状态函数，记不住「这是第几次」；契约文字和实际拦截分两层，两边都有 | 在工具里加状态 |
| P14 | 错误信息里的参数用 `_preview` 缩成一行 | `old_string` 可能几百行，原样塞进 content 会把预算吃光 | 原样 `repr` |
| P15 | 不唯一时最多报 **20 处** | 超过 20 处说明锚点选得太泛，列全了也没用 | 全列 |

### run_tests(target, timeout) —— ✅ 09-16，Claude 写

规格：在容器的 testbed 环境里跑测试。运行器前缀和日志解析器由 `run.py` **按实例绑定**，模型看不到；
通过的测试只报数量，失败的报名字，再附原始输出的**尾部**。

#### 执行步骤

| 步 | 做什么 | 失败时 |
| --- | --- | --- |
| 1 | 校验 `timeout`（≥1 且 ≤ 900）、`target` 是非空 str | `INVALID_ARGUMENT` |
| 2 | `shlex.split(target)` 拆目标，逐个 `shlex.quote` | 引号不配对 → `INVALID_ARGUMENT` |
| 3 | `( source /opt/miniconda3/bin/activate && conda activate testbed && <前缀> <目标> ) 2>&1` | — |
| 4 | 超时先判 | `TIMEOUT` |
| 5 | 用 harness 的 `log_parser` 解析日志；一条结果都没有 → 目标名错或代码 import 不了 | `UNCLASSIFIED`（附输出尾部） |
| 6 | 有结果：失败的列名字（最多 25 个），通过的只报数量，再接日志尾部 | — **ok**（测试挂了也是 ok） |

#### 决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| T1 | 测试命令**从实例自带的 `eval_script` 里抽**，不按仓库硬编码 | 75 条（subset 25 + holdout 50）只有 **5 种**运行器前缀，但每种的参数都不一样（django 要 `--settings=test_sqlite --parallel 1`，sympy 要 `PYTHONWARNINGS=…`，sphinx 走 `tox --current-env -epy39 --`）。硬编码等于把 7 个仓库的构建知识抄一遍，抄错一条那条实例的 `run_tests` 就是废的 | 按 `repo` 字段查表 · 一律 `pytest`（django / sympy / sphinx 三家都跑不起来） |
| T2 | `target` 先 `shlex.split` 再**逐个 `shlex.quote`** | `environment.py` §七压下来的义务；实测 `t.py; rm -rf /` 变成 `'t.py;' rm -rf /`，分号成了 pytest 的一个普通参数，没有注入 | 原样拼进命令 · 正则黑名单过滤元字符（补不全） |
| T3 | `stderr` 用 `2>&1` 并进 `stdout` | `log_parser` 要的是一整份日志；分开存会让 pytest 的进度行和 traceback 错位 | 宿主机上拼 `stdout + stderr`（顺序不对） |
| T4 | 截断**只留尾部**，不像 `observation._truncate` 那样头尾各留一半 | 测试输出的开头是 session 头（平台、插件版本、rootdir），失败详情和统计行都印在最后。头部信息密度接近零 | 复用 `_truncate` |
| T5 | `timeout` 硬上限 **900 秒**，超出报错并引导收窄目标 | 死循环的测试会挂死整个 loop；`environment.execute` 的超时只杀宿主机上的 `docker exec` 客户端，容器里的进程还活着（DESIGN-environment §七），所以上限必须由本层守住 | 不设上限 · 让模型自己传任意值 |
| T6 | 测试失败（退出码非 0）仍然是 **ok** | observation 决定 1、3：`status` 回答的是「工具有没有完成它的活」，不是好消息坏消息。测试挂了正是模型要的信息 | 非 0 → `ERROR`（模型会以为工具坏了） |
| T7 | 一条测试结果都解析不出来 → **`UNCLASSIFIED`**，next_actions 同时给两条路 | 两种原因长得一样：目标名写错，或者**模型自己的编辑把代码改到 import 不了**。硬塞 `INVALID_ARGUMENT` 会把后者误记成参数错误，归因表就脏了 —— `UNCLASSIFIED` 本来就是「预料外，事后人工重分」的桶 | `INVALID_ARGUMENT` |
| T8 | **`target` 没有默认值**，必须模型自己指定 | 【方法论】默认跑实例自己的评分目标 = 告诉自己的 Agent grader 用哪些测试文件，**mini baseline 没有这个信息，两边数字就不可比了**。`run.py` 的 `derive_test_command` 因此把评分目标从前缀里剔掉，75 条全部验过没有泄露（`tests/test_run.py`） | 空 target → 跑评分目标（泄露）· 空 target → 跑全套（django 几十秒起） |
| T9 | 目标写法提示（`target_hint`）按运行器注入工具描述 | django 要点号模块名、其余要文件路径，模型不可能凭空知道。提示按**运行器**给，不引用任何具体实例，所以不泄露 | 不给提示（模型第一次必然写错一次） |

**要主动说出口的一句**：运行器前缀是从实例元数据里抽的，等于我的 scaffold **白拿了**「这个仓库怎么跑测试」这条环境知识，
而 mini-SWE-agent 得自己摸索。这是我方的一个优势，报告里要写明，不能装作两边条件完全一样。

### git_diff(path=".") —— ✅ 09-16，Claude 写

两个角色别混：

- **harness 提取答案**：`run.py` 的 `extract_patch`，在 loop 外面做，不占 Agent 步数
- **Agent 自查**：本工具，提交前看一眼自己改了什么

保留为 Agent 工具的理由是第二个角色有明确因果：它让模型发现「我改了不该改的文件」，直接减少失败模式 3（PASS_TO_PASS 挂）。
**执行计划 §八「`git_diff` 到底是哪个」这条悬置项到此关闭：两个都是，但由两段不同的代码承担。**

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| G1 | 自查工具与答案提取**分成两段代码** | 提取要在循环之外、不计步数、不受模型影响；自查要计步数、要给 next_actions。同一个函数做两件事，改一个就会碰坏另一个 | 一个函数两用 · 只做提取（模型看不到自己改了什么） |
| G2 | `--stat` 与未跟踪清单**一条命令取回**，正文单独一条 | 两段形状不同（`?? ` 前缀 vs stat 表格），混不了，省一次往返；正文可能很大，要单独判断预算 | 三条命令 · 用分隔符把三段拼在一条命令里（分隔符可能出现在 diff 正文里） |
| G3 | 正文超预算**截头部**，并引导按单文件再调 | `--stat` 已经说清楚改了几个文件，正文从头读才对得上；从尾部读会落在最后一个文件中间 | 复用 `_keep_tail`（测试输出才该留尾部） |

## 五、已纠正的错误

### 设计判断（Claude 的，3 条）

| 原判断 | 实际 | 结论 |
| --- | --- | --- |
| 09-14 规格写「django 递归到底是几万个文件，一次就能打满上下文」 | 09-15 进 django-15863 容器实测：`git ls-files` **6649** 个，含忽略文件 6657 个 | 「打满上下文」的结论不变（depth=3 就 61704 字符），但依据改用实测数（§六），决定见 L1–L2 |
| 09-15 §六「仓库规模」记 django 根目录 depth=1 30 条、depth=2 300 条 | 当时的 awk 统计没加 `-z`：非 ASCII 文件名被转义成 `"django/…` 开头，多出假的顶层条目。加 `-z` 后实测 **29 / 298** 条；带计数后缀 depth=2 为 8303 字符 | §六 原行保留作对照，以验收行的数为准。L4 加 `-z` 的理由又多一条实证 |
| 09-14 把 D3（读法）、D4（不存在 vs 是目录）当作悬置，推荐「`cat` 全文 + Python 切片」、区分失败「只能看 stderr 或先 `test -f`」 | `DESIGN-environment.md` §五 09-08 已有结论：awk `NR` 数行正确；前置 `test` 守卫 + 自定义退出码（90+），不解析文本。Claude 没回查设计档案就出题 | 以 09-08 结论为准。补充：WSL 宿主机上 `cat` 对不存在和是目录**都是 exit 1**（09-08 记录的是 2，命令不同），同样说明退出码分不开 |
| 决定 4 起初表述成「limit 要不要设上限」 | 读了 `_truncate` 决定三才发现真正的问题是「超长内容由谁截」：render 丢中段，工具给的续读行号失效 | 改问法后选 (b) 按字符预算截停 |

### 第 1–2 步代码 bug（5 版审稿，按类归）

**语法错（6 个）**

1. 用 `!` 取反 —— Python 是 `not`；`!` 只出现在 `!=` 和 f-string 的 `!r`
2. `for name, val, default_val int in [...]` —— for 的循环变量**不能写标注**（实测 `for x: int in [1]` → SyntaxError）
3. 同一行 `in` 写成 `int`、`if` 行尾少冒号、`return` 没缩进进 if
4. `startswith(REPO_ROOT/)` —— `/` 是除法；只有 `pathlib.Path` 重载了它，字符串拼接用 `+`

**import 期就炸（2 个）** —— 返回值标注在 `def` 那一刻求值（3.12）

5. `Observation` / `FailureCategory` / `Optional` 没 import；`environment.py` 用 `Final` 没 import → **整个 `agent` 包 import 失败，`DockerEnvironment` 一起不可用**

**只在某条路径上炸（4 个）**

6. `PATH_OUTSIDE_ROOT` 少 `FailureCategory.` 前缀；改完又残留一个 `{ROOT}` —— 都只在越界分支触发
7. `summray=` —— ruff 查不出，关键字参数名只在调用时核对
8. `default_va` 拼错 —— 执行到才 NameError
9. `instance(result, Observation)` —— **第二次**（`DESIGN-environment.md` 代码 bug 第 11 条也是它）

**不报错只是全错（6 个）** —— 最危险的一类

10. `Observation.error(cat, "msg")` 位置传 summary → TypeError（这个会响）；但字符串**少 `f` 前缀** → 模型原样收到 `{offset}`
11. `if type(limit) is int:` 少 `not` → **合法 limit 全被拦、非法全放行**：正常调用必然失败，`offset=0` 被报成 limit 的错，`limit='3'` 冲进 `<` 崩掉。**只测错误路径发现不了**
12. summary 里的值没用 `!r` → `offset should be int, receive: 3`：类型错恰恰是最需要看清类型的时候
13. f-string 里写常量名 `DEFAULT_OFFSET` 而不是插值 → 模型收到一个它不认识的名字（ruff F541）
14. 白名单 `full != ROOT or not full.startswith(...)` —— 德摩根律取反时 `or` 没变 `and`，**恒真，合法路径全拦**
15. `startswith(REPO_ROOT)` 少 `"/"` → `/testbed2/x.py` 放行（前缀陷阱，第一轮就演示过，改写时回归）

**文案（3 处）**：next_actions 一条说「重试」一条说「别重试」；一句话被拆成两个列表项（每项渲染成独立 `-` 条目）；
「return an error」写给了没有这个动作的模型。

### 第 3 步代码 bug（09-15，4 版审稿）

**语法 / 名字（4 个）**

16. `f"... exit 90";` —— 分号写在引号外，括号里成了 Python 语句分隔符 → SyntaxError。挪进引号后每段还要以 `"; "` 结尾，否则拼成 `exit 91awk`
17. `END {{print} NR > ...}` —— awk 的 `print NR > ...` 是一个整体，花括号只包了 `print`；下一版又漏了收尾的 `}}` → `single '}' is not allowed`。**f-string 里字面花括号开合都要双写**
18. `environment.execute(cmd)` —— 参数叫 `env`，模块里没有 `environment` 这个名字 → NameError（语法错挡着，ruff 还没报到 F821）
19. 退出码常量起名 `_EXIT_IS_PATH` → 改 `_EXIT_IS_DIR`：所有东西都是 path，名字要说出分派依据

**不报错只是全错（3 个）** —— 都是 awk 程序没被同一对单引号包住

20. 漏写 `END {print NR > "/dev/stderr"}` → 拿不到总行数，第 5 步的空文件、越界、「共 N 行」全无依据
21. `END {...}` 放在**路径之后**、引号之外（容器实测）：awk 把 `END` 当第二个文件名 → exit 2、stdout 空；
    没被引号保护的 `>` 被 **bash** 当重定向，读到的行写进了新文件 **`/dev/stderr}`**（bash 去引号后 `}` 粘在文件名上）
22. `END {...}` 挪到**程序开引号之前**，仍在引号外（容器实测）：awk 把 `END` 当整个程序 → `syntax error at or near end of line`，exit 2；
    又留下文件 `/dev/stderr}NR >= s && NR <= e {print}`

最终版容器实测：`setup.py` offset=2 limit=3 → exit 0、stdout 第 2–4 行、stderr `'68\n'`；`nope.py` → 90；`astropy` → 91；`/dev` 无残留。

### 第 4 步代码 bug（09-15，1 版审稿）

分支顺序（超时最先）、归类、exit 0 放行都对。问题都不在判断逻辑：

23. 四处 `failure_category=FailureCategory.X` 后少逗号 → SyntaxError
24. 第 2 步的返回值改名为 `path_validate_result`，第 3 步仍写 `shlex.quote(result)` → NameError。**改名要搜全文件**
25. `timed_out == True` → 改为直接判真值（ruff E712）
26. （Claude 补文案时）next_actions 里用隐式字符串拼接跨两行 → ruff ISC004「是不是忘了逗号」；已加括号

### 第 5–7 步代码 bug（09-15）

第 5、6 步判断逻辑一次写对（空文件先于越界、`[:-1]` 切行、放入时记行号、`content and` 至少一行），只改了格式。

27. 第 7 步只写了「没读完」分支，**读到末尾时函数落空返回 `None`** —— ruff 查不出，`-> Observation` 标注在运行时不检查。
    验收脚本第一轮在 `setup.py` 60/20 和 fits 单行两条上抓到（`返回 Observation（实际 NoneType）`）。
    对策：验收脚本对每条用例都先查 `isinstance(obs, Observation)`；**有返回值的函数，每个 `if` 都问一句「不成立时去哪」**

### list_files 第 6 步代码 bug（09-15，本人版 4 版审稿）

| # | 版 | bug | 为什么没报错 / 怎么抓到 |
| --- | --- | --- | --- |
| 1 | `_aggregate` v1 | 标注写 `List[str]`，没 import → **整个模块 import 失败**（read_file 一起挂） | ruff F821；标注在 def 时求值 |
| 2 | v1 | `path.endwith("/")` 拼错 → `AttributeError` | ruff 不知道 `path` 是 str，**只有跑才暴露** |
| 3 | v1 | 每个文件只取最深一截 `parts[:take]`，中间层目录丢失（`a/ (4 files)` 不出现），违反 L3 | 不报错；手写 7 个文件的列表跑一次才看出少行 |
| 4 | v1 | 目录行用 `{path!r}` 带引号，模型照抄进工具即 `PATH_NOT_FOUND`，违反 L7 | 不报错；`!r` 适合报错里显示收到的值，不适合给模型复制的输出 |
| 5 | v2 | 漏 `return result` → 返回 `None` | ruff 不报；调用方 `"\n".join(None)` 才会炸 |
| 6 | 循环 v1 | 条件写成 `depth * len(...)`（照抄小例子 `size * len(text)`）→ django depth=2 的 8303 字符被判超预算，降到 1 | astropy 2×2965 仍在预算内，**小仓库测不出** |
| 7 | 循环 v1 | `depth -= 1` 改掉参数，第 7 步拿不到请求值 | 不报错；summary「请求 N 实际 M」写不出 |
| 8 | 循环 v2 | `used_depth = depth - 1` 每轮从请求值重算 + 条件仍判 `depth > 1` → **死循环**（django 请求 4：4→3→3→3…） | 请求 3 时降一次就装下，**没有「要降两次」的用例** |
| 9 | 循环 v3 | 条件仍判 `depth > 1`（`used_depth` 已正确递减）→ depth=1 仍超预算时降到 **0**，`_aggregate` 返回 `[]`，模型收到空目录 | 不报错不卡住；三仓库单目录直接子项最多 281，**只有假 exec 平铺 1500 个文件才触发** |

### search_code 验收抓到的错（09-15，Claude 版）

1. **设计错：只用 `--untracked`**。第一版为了让 agent 新建的文件可见，所有 grep 都带 `--untracked`，结果漏掉已跟踪却匹配 `.gitignore` 的源码
   （astropy `tokenizer.c` 170 条）。发现方式：验收 R6 断言写死了探针里的总数 33,895，工具给 33,722；逐文件 diff 定位到 2 个文件，
   再逐个开关二分到 `--untracked`。→ S14。**教训：探针脚本与工具的参数不一致时，数字对不上不是「环境差异」，要追到底**
2. **解析崩溃**：第一版 `_parse_grep_lines` 按 `\0` 个数分命中 / 上下文（4 段 / 3 段），FITS 数据文件的行文本自带 NUL，
   `int('')` 抛 `ValueError` 冲出工具。→ S15，改用 `path\0行号\0(列号\0)?文本` 正则，碎片跳过
3. **验收用例选错路径**：R10 想测压缩 JS 的长行截断，给的是目录 `astropy/extern/jquery`，前 20 条命中全在未压缩文件里，断言失败；
   改为直接指向 `jquery-3.1.1.min.js`。不是工具 bug

### 09-16 三个工具写完后抓到的错（5 条）

| # | 错法 | 怎么露出来的 | 改法 |
| --- | --- | --- | --- |
| 1 | **`git_diff` 把两条命令串成 `a; b`，还在 b 上挂了管道** —— 整条的退出码是 `sed` 的，`git diff --stat` 失败（不在 git 仓库、坏索引）会被吞掉，工具静默返回「没有改动」 | 写 §七 那张义务表时，为了给「有管道但无害」辩护，去逐条核对左端会不会失败，才发现**根本不是左端的问题，是 `a; b` 让 a 的退出码丢了** | 拆成两条独立 `execute`，各自判退出码；未跟踪清单改用 `ls-files -z` 在宿主机加前缀，管道去掉。补了 `test_git_diff_does_not_let_a_pipe_swallow_the_exit_code`，断言命令里没有 `\|` |
| 2 | `_keep_tail(text, 0)` 返回**整串** | 写测试时想起 `observation._truncate` 的 `half=0` 特判（§五早有记录），回头查同一个坑 | `text[-limit:] if limit else ""`，并加 `ValueError` 拦负数。**同一个 `text[-0:]` 的坑第二次踩** |
| 3 | `run_tests` 的 `target` 一开始有默认值，空 target 就跑实例自己的评分目标 | 写 `derive_test_command` 时才意识到：这等于把 grader 用哪些测试文件告诉自己的 Agent，而 mini baseline 没有 —— **不是 bug，是方法论错误，会让两边数字不可比** | `target` 改成必填；前缀里的评分目标一律剔除，75 条全部断言过（T8、R2） |
| 4 | `graded_test_files` 只取 `diff --git a/X` 一侧 | 在全部 75 条上跑前缀提取，发现 `astropy__astropy-7336` 还剩一个目标没剔掉 | 取 `a/` 和 `b/` 两侧：该条的测试补丁把 `py3_test_quantity_annotations.py` **改名**成评分目标，只看 a 侧看不到新名字 |
| 5 | `agent/run.py` 里有个 `test_patch_files`，pytest 把它当测试用例收集，报 `fixture 'test_patch' not found` | 跑全套测试时出现一条 ERROR | 改名 `graded_test_files`。**生产代码里的函数不要以 `test_` 开头** |

### 教训（6 条）

1. **恒真/恒假条件累计第 4、5 次**（接 `DESIGN-environment.md` 第 7 条）。对策：**每个守卫都要用合法输入测一次**，不只测它该拦的
2. **取反别手写。** 先正着写 `inside = ...`，再 `if not inside:`，让 Python 替你做德摩根
3. **F541 和 F841 是同一个信号**：lint 指出的「多余」说明你本来想做别的事 —— 本来想插值、本来想用这个变量
4. **语法错时 ruff 只报第一处**（第 4 版的 `instance(` 就是修掉语法错才露出来的）
5. **拼 shell 命令，核对的是渲染后的字符串，不是 Python 源码**（第 21、22 条）。源码里引号开合分在两行就看不出配对；
   对策：一段 shell 程序（awk 脚本）写在同一行 f-string 里，冒烟时把真正发出的 `cmd` 打印出来看一眼
6. **循环要测「转 0 次 / 1 次 / 2 次以上 / 转到下限还不满足」四种**（list_files bug 6–9）。只测「转 1 次就满足」，
   死循环和降到 0 都藏得住；循环变量要同时出现在条件、递减、调用三处 —— 三处名字不一致就是信号

## 六、实测数据（2026-09-14/15，WSL `.venv` Python 3.12.3；上半 shell 在 WSL 宿主机，下半进 astropy-12907 容器）

| 事实 | 值 | 用在哪 |
| --- | --- | --- |
| `str.splitlines()` | 还按 `\x0c`、` ` 等切 → 行号和 `git grep -n` 对不上 | 第 5 步切行用 `split("\n")`，注意末尾多一个 `''` |
| `wc -l` | `'a\nb'` → 1（末行无 `\n` 不计） | 与 09-08 结论一致，数行不用 `wc -l` |
| `cat` 不存在 / 是目录 | 两者 **exit 1**，只有 stderr 文本不同 | D4 → 前置 `test` 守卫 |
| 名为 `-n` 的文件 | `cat -n` 把它当选项；`shlex.quote('-n')` 原样返回 `-n` | quote 防注入不防选项；路径先归一化成 `/testbed/...` 绝对路径即自动规避 |
| `posixpath.join('/testbed', '/etc/passwd')` | `'/etc/passwd'`（第二参数绝对则丢前缀） | 决定 10 |
| `normpath` | `''` → `'.'`；`'/testbed/'` → `'/testbed'`；`'//testbed/a'` 保留两个斜杠，三个及以上才合并 | 决定 10；`//testbed/x` 会被误拒（只误拒不误放） |
| `subprocess` 参数含 `\x00` | `ValueError: embedded null byte`，启动前就抛 | 决定 9 |
| 类型标注 | 运行时不检查：`f("3", None)` 照收；`lines[True:2]` → `['L2']` 静默通过 | 决定 5 |
| `:=` 优先级 | `if err := f() is not None` 绑定的是 bool；要写 `(err := f()) is not None` | read_file 的校验循环 |
| 行号前缀 | `f"{n:>6}\t{line}\n"` 占 8 字符（30 字符的行渲染后 38） | 决定 4 的预算要把前缀算进去 |
| `match` 里的裸名字 | `case _EXIT_NOT_FOUND:` 是**捕获**：传 91 也命中，且把常量名重新绑定成 91；后面还有 case 时 → `SyntaxError: name capture ... makes remaining patterns unreachable`；带点的名字（`ns.NOT_FOUND`）才是值比较 | 第 4 步用 `if/elif` 比较模块常量 |
| 切 awk 的 stdout | `s.split("\n")[:-1]`：`'b\nc\n'` → `['b','c']`、`''` → `[]`、`'x\r\n'` → `['x\r']`；`removesuffix("\n").split("\n")` 对 `''` 给 `['']`（空当成 1 行） | 第 5 步切行用 `[:-1]`，依据是 awk 每行都补 `\n` |
| 解析 stderr 的 NR | `int('68\n')` = 68（容忍首尾空白）；`int('')`、`int('awk: warn\n68\n')` → `ValueError` | 第 5 步：stderr 不是纯数字时不能让异常冲出工具 |
| **list_files：仓库规模**（09-15，三个镜像 `/testbed`） | django-15863 / astropy-12907 / sympy-22714：跟踪文件 **6649** / 1876 / 1960；被 ignore 12 / **64** / 7；根目录条数·字符 depth=1 30·345 / 31·392 / 33·396，**depth=2 300·5763** / 134·2299 / 152·2609，**depth=3 2136·61704** / 691·17818 / 763·19280；单目录直接子项最多 281（django `docs/releases/`）/ 71 / 47；`git ls-files` 0.020s / 0.003s / 0.003s；三者都没有 `tree`，有 git 2.34.1、GNU find 4.8.0 | L1、L2、L4 |
| **list_files：命令层**（09-15，astropy-12907 容器） | 绝对路径 pathspec `-- /testbed/astropy/io/fits` 输出**相对仓库根**（`astropy/io/fits/card.py`）；`é.py` 默认输出 `"astropy/\303\251.py"`，`-z` 原样；`-z` 输出以 `\0` 结尾（`setup.py\0`）→ `split("\0")[:-1]`；pathspec `[x]` 默认匹配到同级文件 `x`，加 `--literal-pathspecs` 后只剩 `[x]/a.py`；被 ignore 的 `astropy.egg-info` → 空输出 exit 0；新建未跟踪文件可见、`rm` 掉的已跟踪文件仍列出；守卫：文件 → 92、不存在 → 90、目录 → 0 | L4、L5、L9，已知边界 |
| 降深度轨迹（`_aggregate` 包一层记录每次调用） | django 根目录渲染字符数：depth 4 → 132151、3 → 66922、2 → **8303**、1 → 426；astropy 4 → 48320、3 → 19472、2 → 2965、1 → 481。请求 4 走 4→3→2 停；平铺 1500 个文件请求 2 走 2→1 后截条目 | L2 |
| **`list_files` 最终验收**（09-15，21 项全过；astropy-12907 + django-15863 + 假 exec） | `_aggregate` 纯函数 2 项；平铺 1500 文件 → 保留 588 条、content 9995 ≤ 10000、summary 写明降深度与省略 912 条；astropy 根目录默认 134 条、depth=3 降为 2；`astropy/io` 81 条全带前缀，尾斜杠结果相同；**输出的文件行原样传给 `read_file`、目录行去掉计数后传给 `list_files` 都成功**；只有文件的目录 next_actions 为空；新建未跟踪文件、`é.py` 原样、`[x]` 只匹配字面；`setup.py` / `nope` / `../etc` 三种错归类正确；被 ignore 的目录 ok 空；django 请求 4/3/2/1 → 2/2/2/1，content 均 ≤ 10000；`ruff check agent/` 全过 | 本模块验收 |
| **search_code：退出码与方言**（09-15，astropy-12907 + django-15863，git 2.34.1，`LC_CTYPE=POSIX`） | 命中 0 · 没命中 1 · pattern 语法错 128（stderr `fatal: -e option, 'foo(': Unmatched ( or \(`，PCRE 为 `missing closing parenthesis`）· pathspec 不存在 1 且无 stderr · `--max-count` 129 `unknown option`。astropy 匹配行数 BRE / ERE / PCRE / 字面量：`def __init__(` 547 / **128** / **128** / 547；`def __init__\(` **128** / 547 / 547 / 0；`\d+` 259 / **275,601** / 237,399 / 52；`foo\|bar` 0 / 1,637 / 1,637 / 0；`\bclass\b` 5,600 / 5,600 / 5,600 / 0。`-P` 可用，`(?i)` 可用，`(*NO_UTF)` 不认；`self` 耗时 BRE 35ms、PCRE 33ms、`-F` 36ms（django 122 / 135 / 132） | S1、S4、S7、S8 |
| **search_code：输出格式** | `-n -C1`：命中 `path:75:文本`、上下文 `path-74-文本`、段间 `--`（跨文件也是 `--`）；**`-z` 后两者都成 `path\0行号\0文本`**；加 `--column` 后命中行为 `path\0行号\0列号\0文本`，上下文不变；`-c -z` 为 `path\0计数\n`；文件名 `a:1:b.py` 不加 `-z` 时输出 `zzq/a:1:b.py:1:QTOKEN`；`é.py` 不加 `-z` 转义为 `"zzq/\303\251.py"`；`-e` 以外传 `--version` → `unknown option` | S5、S6、S10 |
| **search_code：规模** | astropy `import` / `self` / `def ` / `e` 匹配行 9,005 / 33,895 / 18,140 / 451,650，`-C2` stdout 1.5MB / 7.2MB / 6.0MB / 53.5MB，45–85ms；django 13,494 / 93,145 / 28,405 / 566,844，`-C2` stdout 2.1MB / 19.5MB / 9.7MB / 74.2MB，131–225ms；`Unit` 平均每命中 `-C2` 442 字符（astropy）、`import` 155 字符（django） | S3、S4 |
| **search_code：可见性与二进制** | 新建未跟踪文件：默认不可见，`--untracked` 可见；被 ignore 的 `.pyc` 在 `--untracked` 下仍不可见；工作区改动可见（搜的是工作区不是 index）；**`--untracked` 跳过已跟踪但被 ignore 的文件**：astropy `git ls-files -ci --exclude-standard` 7 个，`self` 总数 33,722 vs 33,895，django 0 个；`--no-index` 对点名的已 ignore 文件照搜；`-I` 下 FITS 仍被当文本（`chandra_time.fits` 31,680 字节含 2,788 个 NUL；【判断】NUL 都在 git 检测的前 8000 字节之后） | S5、S14、S15 |
| **`search_code` 最终验收**（09-15，51 项全过；纯函数 + 假 env + astropy + django） | 纯函数 10 项（计数去重、NUL 与碎片、max_results=1 丢弃下一段前文、分隔符、context=0 双文件、预算截至少 1 条、5 万字符单行截到 < 700）；假 env 5 项（两遍各自超时 / 意外退出码、pattern 含单引号与 `; rm -rf /` 正确 quote）；参数错 9 项 + 不发命令；真容器：总数等于 `git grep -P -c` 原生计数、**每条显示的命中行与上下文行逐行等于 `read_file` 读到的内容**（R1b R6b R8c R11b）、`def __init__(` 报 128 带 PCRE 原因而 `fixed_string` 得 547、没命中 ok、文件路径 ok、`self` 截到 20 条并列文件分布、`import` + `max_results=1000` + `context=10` 预算截且说明调大无用、未跟踪与怪文件名原样且可喂 `read_file`、`--version` 与 `it's`、压缩 JS 长行截断、`tokenizer.c` 170 条、全仓 33,895；django `e` / `self` / `import` 0.95 / 0.45 / 0.47s 均 ≤ 10000 字符，`e` + `max_results=100000` 0.81s 预算截；`ruff check agent/` 全过 | 本模块验收 |
| **以下进容器实测**（09-15，astropy-12907 镜像） | | |
| `test` 守卫 | 不存在 → exit **90**、目录 → exit **91**，stdout 均为空 | 决定 14 |
| awk `NR`（s=2, e=3） | `'a\nb\nc'` → stdout `'b\nc\n'`、NR=3；`'a\nb\n'` → NR=2；空文件 → stdout `''`、NR=0；`setup.py` NR=68 | 决定 13、15 |
| awk 输出结尾 | 每行都补 `\n`，无结尾换行的文件也一样 | 第 5 步切行统一去掉末尾一个 `''` |
| `cat` + `split("\n")` | `'a\nb\n'` → `['a','b','']`；空文件 → `['']` | 决定 13 否决理由 |
| 容器里的 awk | `/usr/bin/mawk` 1.3.4；`'a\0b'` 的 `length` = 3，NUL 不截断 | 决定 13 |
| `shlex.quote` | `"/tmp/a b'c.py"` → `'/tmp/a b'"'"'c.py'`，cat/awk 都读对 | 义务「拼参数用 `shlex.quote`」 |
| awk 加 `NR>e {exit}` 提前退出 | `seq 1 10` 取 2–4：stdout 不变，`END` 里 NR 变成 **5**（不是 10） | 决定 13「不加提前 exit」 |
| 3.4MB 文件取 1–200 行 | awk：stdout 29,916 字符、NR=21919、0.043s；`cat`：3,418,080 字符、0.046s | 两者耗时相当，差别在传回的体积 |
| astropy 单行超预算 | 排除 `.git` `.so` `.pyc`：行长 > 2000 共 130 行；**> 9992（10000 − 行号前缀 8）共 39 行，其中 `.py` 0 行**；最长 83,520（`wcs/tests/data/j94f05bgq_flt.fits` 第 1 行），其余是 `.fits` / `.hdr` / `jquery-3.1.1.min.js` | 决定 4 的洞：真实存在，但只落在数据文件和压缩 JS 上 |
| 第 6 步三种停法（`sys.settrace` 抓局部变量，不改代码） | `setup.py` 60/20 → last=68=total，312 字符；`convolution/tests/test_convolve.py` 默认 → last=200、total=1017、8916 字符（limit 截）；`timeseries/periodograms/bls/tests/test_bls.py` 默认 → **last=153**、total=826、**9995** 字符（预算截）；`j94f05bgq_flt.fits` → last=1=total、83528 字符（单行，交给 render） | 决定 4、19；三种停法在第 7 步归一为「`last + 1 ≤ total` 即未读完」 |
| `break` 后的循环变量 | 停在**被拒的那一行**（`enumerate(..., start=10)` 在第 2 个元素 break → 11）；不 break 则是最后一个元素；空列表则未绑定（NameError） | 第 6 步在放进去的那一刻单独记 `last_line_number`，不用循环变量 |
| astropy 最大的非 .git 文件 | `iers/data/eopc04_IAU2000.62-now` 3,418,080 B；`_wcs…so` 1,666,096 B；`cparser.c` 1,351,496 B | 决定 13 |
| **`read_file` 最终验收**（09-15，16 项全过） | 内容：`setup.py` 60–68、`test_bls.py` 154–287 与 `sed -n` 逐行相同；续读：第一次止于 153、照 next_actions 续读始于 154，不重不漏；limit 截给 `offset=201`；预算截 content 9995 / 9994 ≤ 10000；读到末尾不给续读；fits 单行 render 总长 10237（`_truncate` 截）；空文件 ok；不存在 / 是目录 / 越界归类正确；`ruff check agent/` 全过 | 本模块验收 |
| **以下 09-16 实测** | | |
| **apply_patch：gold patch 的表达力**（dev 子集 25 条，`tests/gold_replay.py`） | 25 条 gold patch 共 **66 个 hunk**，拆成 `(old_string, new_string)` 后**66/66 一次打上，0 个 `ANCHOR_AMBIGUOUS`、0 个 `ANCHOR_NOT_FOUND`**；改 1 个文件的 19 条、2 个 3 条、3 个 1 条、4 个 2 条；**新建文件的 0 条** | P1、P2、P3 |
| **apply_patch：权限位**（astropy-12907 容器） | `astropy/table/operations.py` 原 mode **100755**；`head -c`/`tail -c` 切片后 `cat tmp > path` 回写，`stat -c %a` 前后相同，`git diff` 的 index 行仍是 `100755` | P5（`mv` 会变成 100644） |
| **apply_patch：只差空白的报法** | `'def  _join('`（两个空格）→ 压掉空白后匹配 1 处，报「once whitespace is ignored」并给**匹配所在行 1058**；同一输入若只走 `_closest_lines`，给的是不相干的第 170 行 `def join_func(sc1, sc2):` | P7 —— 这条是改进前后对比，不是假设 |
| **apply_patch：不唯一** | `'    return'` 在 `operations.py` 出现 **27 次**，报前 20 处行号 + 该行内容，文件未被改动（随后 `git_diff` 为空） | P2、P15 |
| **run_tests：运行器前缀**（subset 25 + holdout 50 = 75 条） | 只有 **5 种**前缀：`./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1`（27）· `pytest -rA`（19）· `PYTHONWARNINGS=ignore::UserWarning,ignore::SyntaxWarning bin/test -C --verbose`（14）· `tox --current-env -epy39 -v --`（12）· `pytest -rA -vv -o console_output_style=classic`（3）。**75/75 都能从 `eval_script` 抽出前缀且把评分目标剔干净**（`tests/test_run.py::test_no_graded_test_target_survives_in_any_prefix`） | T1、T8 |
| **run_tests：三条真实路径**（astropy-12907 容器） | ① 正常：`astropy/utils/tests/test_misc.py` → `All 7 test(s) passed (7 passed)`；② 把 `isiterable` 改成 `raise RuntimeError` 后重跑 → pytest 在 **conftest 收集阶段就崩**（exit 1，没有一条测试结果），归 `UNCLASSIFIED` 并把 traceback 原样给模型；③ 不存在的目标 → 同样 0 条结果 | T7 —— 两种原因输出形状一样，所以不能硬归 `INVALID_ARGUMENT` |
| **注入防护**（假 env） | `read_file('a.py; rm -rf /')` → 命令里是 `'/testbed/a.py; rm -rf /'`（整串在单引号内）；`run_tests('t.py; rm -rf /')` → `pytest -rA 't.py;' rm -rf /`，分号被引号包住，`rm` 成了 pytest 的普通参数 | T2；验收 4 的可执行版 |
| **端到端（gold 回放）** | 25 条实例、5 并发、**8.5 秒**跑完（每条 0.6–2.8s，纯工具链无模型）；产出的 `preds.json` 走官方 harness：**25/25 resolved，0 infra failure、0 ambiguous、0 empty patch**（`results/evaluation/gold-replay-s25/results.json`） | 整条链的正确性；接模型前的未知量只剩模型本身 |
| **测试套件规模** | 75 条假 env / 纯函数用例 **0.77s**；8 条真容器用例 **3.29s**（同一个容器 module 级复用） | §七 的「验收脚本没进仓库」到此关闭 |

## 七、已知边界与待办

- **软链接逃逸**：不处理，见 `DESIGN-environment.md` §七
- **`//testbed/x` 被误拒**：POSIX 保留开头恰好两个斜杠。只误拒不误放，且报错里有归一化后的路径，不处理
- **`environment.py` 的 `-w` 改用 `REPO_ROOT`**：✅ 09-15 进 astropy-12907 容器冒烟，`pwd` → `'/testbed\n'`，exit 0
- ✅ **验收脚本进仓库（09-16 完成）**：三层取舍（09-15 定）已落成 —— ① 纯函数直接喂列表测；
  ② 超时、意外退出码、平铺上千文件等真容器造不出或造起来贵的，用假 env（`tests/fake_env.py`）；
  ③ 其余走真容器（`tests/test_container_smoke.py`，打 `slow` marker，`pytest.ini` 里默认跳过）。
  否决：只用真容器（超时 / exit 128 触发不了）· 只用假 exec（`-z`、`--literal-pathspecs`、`test` 守卫这类命令层事实测不到）。
  **代价**：09-14/15 那两份会话临时脚本（read_file 16 项、list_files 21 项、search_code 51 项）**没有逐条搬进来**，
  §六的记录是它们唯一的痕迹；新套件是按四条验收重写的，覆盖的边界不完全一样。
- **apply_patch 的写回不是原子的**：`cat tmp > path` 中途失败会留下截断的文件。已在 `IO_ERROR` 的 next_actions 里
  要求模型先 `read_file` 查看当前状态（P11），但没有回滚。做回滚要先备份整个文件，和 P5「整文件不出容器」冲突，不做
- **`run_tests` 白拿了运行器知识**：见 §四 T8 下面那段。报告里要写明，不能装作两边条件一样

### `DESIGN-environment.md` §七 压在本模块的四条义务 —— 进度

| 义务 | 状态 |
| --- | --- |
| 每条错误路径有停止条件 | ✅ 09-16 六个工具全部 error 的 next_actions 都写明「什么情况下别再试」；`tests/test_tools.py` 用 20 条参数化用例逐条断言 |
| 拼参数用 `shlex.quote()` | ✅ 09-16 六个工具全覆盖：路径、pattern、第二遍的每个文件、`run_tests` 的每个目标、`apply_patch` 的 base64 串都 quote；整数参数由第 1 步保证是 int，不 quote |
| 告诉模型 `cd` 不持久 | ✅ 09-16 在 `loop.py` 的 system prompt 里落地：「There is no shell: if a tool cannot do it, it cannot be done」—— 比解释 `cd` 更彻底，模型根本没有发 shell 命令的途径 |
| 不用管道或 `set -o pipefail` | ✅ 09-16。唯一剩下的管道是 `apply_patch` 的 `printf %s '<b64>' \| base64 -d`：左端是常量串的内建命令，不会失败，右端的失败由 `\|\| exit 94` 接住。`run_tests` 的 `2>&1` 是重定向不是管道。**`git_diff` 第一版踩了这条**，见 §五 |
