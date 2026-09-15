# tools.py 设计档案

> **进行中**。`read_file` 第 1–2 步完成（参数校验 + 路径白名单），2026-09-15，未提交。
> 判断逻辑本人手写；Claude 给思路、跑实测、审代码。**例外**：09-15 的报错文案、docstring、类型标注、格式由 Claude 改（本人要求）。
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

12 个路径全部归类正确：3 个合法路径放行（`'./astropy/../setup.py'` → `'/testbed/setup.py'`），
`../etc/passwd` `/etc/passwd` `//etc/passwd` `/testbed2/x.py` `/testbedXYZ/../testbed_evil/a.py` 越界，
`''` `None` `123` `'a\x00b'` 参数错。`ruff check agent/` 全过。

### 悬置（第 3–6 步动手前定）

- ~~D3 / D4 / D5~~ 09-15 已定，见决定 13–15
- ~~决定 4 的洞~~ 09-15 已定，见决定 19。原记录：某一行本身超过预算时一行都放不下，kept=0，续读 offset 原地不动 → 模型打转、没有停止条件。
  两个方向：至少保留一行（交给 render 截），或单独截这一行并明说

## 四、待写工具的规格（尚未实现）

### list_files(path, depth)

要定：递归深度上限。django 递归到底是几万个文件，一次就能打满上下文。
建议：条数超上限时按目录聚合，不要截断 —— `tests/  (487 个文件)` 保留了「这里很多」这个信息，截断会丢掉。
它和 search_code 语义重叠，要能说出它存在的理由（用在「还不知道该搜什么关键词」的阶段）。

### search_code(pattern, path, context, max_results)

用 `git grep -n -C <context>`，不是 ripgrep（容器里没有）。要定三件事：

- **正则还是字面量**：模型写的正则经常错且难自查，考虑给个 literal 开关
- **上下文行数**：0 行会逼模型必然再跟一次 read_file。多一步 = 多一次 LLM 调用 = 多花钱 + 多一次出错机会
- **结果条数上限**：超了要告诉模型总共命中多少条，让它自己收窄查询

### apply_patch(...) —— 这一个决定影响 resolved 率超过其他五个加起来

三选一：

| | 方式 | 代价 |
| --- | --- | --- |
| (a) | unified diff | token 最省，但模型极易算错行号 -> git apply 失败。这是失败模式 1 的主要来源 |
| (b) | search / replace | 不依赖行号，鲁棒；要求 old_string 唯一，token 更贵 |
| (c) | 全文件重写 | 最鲁棒，但大文件 token 爆炸，且容易顺手改坏别处 -> 失败模式 3 |

建议 (b)。理由三条：

1. 它把「行号算错」这一整类失败消灭，而不是缓解
2. Aider 用的就是它，有公开工程实证可引用
3. 它的失败可精确分类（找不到 / 不唯一），两种都能给明确恢复指令，那正是归因表要的数据

错误契约（三条都要写）：

- **找不到**：给出最接近的三处（行号 + 内容），要求先 read_file 确认再重试
- **不唯一**：给出全部出现位置，要求扩大 old_string 使其唯一
- **连续失败**：同一文件失败 3 次 -> 停，别再改这个文件 ← 停止条件

### run_tests(target, timeout)

- **粒度**：支持指定测试文件/模块，不要只有「全跑」。django 全套一次几十秒，全跑会把时间和 token 都吃掉
- **截断**：只保留失败部分 + 统计行，通过的全丢。通过的测试对模型零信息量
- **超时**：必须有，死循环的测试会挂死整个 loop

### git_diff()

两个角色别混：

- **harness 提取答案**：在 loop 外面做，不占 Agent 步数
- **Agent 自查**：提交前看一眼自己改了什么

保留为 Agent 工具的理由是第二个角色有明确因果：它让模型发现「我改了不该改的文件」，直接减少失败模式 3（PASS_TO_PASS 挂）。

## 五、已纠正的错误

### 设计判断（Claude 的，2 条）

| 原判断 | 实际 | 结论 |
| --- | --- | --- |
| 09-14 把 D3（读法）、D4（不存在 vs 是目录）当作悬置，推荐「`cat` 全文 + Python 切片」、区分失败「只能看 stderr 或先 `test -f`」 | `DESIGN-environment.md` §五 09-08 已有结论：awk `NR` 数行正确；前置 `test` 守卫 + 自定义退出码（90+），不解析文本。Claude 没回查设计档案就出题 | 以 09-08 结论为准。补充：WSL 宿主机上 `cat` 对不存在和是目录**都是 exit 1**（09-08 记录的是 2，命令不同），同样说明退出码分不开 |
| 决定 4 起初表述成「limit 要不要设上限」 | 读了 `_truncate` 决定三才发现真正的问题是「超长内容由谁截」：render 丢中段，工具给的续读行号失效 | 改问法后选 (b) 按字符预算截停 |

### 代码 bug（5 版审稿，按类归）

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

### 教训（5 条）

1. **恒真/恒假条件累计第 4、5 次**（接 `DESIGN-environment.md` 第 7 条）。对策：**每个守卫都要用合法输入测一次**，不只测它该拦的
2. **取反别手写。** 先正着写 `inside = ...`，再 `if not inside:`，让 Python 替你做德摩根
3. **F541 和 F841 是同一个信号**：lint 指出的「多余」说明你本来想做别的事 —— 本来想插值、本来想用这个变量
4. **语法错时 ruff 只报第一处**（第 4 版的 `instance(` 就是修掉语法错才露出来的）
5. **拼 shell 命令，核对的是渲染后的字符串，不是 Python 源码**（第 21、22 条）。源码里引号开合分在两行就看不出配对；
   对策：一段 shell 程序（awk 脚本）写在同一行 f-string 里，冒烟时把真正发出的 `cmd` 打印出来看一眼

## 六、实测数据（2026-09-14/15，WSL `.venv` Python 3.12.3；shell 部分在 WSL 宿主机，**未进容器**）

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
| **`read_file` 最终验收**（09-15，16 项全过） | 内容：`setup.py` 60–68、`test_bls.py` 154–287 与 `sed -n` 逐行相同；续读：第一次止于 153、照 next_actions 续读始于 154，不重不漏；limit 截给 `offset=201`；预算截 content 9995 / 9994 ≤ 10000；读到末尾不给续读；fits 单行 render 总长 10237（`_truncate` 截）；空文件 ok；不存在 / 是目录 / 越界归类正确；`ruff check agent/` 全过 | 本模块验收 |
| astropy 最大的非 .git 文件 | `iers/data/eopc04_IAU2000.62-now` 3,418,080 B；`_wcs…so` 1,666,096 B；`cparser.c` 1,351,496 B | 决定 13 |

## 七、已知边界与待办

- **软链接逃逸**：不处理，见 `DESIGN-environment.md` §七
- **`//testbed/x` 被误拒**：POSIX 保留开头恰好两个斜杠。只误拒不误放，且报错里有归一化后的路径，不处理
- ~~`environment.py` 的 `-w` 改用 `REPO_ROOT`~~：09-15 进 astropy-12907 容器冒烟，`pwd` → `'/testbed\n'`，exit 0

### `DESIGN-environment.md` §七 压在本模块的四条义务 —— 进度

| 义务 | 状态 |
| --- | --- |
| 每条错误路径有停止条件 | ✅ 09-15 `read_file` 全部 error 的 next_actions 都写明「什么情况下别再试」；另外 3 个工具随写随补 |
| 拼参数用 `shlex.quote()` | ✅ 09-15 第 3 步：路径 quote；`offset`/`end` 已由第 1 步保证是 int，不 quote |
| 告诉模型 `cd` 不持久 | ⬜ 属于 system prompt，写 `loop.py` 时落地 |
| 不用管道或 `set -o pipefail` | ✅ 09-15 第 3 步：命令里没有管道，三段用 `;` 连接 |
