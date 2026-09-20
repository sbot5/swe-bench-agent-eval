# SWE-bench Agent Eval

在 **SWE-bench Verified** 上评测一个自建的 Coding Agent scaffold。

这个仓库的核心不是「又一个能跑的 Agent」，而是**一套先于 Agent 建立、并且可复现的评测方法**：
评测集怎么抽、两条基线是什么、失败怎么归因、以及**这些数字不能证明什么**。

> **做法上的一个刻意选择：评测先行。**
> 在写任何 Agent 代码之前，先用维护者的真实修复（gold patch）把整套 Docker 评测链路跑通。
> 理由见下面「为什么先做评测」。

---

## 现在在哪

dev 25 条上的 resolved：

| | resolved | 备注 |
| --- | --- | --- |
| 自建 scaffold | **12 / 13 / 10** | 同一批 25 条、三次跑（S5 · P2 · P2 原样重跑） |
| mini-SWE-agent（官方最小实现） | **21** | 同模型、同端点、同一批 25 条；**给容器断网后 6** |
| gold patch（环境基线） | **25** | holdout 另 50/50 |

**差距不是这个仓库的结论，差距的成因才是。** 已经做出来的三件事：

1. **把失败归到了因。** S5 的 9 条空 patch 不是「轮数不够」——
   三条修法（加预算 / 加工具 / 改 prompt）**全部被自己的数据否掉**，
   最后靠落盘模型的 `reasoning_content` 逐轮读原文拿到根因：
   **它切去考古找上游的标准答案，而不是修这个 bug。** 见下面「主线」。
2. **基线那 84% 里有一半是抄来的。** 给 mini 的容器断网后 21/25 → 6/25；
   非平凡层它解掉的 8 条**逐行等于 gold patch**，断网后归零。基线数字在断网前后不是同一个东西。
3. **成本可以被预测。** 把缓存命中 / 未命中 / 推理三列 token 落盘之后，
   按官方分时单价预测三次真跑的实付，预测/实际 = **0.988 / 0.998 / 0.995**。

---

## 当前进度

| 阶段 | 做了什么 | 结果 | 花费 | 文档 |
| --- | --- | --- | ---: | --- |
| S0 | gold patch 冒烟 3 条 | 3/3 resolved | $0 | |
| S1-dev | gold patch 跑完整 dev 25 条 | **25/25 resolved**，1024s | $0 | |
| S1-holdout | gold patch 跑 holdout 50 条 | **50/50**（剔除 1 条判定不稳定的实例后），258s | $0 | 见下 |
| S2 | mini-SWE-agent 基线 2 条 | 2/2 resolved | $0.06 | |
| S3 | **自建 scaffold 写完，整条链端到端验证** | **gold 回放 25/25 resolved**，66/66 hunk 零失败编辑，8.5s | $0 | 见下 |
| S3′ | scaffold 接真模型跑 2 条 | **1/2 出合法 patch**（验收线是「合法 patch」，不是 resolved） | 分币级 | |
| S4 | dev 10 条 | **8/10 resolved**，0 infra / 0 ambiguous / 0 空 patch | ¥2.24 | [run](docs/DESIGN-run.md) §三 |
| — | `run_tests` 判定改白名单 + 冻结 | tag **`s5-frozen`**；旧黑名单会把「失败」读成「通过」 | $0 | [tools](docs/DESIGN-tools.md) §五 |
| S5 | dev 25 条正式跑 | **12/25**，16 条出 patch / **9 条空 patch** | ¥5.27 | |
| S5-badcase | 9 条空 patch 归因 | **`apply_patch` 调用全部为 0** —— 从未进入编辑阶段 | $0 | [badcase](docs/EVAL-S5-badcase.md) |
| S6 | 决定性实验：80 轮 × 2 条 | 一条**第 72 轮**才首次动手（766 字符 patch，**仍 unresolved**）；另一条 80 轮仍从未动手 | ¥0.85 | [badcase](docs/EVAL-S5-badcase.md) §4.4 |
| S5-baseline | mini 跑同一批 25 条（同模型同端点） | **21/25**；两边都过 12、只有 mini 过 9、**只有我方过 = 空集** | ¥3.17 | [baseline](docs/EVAL-S5-baseline.md) |
| P1 | **给 mini 的容器断网**重跑同 25 条 | **6/25**；非平凡层它解掉的 8 条全部逐行等于 gold | ¥2.90 | [nonet](docs/EVAL-S5-baseline-nonet.md) |
| P2 | 加 `run_python(code)`，同时给我方容器 `--network=none` | **13/25**，但是三人换位的净 +1，落在方差里 | ¥11.15 | [P2](docs/EVAL-P2.md) |
| P2-A | A 组 8 条逐轮对读（$0） | 新工具 **37% 用来找现成答案**，只有 32% 跑被测代码（B 组 77% / 14%） | $0 | [groupA](docs/EVAL-P2-groupA.md) |
| P2-rerun | 原样重跑（第二个样本） | **10/25**；A 组同一批 8 条**三跑 24/24 次零 `apply_patch`** | ¥5.91 | [rerun](docs/EVAL-P2-rerun.md) |
| P3 | 改 prompt 的「先复现」条款 | 动手数 0/24 → 2/16，**p = 0.154 不显著**；新条款触发 6 次、模型**照做 0 次** | ¥5.83 | [P3](docs/EVAL-P3-prompt.md) |
| C21 | 落盘 `reasoning_content` + A 组两跑逐轮读原文 | **根因过线**：186 个选中轮里自述复现成败 3 次、**找上游答案 80 次** | ¥5.66 | [A-reason](docs/EVAL-A-reasoning.md) |
| — | 「复现之后切换到哪」判别量 | 按**跑前锁定**的判据**不成立**，按失败记账 | $0 | [switch](docs/EVAL-switch-point.md) |

> **成本口径**：程序打印的 `cost = $0.0000` **是假的**（litellm 不认 `openai/deepseek-flash` 这个名字），
> 表里的钱一律是**账户余额差**，并在各 EVAL 文档里写明来历。`--cost-limit` 因此失效，
> 止损只剩 `--max-steps` 与 `--wall-clock-limit`。

**scaffold 全部模块完成**（各带设计档案）：
[`observation.py`](agent/observation.py) 观察契约（[DESIGN](docs/DESIGN-observation.md)）·
[`environment.py`](agent/environment.py) 执行层，行为验收 22/22（[DESIGN](docs/DESIGN-environment.md)）·
[`tools/`](agent/tools/) 七个工具，一工具一模块（[DESIGN](docs/DESIGN-tools.md)）·
[`loop.py`](agent/loop.py) ReAct 循环（[DESIGN](docs/DESIGN-loop.md)）·
[`run.py`](agent/run.py) 批量入口 · [`report.py`](agent/report.py) badcase 归因表（[DESIGN](docs/DESIGN-run.md)）。
测试 150 条：`python -m pytest tests/ -q`（129 条假 env / 纯函数，9.9 秒）、加 `-m slow`（21 条真容器，11.4 秒）。

> ✅ **已纠正，不静默改（09-17）**：这里原先写着「S3′ 被学校网络拦截，挂 VPN 连不上 API」——
> **归错了因**。真因是跑批的命令**漏了 `--model`**，落回 `model.py` 里的中转站默认值，
> 才去打那个被屏蔽的域名；**S5 本来就跑在 DeepSeek 官方端点上**，换网络不是必要条件。
> 当时做的七条网络探针结论仍然成立，只是它拦的不是这个实验。
> 三条原文证据留档在 [`docs/EVAL-S5-badcase.md`](docs/EVAL-S5-badcase.md) §4.1「已纠正的错误 ②」。

### 整条链怎么在不花一分钱的情况下证明是对的

把 25 条 gold patch 的每个 hunk 拆成一对 `(old_string, new_string)`，当成一个**假模型**喂给循环
（[`tests/gold_replay.py`](tests/gold_replay.py)）—— 容器、七个工具、ReAct 消息协议、patch 提取、
`preds.json` 格式、官方 harness 全部真跑，只有「模型该改哪里」这一件事被换成了已知答案。

| 结果 | 值 |
| --- | --- |
| 25 条实例 / 66 个 hunk | **66/66 一次打上，零失败编辑**，8.5 秒（5 并发） |
| 走官方 harness 评测 | **25/25 resolved**，0 infra failure · 0 ambiguous · 0 empty patch |

**这个数的意义**：链上任何一环有 bug 都到不了 25/25。**接模型之前的未知量只剩模型本身。**
顺带量到一件事：git 默认三行上下文的 search/replace 锚点，在 66 个真实修复 hunk 上**全部唯一** ——
这是「`apply_patch` 不提供 `replace_all`」这个决定的实测依据，不是假设。

它后来还当了**回归闸门**：每次改 scaffold 之前先跑一遍，25 条 patch 与上一次**逐字节相同**才开跑
（改工具、加 `run_python`、拆包重构各用过一次），所以那些改动**不必重跑评测**就知道没碰坏链路。

---

## 主线：9 条空 patch 到底卡在哪

S5 那一跑，25 条里有 9 条交了空 patch。第一反应有两个：**轮数不够**，或者**原地打转**。
归因表第一件事就把这两个都否掉了 —— 这 9 条的 `apply_patch` 调用数**全是 0**：
它们不是改错了，是**从来没进入编辑阶段**。

后面每一步都在杀一个假设。**每一步的修法都是我自己提的，也都是被我自己的数据否掉的**：

| # | 假设 | 怎么测 | 结果 |
| --- | --- | --- | --- |
| ① | 40 轮预算不够 | 提到 80 轮，跑 2 条（S6） | **半成立**：一条第 72 轮首次动手、**改错了**；另一条 80 轮仍从未动手 |
| ② | 缺一个能真正跑代码的工具 | 加 `run_python(code)`，同时把容器断网（P2） | **零和**：12→13 是三人换位；A 组 9 条只挪开 1 条 |
| ③ | 加了工具但它没用 | 逐条读 A 组 8 条的 105 次调用（$0 对读） | **否**，全在用。但 **37% 用来在容器里找现成答案**（翻 git 历史 / `pip download` / grep 上游 PR 号），只有 32% 跑被测代码；B 组是 **77% / 14%** |
| ④ | 是 prompt 的「先复现」条款把它卡住了 | 改条款，A 组 8 条 + 2 条对照 × 2 跑（P3） | **否**：动手数 0/24 → 2/16，Fisher **p = 0.154**、配对符号检验 **p = 0.25**；新条款的触发条件出现 6 次，模型 **0 次照做** |
| ⑤ | 那它到底在想什么 | 把 DeepSeek 返回的 `reasoning_content` 落盘，A 组 8 条 × 2 跑逐轮读原文 | **根因**：186 个选中轮里，自述复现成败只出现 **3 次**，**找上游标准答案出现 80 次** |

⑤ 读到的是模型自己的推理原文，不是我的转述：

> `pylint-8898`：**the hidden test is derived from the gold PR**
> `sympy-18211`：**SWE-bench instance IDs use the PR number that fixed the issue**
> `sphinx-8638`：I found the reproduction … **Now I need to figure out the upstream fix**

而能解掉的那一组长这样：

> `django-14631`：**Reproduced the bug. … Now let me implement the fix.** → 轮 34 / 35 / 37 / 39 连下四刀

**结论：A 组不是没有状态切换，是切去了考古。**
它认出自己正在被一个公开基准测，于是去找那个基准的答案，而不是修这个 bug。
这也解释了 ①②④ 为什么全都无效：它们加的是**能力和建议**，而卡点是**目标**。

⚠️ **这条线还没有结论性的修法。** 被自己的数据排除掉的是 ①②④；
下一步是把约束做进 scaffold 层（正在调研 SWE-agent 的 ACI、Agentless 的三段式等工业方案）。

### 从这条链上掉出来的四条方法论

- **prompt 里加一条规则 ≠ 系统里多了一条规则。** 要拦住行为得做进 scaffold，prompt 只是建议。
  同一件事在断网上又出现一次：模型在轨迹里亲眼看见 `pip download` 报 `[Errno -3] name resolution`，
  **之后仍然用满 40 轮、从未改变策略**。
- **判别量要在花钱之前锁定。** ⑤ 的落点表、阈值、「不得事后新增类别」全部先 commit 再开跑。
- **新判别量上线前，先量它自己的方差。** 后来自己提的另一个判别量（「复现之后切换到哪」）
  两跑方向**相反**（+38pp / −1pp），而它想替代的 resolved 分数两跑只差 12pp ——
  **量具比被量的东西还不稳**，于是按失败记账、不改口径重算。
  交叉验证还发现它的落点与 ⑤ 的落点**交集只有 18%**：它压根不在量同一件事。
- **相关性越完美，越要先问它在不在下游。** `run_tests == 0` 与空 patch 在 25 条上 100% 分离，
  但 B 组 16/16 条的第一刀都**早于**第一次跑测试 —— 它是「没动手」的**后果**，当不了早期预警。

---

## 为什么先做评测，再写 Agent

跑一条 SWE-bench 实例要经过六个环节：拉镜像 → 起容器 → 打 patch → 跑测试 → 判定 → 写结果。
**这六个环节全部与 Agent 无关。**

gold patch 是仓库维护者当年的真实修复，**它保证应该 resolved**。所以它跑通就等于把「环境」
这个变量钉死 —— 之后任何 unresolved 都只能是 Agent 的问题。

不这么做的代价是具体的：写完 Agent 第一次跑出 `resolved = 0/25` 时，你面对**双重未知**
（Agent 不行还是环境不行），而人的本能是去 debug 自己写的那部分。

**这个判断在本项目第一天被实证了两次。**

第一次：gold 冒烟还没跑到 SWE-bench 就抓出本机 Docker Desktop
的挂载故障（dockerd 起得来但 `/var/lib/docker` 挂不上）。按「先写 Agent」的顺序，
这个故障会在两周后以一个无法归因的 0/25 出现。实际代价：20 分钟，$0。

第二次：holdout 的 50 条里有 1 条 gold patch 也过不了 —— 详见下面「一条被剔除的实例」。
这条如果不在写 Agent 之前查出来，将来 Agent 在它上面失败会被归因成能力问题。

官方 harness 自己也认这个区分 —— 评测报告里 `likely infrastructure failures` 与
`ambiguous failures` 是独立于 `unresolved` 的计数字段。

---

## 评测集怎么构造的

从 SWE-bench Verified 的 500 条里抽出**两个不相交的集**，共 75 条，由
[`make_subset.py`](make_subset.py) 一次运行产出。

| | 条数 | 配额 (easy/medium/hard) | repo 上限 | 用途 |
| --- | ---: | --- | ---: | --- |
| [`subset_ids.txt`](subset_ids.txt) | 25 | 8 / 9 / 8 | 3 | **dev** —— scaffold 迭代时反复跑 |
| [`holdout_ids.txt`](holdout_ids.txt) | 50 | 16 / 18 / 16 | 6 | **test** —— 只在最后跑一次 |

### 三个设计决定

**① 按 difficulty 分层，不按 repo。**
难度是 OpenAI 做 Verified 时标注的。更要紧的是**只有它能指导迭代**：
「hard 全挂」告诉我该改规划能力；「django 挂得多」什么也没告诉我，因为 django 只是碰巧
占全量的 46.2%。

**② 过采样 hard（8/9/8，而非按比例的 10/13/2）。**
测的是**能力边界**，不是平均分。按比例抽 hard 只有 2 条，看不出边界，分层就白做了。
两个都是 40% 的 Agent，`easy 90 / medium 30 / hard 0` 和 `easy 45 / medium 40 / hard 35`
是完全不同的两个东西，平均分把这个差异抹平。

**③ 同一 repo 在同一层内设上限。**
django 占全量 46.2%（hard 层里 48.9%）。不加上限，「难度剖面」会退化成
「django 的难度剖面」，分不清是「真的难」还是「django 难」。

### holdout 防的不是 Agent，是我自己

Agent 每次只拿到一个仓库 + 一条 issue，跑完容器销毁，**跨实例没有任何记忆**，
不存在「泄露给它」这回事。

真正会累积的是**我的调参决定**：每看到 dev 上的一次失败就改 prompt / 工具 / 上下文策略，
十轮之后分数变高了，但其中多少是真变强、多少是记住了这 25 条的特点，我自己分不清。
holdout 从不参与迭代，所以它的分数没有被我调过。

**holdout 的 cap 是 6 不是 3**，因为 cap 约束的是**份额**不是条数。dev 的 hard 层
8 条 cap 3 → 单仓库最多 37.5%；holdout 的 hard 层 16 条若 cap 仍为 3 → 只有 18.75%。
组成一旦不同，两个集的分数差就分不清是过拟合还是组成差异。等比放大后实测对齐：

| 层 | dev（django 份额） | holdout（django 份额） |
| --- | --- | --- |
| easy | 3/8 = 37.5% | 6/16 = 37.5% |
| medium | 3/9 = 33.3% | 6/18 = 33.3% |
| hard | 3/8 = 37.5% | 6/16 = 37.5% |

### 一条被剔除的实例 —— gold patch 验证真正抓到的东西

用 gold patch 跑 holdout 第一版时，**有 1 条不 resolved**：`django__django-13344`。
下面是排查过程，每一步都在排除一个假设：

| 检查 | 结果 | 排除了什么 |
| --- | --- | --- |
| FAIL_TO_PASS | **2/2 通过** | 修复本身是对的 |
| PASS_TO_PASS | 354/356，挂 `test_touch`、`test_expiration` | 问题在「有没有改坏别的」 |
| 换 `-j 1` 单独重跑 | 同样两条挂，两次结果完全一致 | **不是并行争抢导致的 flaky** |
| 容器里实测 `sleep 2` | wall / monotonic 都走 2.0s | **不是 WSL2 时钟漂移** |
| 容器时区 | `Etc/UTC` | **不是时区问题** |
| 孤立跑这两条 | 通过，7.1s | 测试本身没毛病 |
| 基线（无 patch）跑完整 cache 套 | 通过，481 条 / 13.3s | **不是环境坏** |
| 评测时 | 挂，487 条 / 67.9s（test_patch 改了 `tests/runtests.py`） | ← 差异在这里 |

两条失败的测试都是「设 N 秒超时 → `time.sleep(N+1)` → 断言已过期」的**实时依赖**写法。
而这条实例本身是关于 **ASGI 中间件协程**的（gold patch 改的是 `middleware/cache.py`、
`middleware/security.py`、`sessions/middleware.py`），**与缓存过期语义毫无关系**。

**结论：判定不稳定，既不是环境问题也不是能力问题。**
这正对应 SWE-bench Verified 论文所述「**61.1% 的单元测试会误杀正确解法**」的残留 ——
Verified 已经筛掉了大部分，但 PASS_TO_PASS 里带 `time.sleep` 的测试本质上就是脆弱的。

**处理**：写进 `make_subset.py` 的 `KNOWN_BAD`（附完整原因与全部证据），重新抽样，重跑 → **50/50**。

> ⚠️ `KNOWN_BAD` **只作用于 holdout，不作用于 dev**。
> 因为 dev 那 25 条已全部 gold 验证通过，里面没有坏的；而一旦把它加进 dev 的排除集，
> 候选池会从 500 变成 499，同一个 seed 打乱 499 个和 500 个的结果完全不同 ——
> dev 会整体变动，已经跑过的 S1-dev 就作废了。
>
> 排除 1 条最终连带换掉了 4 条（池子变了，贪心扫描的结果跟着变），46 条不变。
> 只变 4 条而非全变，是因为 **cap 让抽样部分地与顺序无关**：某仓库在某层内条数 ≤ cap 时，
> 它的全部实例必然入选，与打乱顺序无关。变动只发生在 django、sympy 这些远超 cap 的大仓库上。

---

## 两条基线

| 基线 | 是什么 | 回答什么问题 |
| --- | --- | --- |
| **gold patch** | 维护者的真实修复 | **环境**对不对（应当 100% resolved） |
| **mini-SWE-agent** | SWE-bench 官方团队维护的最小实现 | **能力**基线：一个朴素方案能到多少 |

两条基线回答的是不同的问题 —— 前者校验环境，后者校验能力。

**S2（09-06，2 条）**：走第三方中转、模型 `gpt-5.6-luna`，2/2 resolved，$0.06。
⚠️ 换了供应商和模型，**这两条的数不能和后面的比**。

**S5-baseline（09-17，同一批 25 条）**：模型与端点与我方完全一致
（`openai/deepseek-flash`，DeepSeek 官方端点，同一条请求路径），所以是一次**同模型对照**。

| | resolved | 空 patch | 失败模式 |
| --- | ---: | ---: | --- |
| mini（有网） | **21/25** | 4 | 全是 40 步用满的 `LimitsExceeded`（预算耗尽） |
| mini（断网） | **6/25** | 18 | 同上 |
| 我方（S5） | **12/25** | 9 | **`apply_patch = 0`**，从未动手 |

两边都过 12 条、只有 mini 过 9 条、**「只有我方过」是空集** —— 基线是严格超集。

**断网那一跑改变了 84% 的读法。** 非平凡层（gold patch > 8 行，12 条）里，
有网 mini 解掉的 8 条**逐行等于 gold**，断网后**归零**；我方同层解掉 4 条、**0 条逐行等于 gold**。
断网的四层证据：配对探针（`pull/11138.patch` 12502 字节 → 0，且 loopback 仍通，
不误伤要起本地端口的测试）· `docker inspect` 抓到容器 `NetworkMode=none` ·
轨迹里 32 条联网命令 **0 条取件成功** · 结果指纹（终判据，扫描器的误差污染不了它）。

⚠️ **不能因此说「我方 scaffold 更强」**：断网只消掉「联网取件」这一条路，
mini 的 shell 还在（它跑复现脚本 76 次 / 19 个实例，我方当时没有这个工具），而且 n = 1。

⚠️ **我方白拿了一条环境知识**：`run_tests` 的运行器前缀是从实例元数据里抽的
（django 怎么跑、sympy 怎么跑），mini 得自己摸索。评分用的测试目标已经剔干净（75/75 断言过），
但「怎么跑测试」这条便宜确实占了。

---

## 这些数字不能证明什么

写在最前面而不是脚注里，因为这是本项目最该被追问的部分。

1. **点估计的区间很宽。** n = 25 的 pass@1，12/25 的 Wilson 95% 区间约 `[0.30, 0.67]` ——
   **分辨不出「真实 40%」和「真实 50%」**。所以它只用来抓大的回归，不用来给小改动做 A/B。
2. **单跑的方差能吃掉一次修正的全部效果 —— 这不是理论，是四次实证。**
   同一份代码、同一个 prompt、同一批 25 条，三跑拿到 **12 / 13 / 10**，
   其中一对之间**换位 5 条**。所以 P2 的「+1」不能当能力提升读。
   反过来，**失败模式比分数稳**：A 组那 8 条在三跑里 **24/24 次零 `apply_patch`**。
3. **总分不能和排行榜比。** 因为过采样了 hard，总分系统性偏低。**要比只能比分层数字。**
4. **绝对值只能当上界。** 基准来自公开 GitHub 数据，模型可能在训练中见过。
   P1 把这件事从「理论风险」变成了**实测**：断网前后差 15 条，
   非平凡层解掉的 8 条全部逐行等于 gold patch。
5. **模型返回名只有我方这侧可证伪。** 我方每一步都记 `response.model`，按实例汇总进
   `summary.json` 的 `returned_models`（`loop.py` 决定 C15）；
   mini 的 trajectory **不记录 API 返回的 `model` 字段**（`preds.json` 里的
   `model_name_or_path` 是请求名不是返回名）。**两侧口径不同，比较时要记得这一点。**
6. **跨跑的成本基线不可比，所以「便宜了」不能当优化读。** 两个原因：
   DeepSeek 按**北京时间分时计价**（工作日 9–12、14–18 是高峰，其余含周末半价）；
   而**改一次 system prompt 就把整棵前缀缓存树作废** ——
   任何改 prompt 的消融实验，成本基线都不可比。
   实测缓存命中率 58.8%，且 **97% 的未命中出在上下文开始折叠之后**（裁剪省 token、花缓存）。

---

## 可复现

要重跑出同样这 75 条，需要五样，缺一样就不一样：

1. 数据集与 split：`SWE-bench/SWE-bench_Verified`，`split=test`，n=500
2. seed：`42`
3. 两组配额与 cap
4. 排除集（holdout 的候选池依赖 dev 的内容）
5. **抽样算法本身** —— 同一个 seed 配不同算法结果完全不同

第 5 条最容易被忽略，也是为什么**光记 seed 不够、必须把脚本提交进仓库**。

```bash
python make_subset.py     # 产出 subset_ids.txt 与 holdout_ids.txt，自检九条
./collect.sh              # 把证据从 SWE-bench/logs 收进 results/
```

自检包含一条容易做假的检查：**连跑两次输出必须逐行相同**。
它专门抓「seed 固定了但遍历了 set/dict 导致顺序不定」这类 bug。

每个花钱的实验在开跑之前都要过同一道闸：假 env 测试 + 真容器测试 + gold 回放 25/25
且 patch 与上次**逐字节相同** + ruff 无新增 + 容器 `NetworkMode=none` 实抓。
判别量类的实验多一条：**判据先 commit，再开跑**。

### 环境

Ubuntu 24.04 (WSL2) · 原生 docker-ce 29.8.0 · x86_64 · 16 GB RAM · 20 核
SWE-bench harness 来自 upstream commit `02e7a74`（2026-09-02），**不入库**，见 `.gitignore`。

---

## 目录

```
make_subset.py      分层抽样，一次运行产出 dev 与 holdout 两个不相交的集
subset_ids.txt      dev  25 条
holdout_ids.txt     test 50 条（一次都没跑过，留给最终报告）
groupa_ids.txt      A 组：三跑里从未动手的那 8 条 + 2 条对照
collect.sh          把证据从 SWE-bench/logs 收进 results/
agent/
  observation.py    所有工具的统一返回形状：状态、失败类别、渲染、截断
  environment.py    一条实例一个 Docker 容器，工具通过 docker exec 在里面执行；无网卡
  tools/            七个工具，一工具一模块：read_file list_files search_code apply_patch
                    run_tests git_diff run_python；_common.py 放常量与跨工具 helper，
                    __init__.py 只做重导出不放逻辑
  loop.py           ReAct 循环：三个终止条件 + 上下文裁剪 + 异常路径。不认识 Docker，也不认识 SWE-bench
  model.py          litellm 客户端：重试与错误分类，把「可重试」和「没救了」分开
  run.py            批量入口：起容器、绑工具、提取 patch、落盘 preds.json
  report.py         badcase 归因表：按失败模式分桶，每桶配一句修法方向
tests/
  fake_env.py           假执行环境，按脚本回 ExecResult，不起容器
  gold_replay.py        把 gold patch 拆成 apply_patch 调用，当假模型驱动整条链
  smoke_gold_replay.py  端到端冒烟的入口（$0）
  test_*.py             150 条；真容器那 21 条打了 slow marker，默认跳过
results/
  evaluation/<run_id>/results.json       评测结论
  evaluation/<run_id>/attribution.md     badcase 归因表（report.py 产出）
  inference/<run_id>/preds.json          Agent 产出的 patch
  inference/<run_id>/*.traj.json         完整决策链（badcase 归因就靠它）
  inference/<run_id>/summary.json        每条的停止原因、步数、成本、延迟、返回的模型名
```

### 文档

`docs/` 下两类：`DESIGN-<模块>.md` 是**代码**的决策档案（决策清单 · 已纠正的错误 · 实测数据），
`EVAL-<实验>.md` 是**实验**的报告（判据 · 读数 · 排不掉的替代解释 · 遗留的【未知】）。

| 文档 | 讲什么 |
| --- | --- |
| [`EVAL-S5-badcase.md`](docs/EVAL-S5-badcase.md) | 9 条空 patch 的归因；S6 的 80 轮实验；「被网络拦截」那次归错因的更正 |
| [`EVAL-S5-baseline.md`](docs/EVAL-S5-baseline.md) | 没有 token 数怎么把 mini 的成本估到可决策（代理量 → 锚点 → 配对外推 → 上限）；正式跑 21/25 |
| [`EVAL-S5-baseline-nonet.md`](docs/EVAL-S5-baseline-nonet.md) | 给基线断网：21 → 6，四层证据，四条污染假设怎么排 |
| [`EVAL-S5-pairwise.md`](docs/EVAL-S5-pairwise.md) | 配对轨迹对读（$0）：为什么有网那一跑不能当 scaffold 能力对照 |
| [`EVAL-P2.md`](docs/EVAL-P2.md) | 加 `run_python` 的 25 条；成本为什么贵一倍（找错基线的第三种形态） |
| [`EVAL-P2-groupA.md`](docs/EVAL-P2-groupA.md) | A 组 8 条逐轮对读：新工具用在了哪；三个判别量的取舍；甲型那条逐轮读完 |
| [`EVAL-P2-rerun.md`](docs/EVAL-P2-rerun.md) | 原样重跑：方差第三次实证；缓存命中率直读；分时计价 |
| [`EVAL-P3-prompt.md`](docs/EVAL-P3-prompt.md) | 改 prompt 无效，且真因是「指令没被遵守」而不是「假设被证伪」 |
| [`EVAL-A-reasoning.md`](docs/EVAL-A-reasoning.md) | 读模型的 `reasoning_content` 原文，拿到根因 |
| [`EVAL-switch-point.md`](docs/EVAL-switch-point.md) | 一个新判别量按锁定判据**没通过**的完整记账 |

不入库的：`SWE-bench/`（第三方 clone）、`.venv/`、每实例的 `test_output.txt` 与
`run_instance.log`（几百 MB，只在排查单条时才看）。
