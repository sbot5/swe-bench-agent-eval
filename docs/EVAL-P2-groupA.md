# EVAL-P2-groupA —— 那 8 条「仍从未动手」的实例，`run_python` 用来干了什么

**日期**：2026-09-18 ｜ **成本**：**$0**（只读已落盘轨迹，`agent/` 一行未动，没发起任何模型调用）
**回答的是**：`EVAL-P2.md` §八 第 4 条标的「最便宜的下一步」。

---

## 〇、一句话

**8 条全都用了 `run_python`（合计 105 次），问题不是「没用新工具」，是新工具被用在了别的地方：**
只有 **32%（34/105）** 用来跑被测代码拿动态证据，**37%（39/105）** 用来在容器里**找现成答案**
（翻 git 历史、搜 pip 缓存、全盘找另一个版本、grep 上游 PR 号），**25%（26/105）** 用来做
`read_file` / `search_code` 本来就能做的事。作为对照，**B 组（出手的 16 条）这三个数是 77% / 14% / 6%**。

**判别量**：不是「有没有跑偏去考古」（B 组也有 3 条考古），而是**跑偏之后有没有回来** ——
末 10 轮（轮 31–40）的 `run_python` 里，非诊断调用占 **A 组 76%（32/42）· B 组 5%（1/19）**。

---

## 一、范围与口径

**A 组定义**【原文 `scripts/p2_discriminant.py`】：`apply_patch` 调用数 == 0，即从未进入编辑阶段。

- S5 的 A 组 9 条、P2 的 A 组也是 9 条，但**换了一个人**：`django-14631` 挪出（P2 RESOLVED）、
  `sphinx-9711` 挪入（S5 本来 RESOLVED）。
- **本文的「8 条」= S5-A ∩ P2-A**：`django-10554` `django-11138` `pylint-4551` `pylint-8898`
  `sphinx-11510` `sphinx-8638` `sympy-17630` `sympy-18211`。
- 两条对照全程带着：`django-14631`（救回）· `sphinx-9711`（带沟里）。

⚠️ **轮号口径**（否则数字对不上，同 `CLAUDE.md` 对 `steps` 的澄清）：落盘的 `steps` 是**工具调用**，
一轮可含多个工具；`step["index"]` 才是**模型轮数**，`--max-steps 40` 限的是它。
**本文一律用 `step["index"]` 作轮号**，需要工具序号时另标 `ord=`。

⚠️ **四分类是【推算】不是【原文】**。规则写死在 `scripts/p2_groupa.py` 的 `ARCH_PAT` / `BROWSE_PAT` /
`TRIVIAL_PAT`，优先级 `ARCH > BROWSE > TRIVIAL > REPRO`，未命中一律进 `UNCLASSIFIED` 并**全文打印**
（不许静默归桶）。四类的定义：

| 类 | 是什么 | 典型 |
| --- | --- | --- |
| **REPRO** | 跑被测代码本身，拿动态证据 | `b._blockmul(b)` 触发 bug · 建临时 sphinx 工程 build · `astroid.parse` 看 AST |
| **ARCH**（考古） | 在容器里找现成答案或另一个版本 | `git log --all` / `show <sha>` / `reflog` / `for-each-ref` · `pip download` · `find / -name` · 翻 `~/.cache/pip`、conda pkgs |
| **BROWSE** | 当 `read_file` / `search_code` 用 | `inspect.getsource(X)` · `open(p).read().splitlines()` · `subprocess` 跑 `grep -rn` |
| **TRIVIAL** | 版本探针、自检 | `print(django.VERSION)` · `print("HELLO123")` |

**人工抽查**：10/25 条轨迹的 `run_python` 全文逐条读过（8 条 A 组 + `django-14631` + `matplotlib-24970`
+ `xarray-4356`）。抽查纠正了 1 条（见 §七②），其余与分类器一致。**结论所依赖的实例全部在抽查范围内。**

---

## 二、用了多少次、用来干什么

### 2.1 那 8 条（P2）

| instance | 轮 | 工具总数 | rpy | REPRO | BROWSE | ARCH | TRIV | 首个 ARCH 轮 | run_tests | apply_patch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `django-10554` | 40 | 47 | 13 | 4 | 0 | **8** | 1 | 14 | **0** | **0** |
| `django-11138` | 40 | 48 | 4 | **0** | 0 | 3 | 1 | 27 | **0** | **0** |
| `pylint-4551` | 40 | 40 | 9 | 3 | 0 | **5** | 1 | 26 | **0** | **0** |
| `pylint-8898` | 40 | 57 | 5 | 2 | 0 | 3 | 0 | 27 | **0** | **0** |
| `sphinx-11510` | 40 | 48 | **26** | 1 | **17** | **8** | 0 | 11 | **0** | **0** |
| `sphinx-8638` | 40 | 48 | 19 | 5 | **9** | 4 | 1 | 9 | **0** | **0** |
| `sympy-17630` | 40 | 45 | 15 | **14** | 0 | **0** | 1 | — | **0** | **0** |
| `sympy-18211` | 40 | 46 | 14 | 5 | 0 | **8** | 1 | 15 | **0** | **0** |
| **合计** | | **379** | **105** | **34**(32%) | **26**(25%) | **39**(37%) | 6 | | **0** | **0** |

两条对照：

| instance | rpy | REPRO | BROWSE | ARCH | TRIV | 首次 REPRO 轮 | 首次 apply 轮 | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `django-14631`（救回） | 4 | 3 | 0 | **0** | 1 | **22** | 25 | **RESOLVED** |
| `sphinx-9711`（带沟里） | 22 | 4 | **12** | **6** | 0 | 18 | — | A 组 |

### 2.2 A 组 vs B 组（全 25 条，`p2_groupa.py profile`）

| | n | rpy | REPRO | ARCH | BROWSE | 首次 REPRO 轮（中位） | 末 10 轮 rpy | 其中非诊断 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **A 组** | 9 | 127 | 38 (**30%**) | 45 (**35%**) | 38 (**30%**) | **13**  [2,20]，8/9 有 | 42 | **32 (76%)** |
| **B 组** | 16 | 118 | 91 (**77%**) | 16 (14%) | 7 (6%) | **4**  [1,22]，16/16 有 | 19 | **1 (5%)** |

（127+118 = 245，与 `EVAL-P2.md` 的「245 次调用」对得上。）

### 2.3 「没学会用新工具」这条先排掉

那 8 条的工具替代率**与全体一致**【推算，两跑 `counts` 相减】：

| | S5 | P2 | 变化 | 全体（`EVAL-P2.md` §二） |
| --- | ---: | ---: | ---: | --- |
| `read_file` | 232 | 148 | **−36%** | −37% |
| `search_code` | 138 | 108 | **−22%** | −21% |
| 工具调用总数 | 402 | 379 | −6% | |

→ **它们和成功那批一样地采纳了新工具、一样地用它替换了旧工具。差别只在用途。**
所以「采纳率 100%」这个指标在这里**几乎不含信息**（见 ㉗）。

---

## 三、不是一种失败，是三种

把 8 条按用途拆开，**至少三种互不相同的病**，不该用一句「从未动手」概括：

**甲 · 几乎没用（1 条）**：`django-11138` —— 40 轮里只调 4 次 `run_python`，**REPRO = 0**，
即**一次都没跑过被测代码**；其中 3 次是 `git log` / `git show HEAD`。它的行为基本等同于 S5
（`read_file` 22 + `search_code` 22）。**新工具对它等于没加。**

**乙 · 考古占主导（6 条）**：`django-10554` `pylint-4551` `pylint-8898` `sympy-18211`
`sphinx-11510` `sphinx-8638`。ARCH 占其 `run_python` 的 21%~62%。典型动作（全部【原文·轨迹】）：

- `django-10554` 轮 16/20/37/38：`git show 4948fbe849` / `git show 14d026cccb -- <源文件>` /
  `git show 14d026cccb -- tests/queries/test_qs_combinators.py` —— **在 git 历史里找那次修改**
- `pylint-4551` 轮 38：`find / -name inspector.py -path '*pyreverse*'` —— 找**另一个版本的 pylint**
- `sympy-18211` 轮 32–35：`glob.glob('/**/sympy/solvers/inequalities.py', recursive=True)`（**超时**，
  8 条里唯一一次非 ok）→ `os.walk(['/usr/local/lib','/usr/lib','/opt','/root','/home'])` →
  翻 `/root/.cache`、`/opt/miniconda3/pkgs` —— 连续 4 轮全盘找另一个 sympy
- `sphinx-11510` 轮 13/19/20/40：`pip download sphinx==7.4.0` · `find / -name sphinx*` ·
  `du -sh /root/.cache/pip` · `git for-each-ref` + 「search all objects for commits **mentioning 10650**」

**丙 · 诊断到位但从不动手（1 条）**：`sympy-17630` —— **ARCH = 0、REPRO 14/15（93%）**，
是 8 条里唯一没考古的。它轮 2 就复现了 bug，一路缩到 `Add(z,z)` 返回类型不对，
轮 40 已经读到 `matadd.py` 的 `rules` / `canonicalize` —— **方向是对的，就是不动手**。
这与 S6 的实测吻合：给它 80 轮，它在**第 72 轮**才第一次 `apply_patch`，而且仍 unresolved【原文 `EVAL-S5-badcase.md` §4.4】。

> `sphinx-8638` 介于乙丙之间（REPRO 5 · BROWSE 9 · ARCH 4），不强行归类。

---

## 四、判别量

### 4.1 先淘汰一个看起来完美的：`run_tests == 0`

这 8 条（以及 A 组全 9 条）**`run_tests` 调用数全是 0**，而 B 组 16 条**全部 > 0** ——
25 条**零重叠、100% 分离**。但它**不能当判别量**：

**B 组 16/16 条的首次 `apply_patch` 轮号都早于首次 `run_tests`**【原文 `p2_groupa.py order`】：
21<24 · 6<8 · 4<9 · 14<16 · 6<10 · 4<6 · 4<5 · 25<35 · 6<9 · 22<24 · 7<18 · 11<13 · 5<10 · 20<22 · 23<30 · 12<16。

→ **`run_tests` 永远发生在第一刀之后，它是「没动手」的后果，不是原因**，也不可能当早期预警
（在你需要它的时候，它还没有值）。这是⑫「替代解释要免费排除」的反面：
**一个完美相关但处在下游的变量，相关性越完美越危险。**

### 4.2 上游的：首次 REPRO 轮号

**A 组中位 13（区间 [2,20]，8/9 有）· B 组中位 4（区间 [1,22]，16/16 有）。**
这是⑪「首次动手步号双峰」在因果链上**往前挪一格**的版本 —— 首次动手要等编辑发生，
首次 REPRO 在第一刀之前就能读到。

⚠️ **有重叠，不是干净分离**：以「≤5 轮」为线，B 组 13/16 在线内，A 组只 2/8；
但 `django-14631` 首次 REPRO 在**轮 22** 仍 RESOLVED，`sympy-17630` 首次 REPRO 在**轮 2** 仍从未动手。
**单靠它判不了个案，只能读分布。**

### 4.3 最干净的：末段有没有回来

**B 组也有 3 条考古**（`matplotlib-24970` ARCH 9 · `sympy-13852` 5 · `sphinx-7889` 2），
所以「有没有跑偏」不是判别量。**差别在跑偏之后**：

| | 考古起止 | 之后 | 结果 |
| --- | --- | --- | --- |
| `matplotlib-24970`（B） | 轮 7 → 轮 20 | **轮 22 动手** | RESOLVED |
| `sphinx-7889`（B） | 轮 6 | **轮 11 动手** | RESOLVED |
| `sympy-13852`（B） | 轮 5 | **轮 23 动手** | 出 patch |
| **A 组 8 条** | 轮 9~27 → **一直到轮 40** | 没有之后 | 空 patch |

量化：**末 10 轮（轮 31–40）的 `run_python` 里，非诊断（ARCH+BROWSE）占比 ——
A 组 76%（32/42）· B 组 5%（1/19）。**

→ **判别量是「跑偏之后有没有回到诊断」，不是「有没有跑偏」。**
B 组那 3 条证明考古本身是可以幸存的；A 组是**沉进去没出来**。

---

## 五、替代解释

### 5.1 排不掉，而且部分成立：A 组确实更难

| | n | gold 新增行（中位 / 均值 / 区间） | 非平凡（>2 行） | mini **断网** 过 | mini **有网** 过 | S5 过 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| **A 组** | 9 | **14** / 26.7 / [1, 99] | 7/9 | **0/9** | 6/9 | 1/9 |
| **B 组** | 16 | **3** / 9.8 / [1, 31] | 9/16 | **6/16** | 15/16 | 11/16 |

**mini 断网解掉的 6 条全部落在 B 组、A 组 0/9**【原文 `logs/evaluation/s5-baseline-nonet/results.json`】——
这是一个**完全独立的 scaffold、不同的失败模式**给出的难度排序，和我方一致。
**「A 组就是难题」这条排不掉。**

### 5.2 但它不充分

- **两条 gold ≤2 行的平凡题落在 A 组**：`sympy-17630`（gold+ = 2）· `sphinx-8638`（gold+ = 1）
- **两条 gold+ = 31 的非平凡题落在 B 组**，其中 `django-14631` 还 RESOLVED
- 区间**严重重叠**：A [1, 99] vs B [1, 31]

→ **难度能解释一部分，解释不了全部。** 而且【判断】**`gold+ 行数`量的是 patch 规模、不是定位难度** ——
一个两行的修法可以极难找到（`sympy-17630` 正是：gold 只有 2 行，我方 80 轮没解，mini 断网也没解）。
**本文不把它当难度的充分度量。**

### 5.3 免费排掉的

- **不是「没学会用新工具」**：替代率与全体一致（§2.3）
- **不是工具层故障**：105 次调用里 **104 次 ok**，唯一一次非 ok 是 `sympy-18211` 轮 32 的
  全盘 `glob` 超时 —— 而那次本身就是考古
- **不是没给够轮数**：8 条全部 `stop=max_steps`、`api_calls=40` 跑满，且 S6 已证补到 80 轮
  只把失败从「不动手」换成「改错」【原文 `EVAL-S5-badcase.md` §4.4】

---

## 六、顺带拿到：容器层断网的**正式跑现场证据**

`CLAUDE.md` 记「09-18 追加……⚠️ 这一处本人尚未审」——指的是给容器加 `--network=none` 的第六处改动。
P2 跑前的验证是**负对照**（同镜像默认网络 `REACHED THE NETWORK`、`--network=none` 得 `gaierror -3`）。
**这次在正式跑的轨迹里抓到了模型自己撞上去的记录**：

**`sphinx-9711` 轮 15**【原文·轨迹 observation】：

```
r2 = subprocess.run(['bash','-lc','ls /root/.cache/pip; pip download sphinx==4.3.0 -d /tmp/x 2>&1 | head -5'], ...)
```
```
WARNING: Retrying (Retry(total=4, ...)) after connection broken by
'NewConnectionError(...: Failed to establish a new connection:
[Errno -3] Temporary failure in name resolution)': /simple/sphinx/
```

→ **模型确实会去下载上游包，容器层确实挡住了。** 这正是 P1 抓到的 mini 那条路
（mini 有网时 24/25 条发起过网络请求、多条直接下 `.patch` 再 `git apply`）。
**第六处改动不是防御性假想，是真的被触发了。**

**三条附带的观察**：

1. **同一个动作、两条轨迹，一条看见了断网、一条没看见。** `sphinx-11510` 轮 13 也跑了
   `pip download sphinx==7.4.0`，但它只 `print(subprocess.run(...).stdout)` —— pip 的报错走 stderr，
   被它自己的 `capture_output=True` 吞掉，**观察里只有一个空行**。
   `run_python` 本身是把 stderr 并进 stdout 的（`agent/tools.py:1529` 的 `2>&1`），**丢在模型自己的代码里**。
   → **断网的失败信号可以是静默的**（见 ㉚）。
2. **看见了也没用。** `sphinx-9711` 在轮 15 明确读到 `[Errno -3]`，之后仍然 22 次 `run_python`
   用满 40 轮、从未动手。**「它要是知道没网就会改策略」不成立。**
3. **它还试过找评测框架本身。** `matplotlib-24970` 轮 20：
   `grep -rl '24511' / --include='*.patch' --include='*.diff'`（24511 是上游 PR 号）+
   `find / -maxdepth 3 -iname '*swe*bench*'` —— 前者只命中 conda 元数据 JSON（假阳性），后者**空**。

**规模**【推算，扫描规则见 `p2_groupa.py` 的 `NET_PAT` / `HUNT_PAT`】：
**11/25 个实例有考古行为，跨 5 个仓库**（django · pylint · sphinx · sympy · matplotlib），
但**真正发起网络请求的只有 2 次 / 2 个实例**，其余全是本地考古（git 历史、文件系统、pip/conda 缓存）。
→ 「去找现成答案」是这个模型**稳定的策略**而不是个例；**断网只堵住了其中最直接的那一条路。**

---

## 七、已纠正的错误（不静默改）

**① `django-14631` 的「轮 15 拿动态证据」不准确。**
`EVAL-P2.md` §六 ㉔ 与 `Career/07-swe-bench-agent/CLAUDE.md` 都写成
「P2 轮 15 拿动态证据、轮 25 动手」。逐条读轨迹后：**轮 15 的 `run_python` 全文是**

```python
import django
print(django.__version__)
print(django.VERSION)
```

—— 一条版本探针，不是动态证据。**真正的复现在轮 22**（构造 `DateTimeForm(initial=..., disabled=True)`
触发 bug），**首次 `apply_patch` 在轮 25**。
**正确口径：轮 22 拿动态证据、轮 25 动手。** 「轮 25 动手」没错，错的是前半句。
这不影响 ㉔ 的结论（一个能力的净收益可能零和），但**影响 §4.2 的数字**（它是 B 组首次 REPRO 的最大值 22）。

**② 分类器首版漏了一种读文件写法。** `sphinx-9711` 轮 25 的
`for i, line in enumerate(open('/testbed/sphinx/extension.py'), 1)` 首版判为 `UNCLASSIFIED`
（也是 245 次里唯一一条）。已补 `enumerate\(open\(` 规则，该条归 BROWSE。
**它是被 `UNCLASSIFIED` 全文打印捞出来的，不是抽查捞出来的** —— 保留「未命中就打印」这条设计是值的。

---

## 八、面试可讲的事（接 ㉖）

**㉗ 「采纳率 100%」几乎不含信息。** `EVAL-P2.md` 写「`run_python` 采纳率 100%、245 次调用、99.2% ok」，
读起来像个好消息。逐条读下去才知道：**失败那 8 条的采纳率同样是 100%，工具替代率（read −36% / search −22%）
也和成功那批一模一样**，差别全在**用途**（REPRO 占比 32% vs 77%）。
**一个能力加没加上去，和它被用在哪里，是两个问题；前者的指标不能回答后者。**
下次加工具，验收指标要直接定在用途分布上，不是调用数和成功率。

**㉘ 相关性越完美，越要先问它在不在下游。** `run_tests == 0` 把 25 条分得干干净净、零重叠，
是我这次见过最漂亮的分离。但 **16/16 条的第一刀都早于第一次跑测试** —— 它是「没动手」的**后果**。
这和⑩（黑名单判成功）、㉓（基线选错）是同一类：**数字本身没错，错在它在因果链上的位置。**
可操作的拦法：**任何判别量，先问「它的值是在我要预测的事情之前还是之后确定的」。**

**㉙ 判别量不是「有没有跑偏」，是「跑偏之后有没有回来」。** 我一开始想说「考古行为区分了 A/B 组」，
但 B 组有 3 条也考古，其中 `matplotlib-24970` 考古了 14 轮（轮 7→20，连 gold patch 的注释串和
上游 PR 号都全盘 grep 过），**找不到之后在轮 22 回到诊断并 RESOLVED**。
真正分开两组的是**末段构成**：末 10 轮 `run_python` 的非诊断占比 **76% vs 5%**。
**能力给错用法是可以幸存的；出不来才是失败。** —— 这也直接指向一个比「再加工具」便宜得多的改法方向。

**㉚ 断网的失败信号会被吞掉，而且吞在你管不着的地方。** `run_python` 把 stderr 并进了 stdout
（`tools.py:1529`），但模型自己写 `subprocess.run(..., capture_output=True)` 再只 `print(.stdout)`，
pip 的 `[Errno -3]` 就没了 —— `sphinx-11510` 轮 13 拿到的是**一个空行**，
而 `sphinx-9711` 轮 15 因为自己写了 `2>&1 | head -5` 就**看见了**。
**同一个环境限制，模型能不能感知到，取决于它自己那两行代码。**
把限制做进容器层是对的（语言层拦不住），但**限制要能被观测到**，否则模型会一直换着法子撞。

---

## 九、【未知】

1. **考古是病因还是病症，本文判不了。** A 组首个 ARCH 轮号中位 14.5，而 B 组首次动手中位是轮 9 ——
   考古开始时成功组已经动过刀了，这**偏向病症**；但 A 组有 2 条在轮 9/11 就开始考古，早于 B 组中位。
   **时序定不了因果。** 能确定的只有：**这 39 次调用在 S5 物理上不可能发生**（六个工具没一个能跑
   git / pip / find），所以它是 `run_python` **新开出来的**消耗，不论它是因还是果。
   **验证法**：改 system prompt 明确禁止考古（「不要在 git 历史或文件系统里找修复」）再跑一次 ——
   但 ㉕ 已证**改 prompt 会让成本基线不可比**，且⑦⑨ 的方差要重复跑才压得住。**不建议现在做。**
2. **`django-11138`（甲型，REPRO=0）为什么几乎不用新工具**：40 轮只调 4 次，本文没往下读它的
   `thought` 与 `read_file` 序列。**$0 可查。**
3. **这 8 条在别的模型下是不是同样的分型**：n=1 单模型（`deepseek-flash`），⑦⑨ 的方差未压。
4. **末段非诊断占比 76% vs 5% 的方差有多大**：单次跑，没有重复。按⑨ 的教训，
   **不得拿它当「修正有效」的验收线**，只能当本跑的描述。

---

## 十、复现

全部 **$0**，只读 `results/inference/p2-mine/`（25 条轨迹已入库）。脚本：`scripts/p2_groupa.py`。

```bash
cd ~/swe-bench-eval

# A 组是哪几条（S5 / P2 对照）
python3 scripts/p2_discriminant.py results/inference/p2-mine
python3 scripts/p2_discriminant.py results/inference/s5-mine

# §2.1 §2.3 工具分布（8 条 + 2 条对照，两跑并排）
python3 scripts/p2_groupa.py counts results/inference/p2-mine results/inference/s5-mine

# §2.1 §2.2 四分类 + UNCLASSIFIED 全文
python3 scripts/p2_groupa.py classify results/inference/p2-mine            # 8 条 + 2 条对照
ALL=$(ls results/inference/p2-mine/*.traj.json | xargs -n1 basename | sed 's/.traj.json//')
python3 scripts/p2_groupa.py classify results/inference/p2-mine $ALL       # 全 25 条

# §2.1 的「合计」行（只要那 8 条）→ {'REPRO': 34, 'ARCH': 39, 'BROWSE': 26, 'TRIVIAL': 6}
STILL="django__django-10554 django__django-11138 pylint-dev__pylint-4551 pylint-dev__pylint-8898
       sphinx-doc__sphinx-11510 sphinx-doc__sphinx-8638 sympy__sympy-17630 sympy__sympy-18211"
python3 scripts/p2_groupa.py classify results/inference/p2-mine $STILL

# §四 判别量
python3 scripts/p2_groupa.py order   results/inference/p2-mine   # 首次 rpy / run_tests / apply_patch 轮号
python3 scripts/p2_groupa.py profile results/inference/p2-mine   # 首次 REPRO 轮号 + 末 10 轮构成

# §五 替代解释（需要 datasets，走 .venv）
PYTHONPATH=. .venv/bin/python scripts/p2_groupa.py confound

# §六 摸网 / 找上游答案，附观察全文
python3 scripts/p2_groupa.py net results/inference/p2-mine

# §三 §七 逐条读原文
python3 scripts/p2_groupa.py dump results/inference/p2-mine sympy__sympy-17630
python3 scripts/p2_groupa.py code results/inference/p2-mine django__django-14631 15
```
