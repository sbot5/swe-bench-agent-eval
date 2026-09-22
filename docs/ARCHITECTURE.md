# 架构

> 从 `README.md` 拆出来（2026-09-22）。README 只留一句话的架构，细节在这里。
> 每个模块另配一份决策档案 `DESIGN-<模块>.md`（决策清单 · 已纠正的错误 · 实测数据）。

## 一个 ReAct 循环，套在一个断网的容器上

```
                    ┌─────────────────────────────────────────┐
   一条 SWE-bench   │  run.py  批量入口                        │
   实例 = 一个      │  起容器 → 绑工具 → 跑循环 → 提取 patch    │
   Docker 容器      └────────────────┬────────────────────────┘
                                     │
                     ┌───────────────▼───────────────┐
                     │  loop.py  ReAct 循环           │
                     │  三个终止条件 + 上下文裁剪      │
                     │  不认识 Docker，也不认识        │
                     │  SWE-bench —— 只认识消息和工具  │
                     └───┬───────────────────────┬───┘
                         │                       │
          ┌──────────────▼──────┐   ┌────────────▼─────────────┐
          │ model.py            │   │ tools/  七个工具          │
          │ litellm 客户端       │   │ 一工具一模块              │
          │ 重试 / 错误分类      │   │                          │
          └─────────────────────┘   │ 只读 ──────────────┐     │
                                    │  read_file         │     │
                                    │  list_files        │     │
                                    │  search_code       │     │
                                    │  git_diff          │     │
                                    │                    │     │
                                    │ 能改东西 ──────────┤     │
                                    │  apply_patch       │     │
                                    │  run_tests         │     │
                                    │  run_python        │     │
                                    └──────────┬─────────┘     │
                                               │               │
                     ┌─────────────────────────▼──────────┐    │
                     │ environment.py  执行层              │    │
                     │ 一实例一容器，docker exec 进去执行   │    │
                     │ 容器 --network=none（没有网卡）     │    │
                     └────────────────────────────────────┘    │
                                                               │
          所有工具的返回都过同一个形状 ◄─────────────────────────┘
          observation.py：状态 / 失败类别 / 渲染 / 截断

          report.py  跑完之后按失败模式分桶，出归因表
```

设计档案：[observation](DESIGN-observation.md) · [environment](DESIGN-environment.md) ·
[tools](DESIGN-tools.md) · [loop](DESIGN-loop.md) · [run](DESIGN-run.md)。

## 三个值得说的设计决定

- **`observation.py` 是第一个写的。** 七个工具的返回形状先统一死，再写工具。
  好处是**失败类别**（不是「报错字符串」）成了一等公民，归因表才有得分桶。
- **`loop.py` 不认识 Docker，也不认识 SWE-bench。** 它只认识「消息」和「工具」，
  所以换成别的任务集不用动循环。
- **容器没有网卡。** 这是后来才加的，而且是**被数据逼出来的** —— 见 [`DATASET.md`](DATASET.md) 的 P1。

## 整条链怎么在不花一分钱的情况下证明是对的

把 25 条 gold patch 的每个 hunk 拆成一对 `(old_string, new_string)`，当成一个**假模型**喂给循环
（[`tests/gold_replay.py`](../tests/gold_replay.py)）—— 容器、七个工具、ReAct 消息协议、patch 提取、
`preds.json` 格式、官方 harness 全部真跑，只有「模型该改哪里」被换成了已知答案。

| 结果 | 值 |
| --- | --- |
| 25 条实例 / 66 个 hunk | **66/66 一次打上，零失败编辑**，8.5 秒（5 并发） |
| 走官方 harness 评测 | **25/25 resolved**，0 infra · 0 ambiguous · 0 empty patch |

**这个数的意义**：链上任何一环有 bug 都到不了 25/25。**接模型之前的未知量只剩模型本身。**

顺带量到一件事：git 默认三行上下文的 search/replace 锚点，在 66 个真实修复 hunk 上**全部唯一** ——
这是「`apply_patch` 不提供 `replace_all`」这个决定的**实测依据，不是假设**。

它后来还当了**回归闸门**：每次改 scaffold 先跑一遍，25 条 patch 与上次**逐字节相同**才开跑
（改工具、加 `run_python`、拆包重构各用过一次），所以那些改动**不必重跑评测**就知道没碰坏链路。

> ⚠️ **这条闸门有一个边界**：假模型**不看工具表**【原文 `tests/gold_replay.py:72-75`】，
> 所以它证不了「工具集每步可变」（C23）这类改动 —— 它只保证「不传 `tool_policy` 时老路径没变」。

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
  staged.py         分阶段 Round（P4）：段边界、段指令、段→工具表映射、指纹

tests/
  fake_env.py           假执行环境，按脚本回 ExecResult，不起容器
  gold_replay.py        把 gold patch 拆成 apply_patch 调用，当假模型驱动整条链
  smoke_gold_replay.py  端到端冒烟的入口（$0）
  test_*.py             220 条；真容器那 21 条打了 slow marker，默认跳过

results/
  evaluation/<run_id>/results.json       评测结论
  evaluation/<run_id>/attribution.md     badcase 归因表（report.py 产出）
  inference/<run_id>/preds.json          Agent 产出的 patch
  inference/<run_id>/*.traj.json         完整决策链（badcase 归因就靠它）
  inference/<run_id>/summary.json        每条的停止原因、步数、成本、延迟、返回的模型名
```

不入库的：`SWE-bench/`（第三方 clone）、`.venv/`、每实例的 `test_output.txt` 与
`run_instance.log`（几百 MB，只在排查单条时才看）。
