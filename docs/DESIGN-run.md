# run.py 设计档案

> **✅ 2026-09-16 完成，Claude 写**（分工见 [`DESIGN-loop.md`](DESIGN-loop.md) 开头）。
> 配套：[`DESIGN-loop.md`](DESIGN-loop.md)（循环）· [`DESIGN-tools.md`](DESIGN-tools.md)（六个工具）

## 一、它做什么

```
读 id 文件 -> 从数据集取实例 -> 每条起一个容器
   -> derive_test_command 抽出这个仓库怎么跑测试
   -> 六个工具绑到这个容器上
   -> run_episode
   -> extract_patch
   -> 落盘 <instance_id>.traj.json / preds.json / summary.json
```

```bash
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s4-mine --limit 10 --workers 4
.venv/bin/swebench eval verified -p results/inference/s4-mine/preds.json --run-id s4-mine -j 6
```

⚠️ 评测结果按 **run_id + instance_id 缓存**。改了 patch 想重评必须换 `run_id`，否则会直接复用上次的结果，
你会以为改动没生效。

## 二、决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| R1 | 测试命令**从实例自带的 `eval_script` 里抽**，不按仓库硬编码 | 75 条只有 5 种运行器前缀，但每种参数都不同（django 的 `--settings=test_sqlite --parallel 1`、sympy 的 `PYTHONWARNINGS=…`、sphinx 的 `tox --current-env -epy39 --`）。硬编码 = 把 7 个仓库的构建知识抄一遍 | 按 `repo` 查表 · 一律 `pytest`（三家跑不起来） |
| R2 | **把评分目标从前缀里剔掉** | 🔑 **方法论，不是工程细节**：留着等于告诉自己的 Agent grader 用哪些测试文件，而 mini baseline 没有这个信息，**两边数字就不可比了**。`tests/test_run.py` 在全部 75 条上断言没有泄露 | 保留（数字作废）· 干脆不给运行器（`run_tests` 就没法做成有类型的工具） |
| R3 | 顺手去掉 `--tb=no` | grader 不用看堆栈，Agent 要看。**只去这一个标志**，其余原样保留 —— 多改一个就多一处「我和评测环境不一样」 | 按仓库调参（滑坡） · 原样保留（astropy 那 3 条看不到堆栈） |
| R4 | 测试输出解析**直接用 harness 的 `PARSER_REGISTRY`**，不自己写 | 和评测同一份代码：`run_tests` 报的通过/失败与 grader 的口径不会有第二种说法。自己写解析器要覆盖 pytest / django runtests / sympy bin/test / tox 四种格式，而且写对了也只是追平 | 自己写正则 |
| R5 | 提取答案用 **`git diff`（只看已跟踪文件）**，不 `git add -A` | `apply_patch` 造不出新文件（DESIGN-tools P3，实测 25 条 gold 有 0 条新建文件），所以未跟踪文件只可能是构建产物或测试残留；`add -A` 会把它们一起卷进答案。**gold 回放 25/25 证明这个取法没漏东西** | `git add -A && git diff --cached`（mini 的做法，它允许 shell 所以必须这样） |
| R6 | **一条跑完就立刻落盘** `preds.json` 和 `summary.json` | 整批要跑几小时，中途挂掉不能把前面的结果一起丢掉；`--overwrite` 不给就自动跳过已有 trajectory 的实例，断了能续 | 全部跑完再写 |
| R7 | 单条实例的任何异常都**收敛成一行 summary**，绝不往上抛 | run.py 原规格：「单条失败了整批不停，记下来继续」。异常会进 `error` 字段和 trajectory，不会消失 | 抛出（一条坏实例毁掉整批） |
| R8 | 并行用 `ThreadPoolExecutor`，默认 **4** | 工作全在 `docker exec` 和 HTTP 上，是 IO 密集，线程够用；瓶颈是磁盘和内存不是 CPU（每条镜像约 1.5 GB，实测）。gold 回放用 5 并发跑 25 条无异常 | 多进程（没必要）· 串行（25 条要多花几倍时间） |
| R9 | trajectory 里**同时存 `steps` 和完整 `messages`** | `steps` 是归因用的结构化表；`messages` 是出了怪事时唯一能复原现场的东西。gold 回放的 25 份加起来 516 KB，真跑会大些但仍可入库 | 只存 steps（复原不了）· 只存 messages（归因要现算） |
| R10 | 评测产物从 `logs/evaluation/<run-id>/` 拷进 `results/evaluation/<run-id>/` | `logs/` 在 `.gitignore` 里（大而无人看）；`results/` 是入库的证据 | 直接入库 `logs/` |

## 三、实测（2026-09-16）

| 事实 | 值 |
| --- | --- |
| 运行器前缀的种类 | subset 25 + holdout 50 = **75 条，5 种**：django runtests 27 · `pytest -rA` 19 · sympy `bin/test` 14 · `tox --current-env -epy39 --` 12 · `pytest -rA -vv -o console_output_style=classic` 3 |
| 评分目标剔除 | **75/75 剔干净**。唯一的坑：`astropy__astropy-7336` 的测试补丁把 `py3_test_quantity_annotations.py` **改名**成评分目标，只取 `diff --git a/` 一侧看不到新名字 → 改成两侧都取 |
| gold patch 的形状（dev 25） | 66 个 hunk；改 1 个文件 19 条 / 2 个 3 条 / 3 个 1 条 / 4 个 2 条；**新建文件 0 条** |
| gold 回放（假模型，$0） | 25 条 / 5 并发 / **8.5 秒**；每条 0.6–2.8 秒 |
| gold 回放的评测 | **25/25 resolved**，0 infra failure、0 ambiguous、0 empty patch（`results/evaluation/gold-replay-s25/results.json`） |
| 产出体积 | 25 份 trajectory 共 516 KB |

🔑 **25/25 这个数的意义**：容器生命周期、六个工具、ReAct 循环的消息协议、patch 提取、`preds.json` 格式、
harness 吃不吃得进去 —— 任何一环有 bug 都到不了 25/25。**接模型之前的未知量只剩模型本身。**

## 四、跑哪个集 —— 还没花的那颗子弹

| 集合 | 条数 | 用途 |
| --- | ---: | --- |
| `subset_ids.txt` | 25 | 开发迭代，随便跑（S3 / S4 / S5 都用它） |
| `holdout_ids.txt` | 50 | **只跑一次，中途绝不许碰** |

碰了 holdout 就等于把它变成第二个 dev，那句「我报的数字没有在上面调过参」就不成立了。

**09-16 的状态：holdout 一次都没跑过**（09-06 用 gold patch 验过它可判定，那不调模型、也不看 Agent 的行为）。
gold 回放故意只跑 dev 25 条，就是为了不动它。

模型恢复之后的顺序：

```bash
set -a; source ~/.config/mini-swe-agent/.env; set +a

# S3：2 条跑通，只要求产出合法 patch，不要求 resolved
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s3-smoke --limit 2 --workers 2

# S4：10 条。判定 resolved > 0；若 0/10 就停下来逐条读 trajectory，绝不直接跑 25 条
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s4-mine --limit 10 --workers 4
.venv/bin/swebench eval verified -p results/inference/s4-mine/preds.json --run-id s4-mine -j 6

# S5：冻结 scaffold，dev 25 条正式跑；baseline 用 mini 跑同样 25 条
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s5-mine --workers 4
```

**冻结 scaffold 的意思**：S5 之前打一个 git tag，之后只许改文档不许改 `agent/`。
