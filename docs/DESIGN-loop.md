# loop.py / model.py 设计档案

> **✅ 2026-09-16 完成，Claude 写。** 09-15 grilling 定的分工里 `loop.py` 的控制流是本人手写的那一份；
> 09-16 本人要求「全部做完，明天统一学习整个项目」，改由 Claude 写、本人事后审。**面试口径按这条说**：
> ReAct 与 Plan-Execute 的取舍、上下文裁剪的停手判据、异常路径的阈值是本人定的，代码是 AI 写的。
>
> 配套：[`DESIGN-tools.md`](DESIGN-tools.md)（六个工具）· [`DESIGN-observation.md`](DESIGN-observation.md)（工具怎么说话）·
> [`DESIGN-run.md`](DESIGN-run.md)（怎么批量跑、怎么落盘）
>
> 代码里的 docstring 只写契约；决定、实测、纠错都在这里。引用写函数名，不写行号。

## 一、这一层管什么，不管什么

```
run.py          起容器、绑工具、读数据集、落盘         ← 认识 Docker 和 SWE-bench
  └─ loop.py    think -> act -> observe，终止与异常路径  ← 只认识「任务描述 + 工具 + 模型客户端」
       └─ model.py  litellm 的重试与错误分类            ← 只认识供应商
```

`run_episode` 的签名里没有 `DockerEnvironment`，也没有 `instance`：工具是**已经绑好 env 的可调用对象**，
模型是一个只有 `complete(messages, tools)` 的 `Protocol`。

🔑 **这个边界不是洁癖，是为了能不花钱把整条链跑通。** 换一个假客户端（`tests/gold_replay.py`）就能把
容器 → 六个工具 → 循环 → patch 提取 → `preds.json` → 官方 harness 全走一遍，答案已知（gold 25/25）。
09-16 实测：25 条 8.5 秒跑完，评测 **25/25 resolved**。链上任何一环有 bug 都到不了这个数。

## 二、为什么第一版是 ReAct 不是 Plan-Execute

1. **SWE-bench 任务在读代码之前无法规划** —— issue 文本不告诉你 bug 在哪，前置 plan 是空想。
   ReAct 的 think → act → observe 恰好匹配「探索式定位」。
2. **基线 mini-SWE-agent 也是 ReAct 系**，同类相比才干净。
3. 简单 = bug 少 = 更多时间留给评测。

> 🔑 **但不要把 Plan-Execute 丢掉，把它变成第一个受控变更。**
> 有了 ReAct 的 baseline 数字之后再加 plan 层，然后能说「我加了 plan 之后 resolved 从 X 到 Y」。
> **这比「我选了 ReAct 因为它简单」强一个数量级** —— 前者是测量，后者是偏好。

## 三、决策清单

| # | 决定 | 判据 | 否决 |
| --- | --- | --- | --- |
| C1 | **用供应商原生 function calling**（`tools=` + `tool_calls`），不自己定文本协议 | 自己写解析器要处理「模型把 JSON 写坏了」「代码块围栏不闭合」两类新失败，而「我写了个解析器」在面试里不值钱；原生调用的 `tool_calls` 直接进 trajectory，归因表不用先做一次文本还原。⚠️ **未实测**：中转站到 09-16 为止连不上（见 §六），这条要在第一次真跑时确认 | 文本协议（mini 的做法，它只有一个 bash 工具才划算） |
| C2 | **`finish` 是终止信号，不是第七个工具** | 执行计划 §四 说「不要加第 7 个工具」，指的是**能力**工具；「主动完成」是三个终止条件之一，必须有落点。它不改变世界，也不返回观察 | 「没有 tool_call 就算做完」（模型有时只是闲聊，会误判完成） |
| C3 | 工具表由 `build_tool_schemas(target_hint)` 生成，`run_tests` 的目标写法按仓库替换 | django 要点号模块名、其余要文件路径，模型不可能凭空知道；提示按**运行器**给，不引用任何具体实例，所以不泄露评分目标（DESIGN-tools T9） | 写死一种写法 · 把实例的评分目标当例子（泄露） |
| C4 | 三个终止条件：**步数 40 / 成本 $0.50 / 主动 `finish`**，另加墙钟 1800 秒 | mini 的配置是 `step_limit: 250` / `cost_limit: 3.`【实测 `swebench.yaml:112-113`】，但 S2 实测它实际只用了 **11 步和 20 步**。40 步给了 2 倍余量又不至于烧钱；$0.50 是实测单条 $0.03 的 **16 倍**。墙钟是 mini 没有的：`environment.execute` 的超时只杀宿主机上的 `docker exec` 客户端，容器里的进程还活着（DESIGN-environment §七），没有墙钟上限一条卡住的实例能拖垮整批 | 抄 mini 的 250 步（跑不到，白等）· 不设墙钟 |
| C5 | 停止原因是**枚举**（`StopReason`），进 trajectory 和 summary | 它是归因表「Agent 侧」那一列的行标签：`max_steps` 多 = 步数不够或它在绕圈，`tool_error_streak` 多 = 工具契约没说清楚，两者的改法完全不同 | 存一段自由文本 |
| C6 | 每一步记一行 `StepRecord`：工具名、参数、状态、失败类别、耗时、成本、token、**响应里的模型名** | 学习验证协议要求「输入 / 输出 / 延迟 / 成本记录」；归因要能在不看代码的情况下读出「它在第几步开始瞎撞」 | 只存最终 patch（归因时无从下手） |
| C7 | 模型不调工具也不 `finish` → **提醒一次，连续两次就停** | 无限提醒会把步数烧光还什么都没做；提醒一次能救回「模型先说了一段话再动手」这种常见情况 | 一次就停（太急）· 一直提醒（烧钱） |
| C8 | 上下文裁剪只做两件最粗的事：**工具输出截断**（在工具里，`MAX_CONTENT_CHARS`）+ **保留最近 5 条完整观察**，更早的只留 `<summary>` 那一行 | 执行计划 §四 的停手判据：能跑完一条 hard 实例而不撞上下文上限就停手。**第一版明确不做**语义压缩 / summary 模型 / 三层压缩 / 历史向量检索 —— 上下文管理只在它成为瓶颈时才有价值，没撞上限就做精细压缩是在优化一个不存在的问题，而且**把「为什么加这一层」的答案提前销毁了** | 一上来就三层压缩 |
| C9 | 裁剪**改 tool 消息的 content，不删消息** | OpenAI 协议要求每个 `tool_call` 都有配对的 `tool` 回复，删请求方的消息会让下一轮请求非法。留下的那一行就是 `<summary>` —— 工具本来就设计成「只读这一行也知道个大概」（observation 决定 15–19） | 直接删早期消息 |
| C10 | 模型把调用写坏了（工具名不存在、参数不是 JSON 对象、参数名对不上签名）→ **回一个 `INVALID_ARGUMENT` 观察**，不抛异常 | 这是模型的错，和工具内部的参数校验同一类；抛异常等于用一次模型失误换掉整条实例 | 抛异常 · 静默跳过（模型不知道发生了什么） |
| C11 | 三条异常路径都有**降级**而不是重试到死：① 工具连错 5 次 → 停；② 同一文件 `apply_patch` 失败 3 次 → **不再进容器**，直接回「这个文件被封了」；③ 工具自己抛异常 → 记成 `IO_ERROR` 继续 | ② 是 DESIGN-tools §四 apply_patch 错误契约里写死的停止条件，工具是无状态函数记不住次数，必须由这一层落实；**改成功一次就清零**，否则前面失败过的文件会被永久拉黑（`tests/test_loop.py` 两条都断言了） | 无限重试 · 失败即停整条实例 |
| C12 | 上下文超限（`ContextWindowExceededError`）→ **先把 `keep_full` 降到 1 再试一次**，仍然不行才放弃 | 这是唯一一个「再试一次真的可能成功」的错误，因为我们改变了请求本身 | 直接放弃（浪费前面所有步数） |
| C13 | 模型叫不动 → 连接类错误**指数退避重试 4 次带抖动**，其余（认证错、请求体非法）直接判死 | S2 实测中转站抖过一次 `ServiceUnavailableError`，litellm 自动重试后恢复；但重试一个 400 只是把时间烧掉。抖动是因为整批并行时几个 worker 会同时被限流，同步重试会再撞一次 | 一律重试 · 一律不重试 |
| C14 | 模型客户端单独一个 `model.py`，`loop.py` 不 import litellm | 测试注入假客户端时不用装 litellm，也不会被它的全局状态（`drop_params`）影响 | 写在 loop 里 |
| C15 | **把响应里的 `model` 字段记进每一步** | 执行计划 §八 的悬置项：「中转站是否真的给的是 luna」——09-06 发现 `preds.json` 里的 `model_name_or_path` 是**请求的名字不是返回的名字**，无法证伪。记下 `response.model` 就有了证据链；`summary.json` 里按实例汇总成 `returned_models` | 只记请求的名字（等于没记） |
| C16 | system prompt 里写死「**There is no shell**」 | DESIGN-environment §七 压下来的义务是「告诉模型 `cd` 不持久」。比解释 `cd` 更彻底的是让模型根本没有发 shell 命令的途径 —— 六个工具每次都是新进程，压根没有「当前目录」这个概念 | 解释 `cd` 的行为（多一条它要记住的规则） |
| C17 | prompt 里写死「不许改测试」「空 diff 得零分」「改病因不改症状」 | 这三条各自对应一类失败：改测试会被 harness 的 `git checkout` 抹掉、空 diff 直接 0 分、只改症状是失败模式 2（最大的一桶）。**这是 prompt 里唯一允许写的任务知识**，因为它讲的是评分规则，不是这道题的答案 | 写「可能在 X 文件里」这类提示（泄露答案） |

## 四、`model.py` 的错误分类

| litellm 抛什么 | 怎么处理 | 为什么 |
| --- | --- | --- |
| `ContextWindowExceededError` | 转成 `ContextOverflow`，交给循环裁历史 | 改请求可能成功 |
| `RateLimitError` `APIConnectionError` `ServiceUnavailableError` `InternalServerError` `Timeout` `APIError` | 退避重试 4 次（2ⁿ + 抖动），用尽转 `ModelUnavailable` | 中转站抖动是实测过的 |
| 其余（认证、请求体非法…） | 直接转 `ModelUnavailable` | 重试不会变对 |
| `completion_cost` 算不出来 | 成本记 0，继续 | 不为了一个读数中断实例；`returned_models` 那一列仍能发现异常 |

`_RETRYABLE` 用 `getattr(litellm, name, None)` 取，取不到的类名自动跳过 —— litellm 改过好几次异常层级，
写死 import 会在升级时直接 `ImportError`。

## 五、测得到的和测不到的

`tests/test_loop.py`（22 条，假客户端 + 假工具，秒级）覆盖：

- 三个终止条件各一条 + 墙钟一条
- 异常路径六条：连错即停、成功清零、同一文件三次拉黑、拉黑后不再进工具、成功一次解封、工具抛异常不炸
- 模型写坏调用三条：工具名不存在、参数不是 JSON、参数名对不上签名
- 上下文：裁剪保留最近 K 条、消息条数与角色序列不变、`keep_full=0`、超限后先裁再试
- 工具表：目标写法提示进到了模型看到的 schema、七个名字齐全

**测不到的（要等第一次真跑）**：

- 🔴 **中转站支不支持 function calling** —— C1 整条建立在这上面。09-16 连不上，未验证
- 🔴 **`keep_full=5` 够不够跑完一条 hard 实例而不撞上下文上限** —— C8 的停手判据就是这一条，
  没撞上限之前不许做更精细的压缩
- 🔴 **40 步够不够** —— mini 用了 11 和 20 步，但那是它的工具粒度；六个有类型的工具可能更费步数
- `returned_models` 到底回什么

## 六、⚠️ 09-16 的阻塞：模型 API 连不上

| 检查 | 结果 |
| --- | --- |
| 本机 DNS 解析 `hgapi.dieqiyun.top` | ❌ 超时；`api.github.com` 正常 |
| 公共 DNS（8.8.8.8 / 1.1.1.1 / 223.5.5.5） | ❌ 全部超时（这台机器出站 53 端口被拦） |
| DNS over HTTPS（`dns.google/resolve`） | ✅ `38.34.175.121`，**域名活着** |
| 直连 `38.34.175.121:443` | TCP 连得上，**TLS Client Hello 之后被 RST** |
| 经本机 Clash（127.0.0.1:7890） | ❌ 同样 TLS 失败（exit 35） |
| Tailscale | 在跑，但没有可用的 exit node |

【判断】域名解析得到、TCP 通、**发出 SNI 之后才被重置** —— 这是按域名拦截的特征，不是服务端挂了。
所以 S3 / S4 / S5 三个要调模型的阶段全部卡住，与 scaffold 本身无关。

**恢复之后要跑的第一条命令**（其余见 `DESIGN-run.md` §四）：

```bash
cd ~/swe-bench-eval
set -a; source ~/.config/mini-swe-agent/.env; set +a
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s3-smoke --limit 2 --workers 2
```
