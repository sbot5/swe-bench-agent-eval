# EVAL —— repair 闸的 N 怎么定（$0，只读已在库轨迹）

> 方案出处：Monash `Career/04-项目/13-工业scaffold调研.md` §五「落地顺序」第 1 步。
> 闸的形状【原文 `13-` §五】：**T（首次成功复现）之后累计 N 轮仍无 `apply_patch`
> → 从 tool schema 摘掉 `search_code` / `list_files` / `run_python`，保留 `read_file`
> + `apply_patch` + `run_tests` + `git_diff`，直到发生第一次 `apply_patch` 为止。**
>
> 本文只做 **$0 的第 1 步**：在已有轨迹上定 N，并量出误伤面。**`agent/` 一行未动。**
> 第 2 步（改 `loop.py`）与第 3 步（约 ¥5.8 的真跑）不在本文范围。

---

## 一 前置：待办② —— `classify()` 的 REPRO 白名单漏（本次已修）

**为什么必须先修**【原文 `13-` §五第 1 步】：「`classify()` 的 REPRO 白名单漏
（要求代码含 `import`）**会影响 T**，T 是本方案的触发器，不能带着已知漏上线。」

### 1.1 漏在哪

原 `TRIVIAL_PAT` 第一条【原文 `p2_groupa.py:123`，改动前】：

```python
r"^\s*import \w+\s*\n\s*print\(\w+\.(__version__|VERSION|get_version\(\)|__file__)"
```

配 `re.search(..., re.M)` —— **只要任意位置出现「`import x` 换行 `print(x.__version__)`」就判 TRIVIAL，
不看版本行后面还跑了什么**。而 `classify()` 的优先级是 `TRIVIAL > ARCH > BROWSE > REPRO`
【原文 `p2_groupa.py:104-105`】，TRIVIAL 一旦命中就返回，后面真正在跑被测代码的部分再也看不到。

⚠️ 这与 `EVAL-switch-point.md` §4.4 记的第一条**不是同一个触发路径**：
§4.4 抓到的是「纯内置语法、没有 import」落进 `UNCLASSIFIED`；
本次抓到的是「**有** import 且开头就是版本打印」被 TRIVIAL 抢走。
两者同属 §七第 2 条那个【未知】的影响面，而后者**从不进 `UNCLASSIFIED` 桶，所以上次没看见**
—— §七第 2 条预判的正是这一点【原文 `EVAL-switch-point.md:250-252`】。

### 1.2 反向探针：候选集怎么圈（`scripts/classify_audit.py`）

`T = find_t()` 要求三件事同时成立【原文 `switch_point.py:41-49`】：
`run_python` · 脚本层 exit 0 · `classify() == "REPRO"`。
→ **只有「轮号 < 当前 T」的漏判才可能让 T 偏晚**；T 不存在时全部轮都是候选；
exit 非 0 的轮怎么判都不影响 T（`find_t` 本来就跳过）。

候选集 = 轮号 < 当前 T（或 T 不存在）· 非 REPRO · exit ∈ {0, '?'}。
实算 `p2-mine` 23 条 / `p2-rerun` 15 条（改动前口径），**逐条读原文判**（㊽）：

| 类别 | 条数 | 逐条读完的结论 |
| --- | --- | --- |
| ARCH | 24 | **全部判对** —— `git log/show/describe/reflog/branch/tag`、`pip show/download`、`find /`、翻 pip 与 conda 缓存找另一个版本。没有一条在跑被测代码 |
| BROWSE | 2 | **全部判对** —— `grep -rn 6058 .`（搜上游 PR 号）· `print(open("ChangeLog").read())` |
| TRIVIAL | 11 | **3 条是真漏**（下表），8 条判对 |

其中 `p2-mine` `django-14631` 轮 15 判 TRIVIAL，与 `CLAUDE.md:68` 那条
「09-18 更正：轮 15 只是 `print(django.__version__)`，真正的复现在轮 22」**独立吻合**
—— 一个免费的正对照。

### 1.3 三条真漏（全部影响 T）

| 现场 | 版本行之后实际在干什么 | T（旧） | T（新） |
| --- | --- | --- | --- |
| `p2-mine` `pylint-4551` 轮 20 | `astroid.parse(src)` 构造类、查 `instance_attrs` | **None** | 20 |
| `p2-mine` `sympy-18211` 轮 1 | `Eq(n*cos(n)-3*sin(n),0).as_set()` + traceback | 4 | **1** |
| `p2-rerun` `pylint-4551` 轮 17 | `astroid.parse(code)` 查 `args.annotations` | 29 | **17** |

### 1.4 修法与新旧读数对照

**改法**【`p2_groupa.py`，本次】：把「版本探查」从**扫开头两行**改成**整段判定** ——
整段只有 `import` / `from` / 注释 / 版本属性打印，才算 TRIVIAL（`_version_probe_only()`）。
`TRIVIAL_PAT` 里的 `HELLO` 那条**保持原行为不动**：收严它会把 `print("HELLO")` 这类冒烟代码
推进 REPRO 兜底，等于换一个病。

**全量对拍**（`scripts/classify_diff.py`，从 git `b999dc4` 取旧版逐轮对比，六跑 816 轮）：

```
run_python 轮合计 816，判定变化 16 轮（2.0%）
   TRIVIAL → REPRO    9      TRIVIAL → ARCH     3
   TRIVIAL → BROWSE   2      REPRO   → TRIVIAL  2
T 发生变化的实例 4 条：
   p2-mine      pylint-4551    T  None → 20
   p2-mine      sympy-18211    T     4 → 1
   p2-rerun     pylint-4551    T    29 → 17
   a-reason-r2  django-10554   T    28 → None
```

16 条**全部开原文读过**，判对 14 条，另 2 条见 §1.5。第四条 T 变化是**反方向**的，
所以单独核了原文 —— `a-reason-r2` `django-10554` 轮 28【原文 traj】：

```python
import django
print("VERSION", django.VERSION)
print(django.get_version())
```

纯版本探查、什么都没跑。旧正则要求 `print(` 后**紧跟**标识符，被 `"VERSION",` 挡住
→ 落进兜底 REPRO → **旧的 T=28 是个假读数**，新判定让它正确地变成 None。

⚠️ **B 组的 T 一条都没变**（4 条变化全在 A 组，或 a-reason 跑的 A 组）
→ **待办② 不动 §三 里 N 的下界，只让闸在 A 组更早触发。**

**两份已发布文档要改的数**（本节即更正来源，两份文档各留更正框）：

| 文档 | 位置 | 旧 | 新 | 结论变没变 |
| --- | --- | --- | --- | --- |
| `EVAL-P2-groupA.md` | A 组 105 次 run_python 用途分布 | REPRO **34（32%）** | **36（34%）** | 不变；ARCH 39(37%)、BROWSE 26(25%) **一个数都没动** |
| `EVAL-switch-point.md` | §3.1 `p2-mine` A 组 | `4/7 = 57%` NO_T=2 | `4/8 = 50%` NO_T=1 | — |
| 同上 | §3.1 `p2-rerun` A 组 | `1/6 = 17%` | **`0/6 = 0%`** | — |
| 同上 | §2.5 过线① | mine **+38pp** / rerun −1pp | **+31pp** / **−18pp** | **不变**（mine 仍过、rerun 仍不过） |
| 同上 | §2.5 过线② | rerun 固定名单 1/8 | **0/8** | 不变（仍不过） |
| 同上 | §4.1 K 敏感性 | K=3 mine 1/7 · K=5 mine 4/7 rerun 1/6 · K=10 mine 5/7 | 1/8 · 4/8、**0/6** · **6/8** | — |
| 同上 | §4.2 T 严口径 | mine K=5 **57%** | **50%** | 不变（读数仍由 T 定义主导） |
| 同上 | §五 交叉验证 | 召回 **2/11 = 18%** | **不变** | `a-reason-r2` `django-10554` 从 `FIX_FIRST` 变 `NO_T`，**它本来就不在 `ARCH_FIRST` 集合里** |

→ **`EVAL-switch-point.md` 的主结论「判别量不成立」不变，而且变强**：
`p2-rerun` 的 A 组 `ARCH_FIRST` 从 1/6 掉到 **0/6**，两跑分离度从「+38 / −1」拉开成
「**+31 / −18**」——「①只在一跑里出现」这个判断更确凿。
⚠️ 同时也更脆：`p2-mine` 的 +31pp 距阈值 +30pp **只剩 1pp**。

### 1.5 修完暴露出的两处边界（**不动**，记录在案）

本次只修「影响 T 的那处」（本人 09-20 拍板）。全量对拍里另有 2 条判得不够准，
**都属于原有的白名单漏、被旧版 TRIVIAL 越界盖住了**，不是本次改动引入的新病：

| 现场 | 代码 | 现判 | 该归 | 漏在哪 |
| --- | --- | --- | --- | --- |
| `a-reason-r1` `pylint-8898` 轮 20 | `print(os.listdir('doc/whatsnew/3'))` | REPRO（兜底） | BROWSE / ARCH | `BROWSE_PAT` 不认 `os.listdir` |
| `p3-r1` `sympy-18211` 轮 26 | 剔掉 `sys.path` 里的 `/testbed` 再 import sympy，然后 `inspect.getsource` | BROWSE | ARCH | `ARCH_PAT` 不认「剔 sys.path 找另一个安装」（§4.4 已记过 ARCH 白名单会漏） |

⚠️ **第一条是一条真实的新风险，必须写明**：REPRO 现在是兜底分支，会吸收
「不在 BROWSE/ARCH 白名单里的非复现代码」。**本次两跑里这类轮都落在 T 之后，所以 T 没被拉早
—— 但这是运气，不是性质。** 闸上线后若 T 被这种轮拉早，闸会提前触发。
判别量见 §六。

---

## 二 判据（**锁定**，在看到 §三 任何读数之前 commit）

沿用 `EVAL-switch-point.md` §二的做法：**本节先 commit，再跑数；不许在看到读数之后改阈值或分组。**

### 2.1 样本

`p2-mine` + `p2-rerun` 各 25 条全跑【原文 `13-` §五第 1 步】。
`a-reason-r1/r2`（A 组 8 + 对照 2）作交叉验证（§五）。
**两跑各自算，不合并** —— ⑦⑨ 已四次实证单跑方差能吃掉效果。

### 2.2 分组

沿用 `switch_point.rows_for` 的 `grp_actual`【原文 `switch_point.py:110`】：
`first_edit is None` → **A 组**（从未动手），否则 → **B 组**。
用实算组不用固定名单，因为闸是在运行时按行为触发的，与实例属于哪张名单无关。

### 2.3 主量：`delta = first_edit − T`

只对 **T 存在且 `first_edit > T`** 的 B 组实例计算。另外两类**单列不进分母**：

- **T 不存在**的 B 组实例 → 闸永不触发（记 `NO_T`）
- **`first_edit < T`** 的实例 → 先动手后复现，闸的前提（T 领先于第一刀）对它不成立。
  §六 只在 `FIX_FIRST` 子集上报过 18/18 无此情况【原文 `EVAL-switch-point.md:240`】，
  **本次要在全 B 组上重查**

### 2.4 N 的下界

- `N_safe = max(delta) + 1` —— 闸在所有 B 组实例动手之后才可能触发，**零误触发**
- 同时报 delta 的中位 / P75 / P90 / max，两跑各一份

### 2.5 误触发面（本方案的主要风险，**必报**）

对候选 `N ∈ {3, 5, 8, 10, 15, 20, 25, 30}`：

- **误触发条数** = `#{B 组实例 : delta > N}`（闸在它自己动手之前就触发了）
- **误触发率** = 误触发条数 / B 组有 T 的条数

### 2.6 误伤的严重性分层（⚠️ **本节是 Claude 自行判断的增项，本人尚未审**）

「闸触发」不等于「把实例弄坏」：闸只摘 `search_code` / `list_files` / `run_python`，
`read_file` / `apply_patch` / `run_tests` / `git_diff` 全部保留。所以对每条被误触发的 B 组实例，
再量它在 **`[T+N, first_edit)` 窗口**里实际调用过的**被摘工具**次数：

- **0 次** → 闸对它无害（那段窗口里它本来就没用被摘的工具）
- **> 0 次** → 行为确实会被改变，记为**有效误伤**

理由：只报条数会把「闸在它上面什么都没改变」和「闸掐断了它正在用的工具」混成一个数，
而这两件事对第 3 步的风险判断完全不同。⚠️ 这仍**不等于**「它会失败」——
被摘工具后模型可能改用 `read_file` 照样动手，那要真跑才知道（第 3 步）。

### 2.7 A 组的可触发性（**必报**，否则只量了代价没量收益）

- **A 组 T 存在的条数**：T 不存在 = 闸永不触发 = 方案对该实例**结构性无效**
- **A 组满足 `T + N ≤ 40` 的条数**（40 = `--max-steps` 上限，S6 已证不加大）：
  N 越大越安全，但 `T + N` 超过 40 时闸**来不及触发**

### 2.8 过线条件（三条**全**满足才算「N 可定」）⚠️【判断】，阈值由 Claude 定，本人尚未审

1. 存在某个 N，使**两跑各自**的 A 组可触发条数 ≥ **6/8**
2. 同一个 N 下，**两跑各自**的 B 组**有效误伤**（§2.6）≤ **2 条**
3. 两跑分别给出的可行 N 区间**有交集**

三条任一不满足 → **N 定不出来**，照实写，不许放宽阈值凑一个数出来。

---

## 三 结果

（待算，本节在 §二 commit 之后填。）
