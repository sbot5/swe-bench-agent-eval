# SWE-bench Agent Eval

在 **SWE-bench Verified** 上评测一个自建的 Coding Agent scaffold。

这个仓库的核心不是「又一个能跑的 Agent」，而是**一套先于 Agent 建立、并且可复现的评测方法**：
评测集怎么抽、两条基线是什么、失败怎么归因、以及**这些数字不能证明什么**。

> **做法上的一个刻意选择：评测先行。**
> 在写任何 Agent 代码之前，先用维护者的真实修复（gold patch）把整套 Docker 评测链路跑通。
> 理由见下面「为什么先做评测」。

---

## 当前进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| S0 | gold patch 冒烟 3 条 | ✅ 3/3 resolved |
| S1-dev | gold patch 跑完整 dev 子集 25 条 | ✅ **25/25 resolved**，errors=0，1024s，$0 |
| S1-holdout | gold patch 跑 holdout 50 条 | 🔄 进行中 |
| S2 | mini-SWE-agent 基线，1 easy + 1 hard | ✅ 2/2 resolved，**$0.06** |
| S3 | **自建 scaffold** | ⬜ **尚未开始** |
| S4 | 两边各跑 dev 25 条对照 | ⬜ |
| S5 | 冻结后跑 holdout 50 条，出归因表 | ⬜ |

> ⚠️ **诚实说明：scaffold 还没写。** 现在仓库里有的是评测基础设施、固定的评测集、
> 和已经量出来的基线数字。Agent 本体是下一步。

---

## 为什么先做评测，再写 Agent

跑一条 SWE-bench 实例要经过六个环节：拉镜像 → 起容器 → 打 patch → 跑测试 → 判定 → 写结果。
**这六个环节全部与 Agent 无关。**

gold patch 是仓库维护者当年的真实修复，**它保证应该 resolved**。所以它跑通就等于把「环境」
这个变量钉死 —— 之后任何 unresolved 都只能是 Agent 的问题。

不这么做的代价是具体的：写完 Agent 第一次跑出 `resolved = 0/25` 时，你面对**双重未知**
（Agent 不行还是环境不行），而人的本能是去 debug 自己写的那部分。

**这个判断在本项目第一天就被实证了** —— gold 冒烟还没跑到 SWE-bench 就抓出本机 Docker Desktop
的挂载故障（dockerd 起得来但 `/var/lib/docker` 挂不上）。按「先写 Agent」的顺序，
这个故障会在两周后以一个无法归因的 0/25 出现。实际代价：20 分钟，$0。

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

---

## 两条基线

| 基线 | 是什么 | 回答什么问题 |
| --- | --- | --- |
| **gold patch** | 维护者的真实修复 | **环境**对不对（应当 100% resolved） |
| **mini-SWE-agent** | SWE-bench 官方团队维护的最小实现 | **能力**基线：一个朴素方案能到多少 |

两条基线回答的是不同的问题 —— 前者校验环境，后者校验能力。

**S2 实测**（模型 `gpt-5.6-luna`，走第三方 API 中转）：

| 实例 | 难度 | 成本 | API 调用 | 结果 |
| --- | --- | ---: | ---: | --- |
| `sphinx-doc__sphinx-9698` | easy | $0.0260 | 11 | resolved |
| `django__django-11138` | hard | $0.0336 | 20 | resolved |

两条都远没触及 `step_limit: 250` / `cost_limit: 3.`。**基线很强 —— 它把 easy 和 hard 都解了。**

---

## 这些数字不能证明什么

写在最前面而不是脚注里，因为这是本项目最该被追问的部分。

1. **点估计的区间很宽。** n=25 的 pass@1，95% 置信区间在 10/25 时约 `[0.23, 0.59]` ——
   **分辨不出「真实 40%」和「真实 50%」**。所以它只用来抓大的回归，不用来给小改动做 A/B。
2. **总分不能和排行榜比。** 因为过采样了 hard，总分系统性偏低。**要比只能比分层数字。**
3. **绝对值只能当上界。** 基准来自公开 GitHub 数据，模型可能在训练中见过，无法排除污染。
4. **推理走的是第三方 API 中转**，不是官方端点。存在模型被替换的风险，
   而 mini-SWE-agent 的 trajectory **不记录 API 返回的 `model` 字段**（`preds.json` 里的
   `model_name_or_path` 是请求名不是返回名），所以这一条目前**无法证伪**。

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

### 环境

Ubuntu 24.04 (WSL2) · 原生 docker-ce 29.8.0 · x86_64 · 16 GB RAM · 20 核
SWE-bench harness 来自 upstream commit `02e7a74`（2026-09-02），**不入库**，见 `.gitignore`。

---

## 目录

```
make_subset.py      分层抽样，一次运行产出 dev 与 holdout 两个不相交的集
subset_ids.txt      dev  25 条
holdout_ids.txt     test 50 条
collect.sh          把证据从 SWE-bench/logs 收进 results/
results/
  evaluation/<run_id>/results.json    评测结论
  inference/<run_id>/preds.json       Agent 产出的 patch
  inference/<run_id>/*.traj.json      完整决策链（badcase 归因就靠它）
```

不入库的：`SWE-bench/`（第三方 clone）、`.venv/`、每实例的 `test_output.txt` 与
`run_instance.log`（几百 MB，只在排查单条时才看）。
