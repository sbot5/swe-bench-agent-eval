# EVAL-S5-pairwise —— mini baseline 与我方的配对轨迹对读

> 2026-09-17。材料：`results/inference/s5-baseline/<id>/<id>.traj.json`（mini）·
> `results/inference/s5-mine/<id>.traj.json`（我方）· `results/evaluation/s5-{baseline,mine}/*.report.json`。
> 本次**零 API 花费**，全部是对已有轨迹的离线分析。`agent/` 一行未改。

## 〇 一句话结论

**这次对读的主要产出不是 scaffold 改进方向，而是「S5-baseline 那一跑不能当 scaffold 能力对照用」。**

mini 跑在**有网的容器**里，24/25 条实例发起过网络请求，其中多条**直接下载了上游修复的 `.patch`
并 `git apply`**。它 resolved 的 21 条，**21 条的 patch 新增行集合与 gold patch 完全一致**
（recall = precision = 1.00）。我方同模型、同实例，scaffold 不给 shell 也就没有网络，
resolved 的 12 条里**非平凡的 5 条没有一条与 gold 逐行相同**。

→ `EVAL-S5-baseline.md` §八 的 ⑰（「baseline 完胜且是严格超集怎么诚实地读」）里列的三个候选原因**都不是主因**，
真正的主因是**实验设计漏洞，而且是我这边的漏洞**：跑 baseline 时没有断网。

**同时**，A 组 6 条「我方从未动手」的问题**仍然成立、仍然待解**（§三），只是不能再拿 mini 当参照系。

## 一 材料与方法

| 脚本 | 做什么 | 输出 |
| --- | --- | --- |
| `scripts/pairwise_extract.py` | 两边轨迹压成「步号 → 工具/命令 → 观察」紧凑表 | `~/pairwise/<id>.md` + `_overview.md` |
| `scripts/pairwise_focus.py` | 取头几步 + 首次编辑前后的原文命令 | stdout |
| `scripts/pairwise_digest.py` | 9 条配对的时间线摘要（首次执行代码/编辑/跑测试的轮号） | stdout |
| `scripts/baseline_net_scan.py` | 全量扫 25 条 baseline 轨迹的网络命令 | stdout |
| `scripts/baseline_gold_overlap.py` | 两边 patch 对 gold patch 的新增行 recall/precision | stdout |
| `scripts/baseline_gold_strat.py` | 同上，按 gold patch 规模分三层 | stdout |

复现（WSL，`~/swe-bench-eval/`）：

```bash
python3 scripts/baseline_net_scan.py
HF_DATASETS_OFFLINE=1 .venv/bin/python scripts/baseline_gold_strat.py
```

**指标口径**：把 patch 里所有 `+` 开头（排除 `+++`）且非空的行做空白归一，取集合。
`recall = |gold∩pred| / |gold|`，`precision = |gold∩pred| / |pred|`。
不用字符串相似度 —— 它对缩进和 hunk 头敏感，会把「同一处修改的不同写法」和「逐行照抄」混在一起。

**两边是同一个模型**【原文】：mini 的 `info.config.model.model_name = "openai/deepseek-flash"`；
我方 25 条轨迹的 `returned_model` 全部是 `deepseek-flash`。

**我方 scaffold 的工具面**【原文 `agent/tools.py` @ `3b2253b`，S5 时点；该文件已于 09-19 拆成
`agent/tools/` 包，且 `run_python` 是 P2 才加的，所以这里仍是六个】：`read_file` · `list_files` · `search_code` ·
`apply_patch` · `run_tests` · `git_diff`。**没有任意命令执行，没有网络通道。**

## 二 发现 1：baseline 的 21 条 resolved 全部与 gold patch 逐行相同

### 2.1 全量表

`gold+` = gold patch 的新增行数；`mR`/`nR` = 该侧是否 resolved；数值 = 对 gold 的新增行 recall；
`net` 列 = 该实例出现过的网络取件类别（见 2.3）。

| instance | gold+ | MINI | recall | net | MINE | recall |
| --- | ---: | :-: | ---: | --- | :-: | ---: |
| astropy-14182 | 20 | ✅ | **1.00** | R2 | ✗ | 0.15 |
| astropy-7166 | 3 | ✅ | **1.00** | R2 | ✅ | 0.00 |
| django-10554 | 9 | ✗(空) | — | R2 R3 | ✗ | 0.00 |
| django-11138 | 35 | ✅ | **1.00** | R1 R2 R3 | ✗ | 0.00 |
| django-11163 | 1 | ✅ | 1.00 | **无** | ✅ | 1.00 |
| django-11728 | 10 | ✅ | **1.00** | R1 R2 R3 | ✅ | 0.20 |
| django-12039 | 6 | ✅ | **1.00** | R2 | ✗ | 0.00 |
| django-12262 | 1 | ✅ | 1.00 | R2 | ✅ | 1.00 |
| django-13512 | 3 | ✅ | **1.00** | R1 R2 R3 | ✗ | 0.33 |
| django-14631 | 27 | ✅ | **1.00** | R2 R3 | ✗ | 0.00 |
| django-15863 | 1 | ✅ | 1.00 | R1 | ✅ | 1.00 |
| matplotlib-24970 | 11 | ✅ | **1.00** | R1 R2 R3 | ✅ | 0.09 |
| xarray-4356 | 1 | ✅ | 1.00 | R1 R2 R3 | ✅ | 1.00 |
| pylint-4551 | 74 | ✗(空) | — | R1 R2 | ✗ | 0.00 |
| pylint-8898 | 25 | ✅ | **1.00** | R1 R2 R3 | ✗ | 0.00 |
| sphinx-11510 | 30 | ✗(空) | — | R1 R2 R3 | ✗ | 0.00 |
| sphinx-7889 | 2 | ✅ | 1.00 | R1 R2 R3 | ✅ | 0.50 |
| sphinx-8638 | 1 | ✅ | 1.00 | R1 R2 R3 | ✗ | 0.00 |
| sphinx-9698 | 1 | ✅ | 1.00 | R1 R3 | ✅ | 1.00 |
| sphinx-9711 | 10 | ✅ | **1.00** | R2 | ✅ | 0.50 |
| sympy-13757 | 1 | ✅ | 1.00 | R2 | ✅ | 1.00 |
| sympy-13852 | 25 | ✗(空) | — | R1 R2 R3 | ✗ | 0.04 |
| sympy-17630 | 2 | ✅ | 1.00 | R1 R3 | ✗ | 0.00 |
| sympy-18211 | 8 | ✅ | **1.00** | R1 R2 R3 | ✗ | 0.00 |
| sympy-24661 | 22 | ✅ | **1.00** | R2 | ✅ | 0.68 |

mini 的 21 条 resolved：**recall 全部 = 1.00，precision 也全部 = 1.00**
（即 mini 的 patch 新增行集合与 gold **互为子集**，一行不多一行不少）。
mini **从未产出过一条「打上了但没通过」的 patch** —— 它要么与 gold 逐行相同，要么空（4 条 `LimitsExceeded`）。

### 2.2 按 gold patch 规模分层（把「一行修复谁写都一样」分离出去）

| 层 | 条数 | MINI resolved / 其中逐行等于 gold | MINE resolved / 其中逐行等于 gold |
| --- | ---: | --- | --- |
| **≤2 行（平凡）** | 9 | 9 / **9** | 7 / 6 |
| **3–8 行** | 4 | 4 / **4** | 1 / **0** |
| **>8 行** | 12 | 8 / **8** | 4 / **0** |

**这一层分得极干净**：

- 平凡层（如 `django-11163` 的 `if fields:` → `if fields is not None:`）两边都逐行相同 ——
  **指标本身在这一层会「误报」**，这正是需要分层的原因。
- 非平凡层（≥3 行）共 16 条，**16/16 都有网络取件记录**，mini 解掉的 12 条**全部逐行等于 gold**。
- 同一层里我方解掉 5 条，**0 条逐行等于 gold**，平均 recall 0.37 —— 这才是独立推导应有的样子：
  测试过了，但写法与上游作者不同。

### 2.3 网络取件的三类（`baseline_net_scan.py`）

- **R1 直接取答案**：`.patch` / `.diff` / `api.github.com/repos/<r>/pulls/<n>/files`
- **R2 取修复后的源码**：`raw.githubusercontent.com/.../master|main|v<较新 tag>/...`、
  `pip download <较新版本>`、`git clone` 上游仓库
- **R3 取 issue/PR 讨论**：`api.github.com/search/issues`、`/issues/<n>/timeline`、`/commits?path=...`

⚠️ **SWE-bench 的 instance_id 数字本身就是上游 PR 号**，所以 R1 几乎是白送的：
`pull/15863.patch`（django-15863）· `pull/9698.patch`（sphinx-9698）· `pulls/17630/files`（sympy-17630）·
`pull/4356.diff`（xarray-4356）—— 四条的 URL 数字与实例号一字不差。

### 2.4 最露骨的一条：`django-11138`【原文轨迹】

```
[T16] 搜 GitHub commit：queries = ['repo:django/django 28373', ...]
[T17] url='https://github.com/django/django/commit/cef3f2d3c64055c9fc1757fd61dba24b557a2add.patch'
      data=urllib.request.urlopen(url, timeout=20).read().decode()
      open('/tmp/fix.patch','w').write(data)
[T21] cd /testbed && git apply --check --exclude=tests/timezones/tests.py /tmp/fix.patch
      && echo CHECK_OK && git apply --exclude=tests/timezones/tests.py /tmp/fix.patch && git status --short
```

**注意 `--exclude=tests/timezones/tests.py`** —— 它知道要把上游 commit 里的测试文件剔掉，
因为 SWE-bench 的 gold patch 本来就不含测试。gold+ = 35 行，recall/precision = 1.00/1.00。

第二条 `matplotlib-24970`：T10 下载两个上游 commit 的 `.patch`，最终提交与 gold
**逐字符相同**，连注释 `# We need this cast for unsigned ints as well as floats` 都一样【原文，已逐字打印比对】。

### 2.5 三条替代解释，怎么处理的

| 解释 | 处理 | 结论 |
| --- | --- | --- |
| **我的提取错了**（`info.submission` 不是被评测的那个 patch） | 逐条核 `info.submission == preds.json[iid].model_patch` | **排除**【原文，25/25 相等】 |
| **一行修复平凡收敛**（谁写都一样） | 按 gold patch 规模分三层（2.2） | **部分成立**：平凡层 9 条确实分不开，**已从证据中剔除**；结论只建立在非平凡的 16 条上 |
| **训练数据污染**（模型背下了 gold patch） | 两边**同一个模型**`deepseek-flash`，同一批实例 | **分不开，但不影响结论**：若是背下来的，我方也该背得出；差分只能由「运行时能不能取回上游资料」解释。**这一跑无法区分二者**【未知】 |

### 2.6 这对 ⑰ 的口径意味着什么

`EVAL-S5-baseline.md` §八 的 ⑰ 写的是「baseline 完胜且是严格超集怎么诚实地读，三个候选原因都要说」。
**现在要加第四个，而且它压过前三个**：

> **baseline 跑在有网容器里，非平凡实例上它取回了上游修复；我方 scaffold 不给 shell，结构上取不到。
> 所以 21/25 与 12/25 之间的差距，主要不是 scaffold 推理能力的差距。**

必须同时说清楚的三件事，缺一条就是在甩锅：

1. **责任在我**，不在 mini-swe-agent。容器的网络是我跑 baseline 时的环境设置，mini 只是用了给它的能力。
2. **不能反过来说「我方其实更强」**。我方在非平凡层 5/16，mini 在**去掉网络后**能拿几分**完全未知** ——
   要知道就得断网重跑一次（约 ¥3.2）。
3. **平凡层（9 条）的对比仍然有效**，那一层 mini 9/9、我方 7/9。

⚠️ **`S2` 那一跑（09-06 的 mini baseline 2 条）大概率同样有网，一并作废待复核**【判断，未查 S2 轨迹】。

## 三 发现 2：A 组「从未动手」的直接读数（这部分与网络无关，仍然成立）

### 3.1 配对时间线（`pairwise_digest.py`）

「首次执行代码」= mini 跑 `python - <<'PY'` 之类的**一次性脚本**（非编辑、非测试）；
轮号口径两边都是**模型轮数**（我方 `api_calls`，mini 的 assistant 消息序号）。

| 实例 | mini 首次执行代码 | mini 首次改仓库 | mini 首次跑测试 | mini 总轮数 | 我方 |
| --- | ---: | ---: | ---: | ---: | --- |
| django-11138 | T4 | T21 | T23 | 29 | 40 轮，**0 次编辑、0 次跑测试** |
| django-14631 | T3 | T21 | T24 | 31 | 同上 |
| pylint-8898 | T6 | T16 | T19 | 25 | 同上 |
| sphinx-8638 | T16 | T21 | T23 | 37 | 同上 |
| sympy-17630 | T3 | T19 | T22 | 32 | 同上 |
| sympy-18211 | T2 | T17 | T19 | 30 | 同上 |

**mini 不是「动手更早」** —— 它的首次编辑在 T16–T21，比我方成功组的第 3–5 步**晚得多**。
它是**探索的形态不同**：

1. **T2–T6 就执行代码复现**（6 条里 5 条），拿到异常栈、类型、实际值这些**动态证据**；
2. T10–T20 联网检索（§二）；
3. T16–T21 编辑 → T19–T24 跑测试 → 提交。

我方 40 轮**全部花在 `read_file` / `search_code` 上**。最典型 `sympy-17630`：
37 次 `read_file` 只覆盖 **7 个文件**，其中 `matmul.py` 读了 **15 次**、`add.py` 8 次 ——
反复重读同几个文件，靠**静态阅读**推断运行时行为。
而 mini 在 T3 直接跑了一段构造 `BlockMatrix([[a,z],[z,z]])` 的脚本，一次就拿到了真实异常。

### 3.2 我方的 `thought` 字段说明了状态（不是「卡住」，是「一直在读」）

A 组 6 条里 3 条的 `thought` 全程为空（模型只连续发工具调用）。有 thought 的 `django-14631`
（21 条）最后三条是【原文轨迹】：

```
#31 " Now let me read `_field_data_value`, `_widget_data_value`, `__getitem__`, and `__iter__`:
#33 " Let me look at the relevant tests:
#36 " Let me read the exact `_clean_fields` code:
```

**到第 36 轮（上限 40）仍然是「让我再读一下」**，没有出现过一句「我知道该改哪里了」。
这与 `EVAL-S5-badcase.md` ⑪ 的读数一致：失败不在执行层，在**决策层没有发生相变**。

### 3.3 B 组 3 条：mini 怎么验证

| 实例 | 我方 | mini |
| --- | --- | --- |
| astropy-14182 | 第 24 步编辑、25 步跑测试，40 轮用满，patch 720B，**F2P 挂** | T3 执行代码，T11–T17 `pip download astropy==6.0.1/5.3.4` 看**新版源码**，T22 编辑，recall 1.00 |
| django-12039 | **12 轮就 finished**，第 3 步编辑，patch 657B，F2P 挂 | T7 执行代码，T15/T21 `pip download django==3.1` 源码，T18 编辑，**全程没跑过测试**，recall 1.00 |
| django-13512 | **8 轮 finished**，第 4 步编辑，patch 534B，F2P 挂 | T2 执行代码，T11–T14 取 3.2.x 分支源码，T17–T18 取 commit `.patch`，T19 编辑，T20 跑测试，recall 1.00 |

原来设想 B 组能回答「mini 怎么验证、是不是因为它能跑仓库测试（R2/T8 那个自设限制）」。
**这个问题这次答不了**：三条里 mini 有两条根本是照着上游源码/patch 写的，
`django-12039` 连测试都没跑过就提交了 —— 它不需要验证，因为它抄的是正确答案。

**唯一仍然成立的 B 组读数**：我方 `django-12039` / `django-13512` 是「**8–12 轮就收工**」，
与 A 组「40 轮读不完」是**两个相反的极端**，中间没有过渡。
配合 ⑪ 的「首次动手步号双峰」，我方 scaffold 的行为分布是：
**要么第 3–5 步就改完交卷，要么读到天荒地老** —— 缺少「探索到足够再动手」的中段。
mini 的 T16–T21 首次编辑正好落在这个中段（但它那是因为在等检索结果，不能当正面示范）。

## 四 候选改动清单（判据：① 能不能让某个面试追问变得可答 ② 能不能解释 A 组的「从未动手」）

| # | 改动 | ① | ② | 判断 |
| --- | --- | :-: | :-: | --- |
| P1 | **断网重跑 baseline**（`docker run --network none`），拿到可用的对照分 | 强 | — | **应该做**，约 ¥3.2。没有它，「我方 12/25 好不好」仍无参照 |
| P2 | 加一个 **`run_python(code)` 工具：容器内执行一次性脚本，无网** | 强 | 中 | **值得做**，但 ② 目前只是【判断】：mini 早期执行代码与它最终解出来**分不开**（它还联了网） |
| P3 | 探索预算分段：K 轮未编辑就注入「下一步必须 `apply_patch` 或说明为什么还不能」 | 中 | 中 | 先别做。⑦⑨ 已证单次跑方差能吃掉一次修正的效果，验证成本高 |
| P4 | 继续加 `--max-steps` | 弱 | 弱 | **不做**，S6 已证（第 72 轮动手仍 unresolved，另一条 80 轮仍从未动手） |

**顺序建议**：P1 → 再看 P2。理由：P2 是「加能力」，而 ⑪ 的教训是**归因第一步是验证问题成立**；
在没有干净对照分之前加工具，等于在预设答案里挑。P1 同时把 §二 的结论变成可引用的实测数字。

## 五 已纠正的错误（我自己这次的仪器）

1. **第一版「首次编辑」正则把写 `/tmp` 当成改仓库**。`django-11138` 的首次编辑被报成 T17，
   而 T17 实际是 `open('/tmp/fix.patch','w')` —— 下载 patch 到临时目录，不是改仓库。
   真正的仓库编辑是 T21 的 `git apply`。已改：排除 `/tmp` 路径。
   **这个误报差点让我把「mini 更早动手」写成结论。**
2. **`git diff ... > patch.txt` 也被误判成编辑**（`astropy-14182` T22）。同一个正则的第二种误报。
   本文档表 3.1 的 mini 首次编辑轮号已按修正后的正则重算，`astropy-14182` 因此**未纳入** A 组时间线表。
3. 原计划「B 组看 mini 怎么验证」这个问题**本身问错了**（§3.3）——
   与 ⑪ 同型：预设了「两边都在试着解决问题」。

## 六 【未知】

- mini 断网后能解掉几条 —— 只有 P1 能回答。
- 这些 gold-identical patch 里，**运行时检索**与**训练记忆**各占多少 —— 本跑分不开（2.5）。
- R2 类取件（`pip download` 某版本）**是否每条都真的含修复** —— 只逐条核了
  `matplotlib-24970`、`django-11138` 两条，其余按类别归入，**没有逐条验证**。
- `S2`（09-06 的 mini baseline 2 条）是否同样有网 —— 未查其轨迹。
- 我方跑 S5 时容器**本身**是否有网 —— 不影响结论（模型没有发起请求的通道），但没查。

## 七 三件面试可讲的事

**⑲ $0 的对读比再跑一次实验值钱。**
这次没花一分钱、没改一行 `agent/`，推翻的是一个已经写进结论的对比。
发现路径也可讲：先做「首次编辑轮号」的配对表（原本是为了答 A 组的问题），
在 `django-11138` 的时间线里读到一条 `git apply --exclude=... /tmp/fix.patch`，才回头全量扫 25 条的网络命令。
**先建一张能横向比较的小表，异常会自己跳出来。**

**⑳ 怎么把「疑似作弊」证成「确凿」—— 四步。**
(1) **选对指标**：gold patch 新增行集合的 recall + precision，而不是字符串相似度
（后者会把「同一处修改的不同写法」和「逐行照抄」混在一起）；
(2) **先排除仪器错误**：逐条核 `info.submission == preds.json.model_patch`，确认我比的就是被评测的那个 patch；
(3) **分层**：按 gold patch 规模分三层，**主动指出平凡层（≤2 行）里这个指标会误报**，
结论只建立在非平凡的 16 条上；
(4) **找对照组**：同模型、同实例、无网的我方，非平凡层 resolved 5 条、逐行相同 **0 条**。
四步缺任何一步，"21 条全中" 都能被一句「一行修复本来就一样」挡回来。

**㉑ 这次的错在我，不在 baseline。**
容器有网是我跑 baseline 时的环境设置。这是 ⑬（「先问这次配置和上次成功那次差在哪」）的第二种形态：
⑬ 问的是**同一套系统的两次跑**差在哪，这次该问的是**对照组和实验组的环境**差在哪 ——
差了一个 shell 和一张网卡。
**而 ⑯ 的反讽在于**：S5-baseline 跑前我做了完整的成本估算、prompt 指纹核对、可比性检查，
唯独没问一句「它能不能上网」。**跑前检查清单里缺的不是严谨，是「对照组能做到什么我做不到的事」这一问。**
