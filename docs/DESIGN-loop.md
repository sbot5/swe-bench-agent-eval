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
| C1 | **用供应商原生 function calling**（`tools=` + `tool_calls`），不自己定文本协议 | 自己写解析器要处理「模型把 JSON 写坏了」「代码块围栏不闭合」两类新失败，而「我写了个解析器」在面试里不值钱；原生调用的 `tool_calls` 直接进 trajectory，归因表不用先做一次文本还原。🔴 **09-16 实测：当前中转站不支持** —— 请求体里只要出现 `tools` 字段就静默挂起（`tool_choice:"none"` 同样挂），见 §七。**被否掉的是这个供应商，不是 C1 本身**；换一个支持 function calling 的供应商，C1 原样成立 | 文本协议（mini 的做法，它只有一个 bash 工具才划算） |
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
| C16 | ~~system prompt 里写死「**There is no shell**」~~ ⚠️ **09-18 作废，被 C18 取代**（加了 run_python，这句变成假话）。原判据仍抄在这里，因为它解释了 C18 为什么要换一种方式满足同一条义务： | DESIGN-environment §七 压下来的义务是「告诉模型 `cd` 不持久」。比解释 `cd` 更彻底的是让模型根本没有发 shell 命令的途径 —— 六个工具每次都是新进程，压根没有「当前目录」这个概念 | 解释 `cd` 的行为（多一条它要记住的规则） |
| C17 | prompt 里写死「不许改测试」「空 diff 得零分」「改病因不改症状」 | 这三条各自对应一类失败：改测试会被 harness 的 `git checkout` 抹掉、空 diff 直接 0 分、只改症状是失败模式 2（最大的一桶）。**这是 prompt 里唯一允许写的任务知识**，因为它讲的是评分规则，不是这道题的答案 | 写「可能在 X 文件里」这类提示（泄露答案） |
| C18 | **删掉「There is no shell」，改写死「容器没有网」**（09-18，取代 C16） | 加了 `run_python` 之后 C16 那句是**假话** —— Python 能 `subprocess.run`，模型有 shell。prompt 撒谎有两重代价：面试官一问就穿；模型信了就不敢用 run_python。DESIGN-environment §七 那条「告诉模型 `cd` 不持久」的义务改由 run_python 的工具描述承担（「Nothing is remembered between calls」）。**新写死的那句（没有网）是真的**，负对照验过（DESIGN-tools §四 Y2） | 留着那句不改（撒谎）· 只删不补（模型不知道联网会失败，会白烧几轮去试） |
| C19 | 工作流里**插一步「先用 run_python 复现，再动手」**，并写死「改文件用 apply_patch 不用 run_python」 | 前半是 P2 要测的假设本身：P1 量出「跑复现脚本」是三方对照里唯一没被断网消掉的能力差，而 A 组 9 条的病是 `apply_patch=0`「从未动手」——给它一个**比继续 read_file 更具体的第一步**。后半是防 run_python 绕过 apply_patch：绕过去既没有锚点唯一性检查，也让归因表里的 `apply_patch` 计数失真（⑪ 全靠这个量判别的） | 不插复现步（那就没测到 P1 量出的那条能力差）· 插了但不禁止用它改文件（`apply_patch=0` 这个判别量当场失效） |
| C20 | **把缓存/推理三个读数落进每一步**（`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` / `completion_tokens_details.reasoning_tokens`），**取不到时记 `None` 不记 `0`**（09-18，㉖ 的修法） | `EVAL-P2.md` §5.4 推「P2 贵一倍是前缀缓存失效」只能靠**三跑外推 + 独立探针**，因为轨迹里没有这一列 —— 而 DeepSeek 一直在返回它。**`None` 和 `0` 必须分开**：0 是冷跑第一次的**真读数**，None 是供应商没给；混成 0 就是 `cost=$0.0000` 那个假读数的翻版，那个坑的代价是至今止损只剩 `--max-steps`。09-18 离线验过（$0）litellm 1.100 的访问路径：`Usage.__init__` 里有 `## DEEPSEEK MAPPING ##` 把 hit 归一化进 `prompt_tokens_details.cached_tokens`，未识别字段在结尾 `for k, v in params.items(): setattr(...)` 原样挂上；**负对照下是属性缺失、details 对象为 None，不是 0** | 只记 `prompt_tokens`/`completion_tokens`（现状，等于没有 —— 这就是㉖）· 取不到记 0（假零，正是要修的病）· 用 `prompt_tokens - hit` 反推 miss（凭空造一个没人返回过的数，⚠️ 违反「不填补」）· 顺手把 `total_tokens`、`text_tokens` 一起落（这次只解决命中率一个问题） |
| C21 | **把 `reasoning_content` 落进每一步**，口径同 C20：**供应商没给记 `None`，给了空串记 `""`**；**不截断、不回传**（09-20，㉖ 同型仪器） | `thought` 那一列取的是 `message.content`，而**带 tool_calls 的轮 content 就是空串**【原文 `scripts/c21_reasoning_probe.py` 09-20 实测：`content=''`、`tool_calls` 1 条、`reasoning_content` 有内容】—— `django-11138` 57 步 `thought` 全空却 38/40 轮在推理（14,042 token），这两件事是同一个机制。P3 已经排掉两个候选（不是「复现跑不起来」、不是「没告诉它可以放弃」），剩下那问「**它凭什么认为自己还没复现完**」在 prompt 层问不出来（㊳：prompt 里加一条规则 ≠ 系统里多了一条规则），只能去读它到底想了什么。**照 ㉛ 逐环点名**，四环分开验：环1 provider 原始 JSON 的 message 里**有** `reasoning_content` 键（带 tools 与不带 tools 两组都有 —— 我方每次调用都带 tools，只测不带的那组等于没测）· 环2 litellm 1.100 透得出来（`common_utils.py:1715` 有键就原样返回 → `convert_dict_to_response.py:688` 传进 `Message`）· 环3 **负对照探针没测到**（两组都拿到了推理文本），由单测 + gold 回放 66 步全 `None` 补上 · 环4 原始 JSON 里就有这个键 → provider 直接给的，**不是** litellm 从 content 的 `<think>` 里剥的（那是 `_parse_content_for_reasoning` 的另一条分支，口径不同）。**体量先估后加**（P1 那两条 204MB traj 的教训）：`p2-rerun` 实测 256,176 reasoning token × 3.4 字符/token（探针实测的上界）≈ **+0.87MB**，一跑 4.1→5.0MB、最坏单条 +107KB → 不必截断 | 不做（那就答不了「为什么不动手」，而 P3 已证 prompt 层问不出来）· **并进 `thought` 那一列**（两个来源混成一列，以后分不开「模型没写 content」与「供应商没给 reasoning」，正是 C20 要避免的病）· **落盘前截断**（P1 的教训是「截断只保护上下文、不保护落盘」，不是「都得截断」；体量已实测可接受，而截断掉的正是本次要看的东西）· **回传给模型当上下文**（DeepSeek 明确不收；且改动送出去的 messages = 改 prompt 指纹，㉕ 那棵前缀缓存树作废，后续成本全不可比）· 顺手把 `thinking_blocks`／`reasoning_items` 一起落（同 C20，这次只解决一个问题） |

⚠️ **C18/C19 的效果现在【未知】**：P1 只证明了能力差存在，**没有**证明补上它就能解掉那 9 条。
⑦⑨ 的方差要求重复跑才压得住，所以下一次跑完**不许**拿单次结果说「run_python 提升了 X 分」。

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

`tests/test_loop.py`（**23 条**，假客户端 + 假工具，秒级；原文写 22 条，见「已纠正的错误」第三处）覆盖：

- 三个终止条件各一条 + 墙钟一条
- 异常路径六条：连错即停、成功清零、同一文件三次拉黑、拉黑后不再进工具、成功一次解封、工具抛异常不炸
- 模型写坏调用三条：工具名不存在、参数不是 JSON、参数名对不上签名
- 上下文：裁剪保留最近 K 条、消息条数与角色序列不变、`keep_full=0`、超限后先裁再试
- 工具表：目标写法提示进到了模型看到的 schema、七个名字齐全
- 落盘的读数两条（09-18 随 C20 加）：缓存三列一路走到 `StepRecord`（`run.py` 是 `asdict(step)` 落盘的，
  到这儿就等于到了 traj）；假客户端不给这三列时落 `None` 而不是 0
- **`reasoning_content` 三条（09-20 随 C21 加）**：落到 `StepRecord` 且 `asdict` 带得出来（这条刻意把
  `content` 设成空串 —— 带 tool_calls 的轮真实形态就是这样）· 不给时落 `None` 而不是 `""` ·
  **它绝不出现在发回给模型的 messages 里**。最后一条守的是一个结构性质：`loop` 构造 assistant 历史时
  **逐字段**取 `content` 与 `tool_calls`，所以新列不会漏进去；DeepSeek 不收回传的 `reasoning_content`，
  哪天有人图省事改成「把整个 reply 塞回历史」，这条会当场红

`tests/test_model.py`（**12 条**，09-18 随 C20 新建 7 条、09-20 随 C21 加 5 条，$0 不发请求）
覆盖 `_to_reply` 的读数提取：

- 主路径走 **litellm 自己的响应转换器**（`convert_to_model_response_object`），不是我手搓一个 usage 对象 ——
  ㉖ 那个坑正是「裸 HTTP 探针证明了 API 会返回，但没人验过 litellm 透不透出来」，手搓就等于把同一个洞再挖一遍
- 负对照（供应商不给 → 三列全 `None`）· 真零（`hit=0` 要留成 0）· 只给归一化字段 `cached_tokens` 也读得到 ·
  连 `usage` 都没有时不炸 · `_first_int` 排掉 `bool`（它是 `int` 的子类，会静默变成 1/0）
- **miss 没有归一化字段**，所以只给 `cached_tokens` 时 `cache_miss_tokens` 就是 `None`，不许拿 `prompt - hit` 补
- C21 五条同样走转换器：主路径读得到 · **`content` 空串而推理不空**（本次改动的全部理由，用的是
  探针实测的消息体形状）· 负对照落 `None`（**探针那一环没测到，靠这条补**）· 空串是真读数不许折叠成
  `None` · `_first_str` 排掉非字符串

**测不到的（要等第一次真跑）**：

- ✅ **中转站支不支持 function calling** —— 09-16 已测：**不支持**，失败方式是静默挂起而不是报错，见 §七
- 🔴 **`keep_full=5` 够不够跑完一条 hard 实例而不撞上下文上限** —— C8 的停手判据就是这一条，
  没撞上限之前不许做更精细的压缩
- 🟡 **40 步够不够** —— 09-16 S3′ 实测 2 条（`deepseek-flash`）：`sphinx-9698` 用 18 次 API 调用就
  `finished` 并交出 1191 字符的 patch；`django-13512` **40 次用满仍是空 patch**
  （`stop_reason=max_steps`，`tool_errors` 只有 2 → 不是工具坏了，是探索没收敛）。
  1/2 撞上限，**样本太小，还不能定要改成多少**，等 S4 的 10 条再看。
  ⚠️ `steps` 与 `api_calls` 不是一回事：那条 53 步里只有 40 次 API 调用，**`max_steps` 限的是后者**。
- ✅ **`returned_models` 到底回什么** —— 09-16 实测 `["deepseek-flash"]`，与请求的名字对得上，C15 生效
- ✅ **缓存命中率** —— C20 已经把仪器装上并离线验过访问路径，但**真实命中率要等下一次真跑才拿得到**。
  在那之前 `EVAL-P2.md` §5.4 的 88~89% 仍然只是**外推 + 探针**，不许当直读数引用。
  **09-19 第一次直读：58.8%**（764 轮全部有读数、每轮 hit + miss = prompt），88~89% 不成立；
  **未命中的 97% 出在 C8 开始折叠之后** —— `trim_messages` 每轮改写发出去的视图，前缀从新折叠的那条观察处断开。
  这是 C8 的一个成本代价，C8 当初的判据（上下文上限）里没有这一维。见 `EVAL-P2-rerun.md` §四
- 🔴 **A 组「从未动手」的模型到底在想什么** —— C21（09-20）把仪器装上并逐环验过取数路径，
  但**推理文本本身要等下一次真跑**。09-20 的探针只回答了「这个字段拿不拿得到」，
  **没有**回答「它凭什么认为自己还没复现完」。在拿到真读数之前，
  `EVAL-P3-prompt.md` §九 的【未知】②仍然是【未知】，不许拿 `thought` 全空当作「它没想」

## 六、⚠️ 09-16 的阻塞（一）：挂着学校 VPN 时模型 API 连不上 —— **已解除**

**结论：跑评测前先断开 Monash VPN。** 原因是本人当场确认的，不是推断。

> 09-16 晚些时候复测：DNS、TLS、`/v1/models` 全部正常，裸 chat 请求 2 秒返回 200 ——
> **这一层确实解除了**。但它挡住的后面还有第二层，见 §七。本节的排查次序仍然有效，
> 症状不同（那次是 DNS 超时 + TLS RST，§七 是 HTTP 层 503 与静默挂起），别混。

排查过程留档（同类症状下次照这个次序查）：

| 检查 | 结果 |
| --- | --- |
| 本机 DNS 解析 `hgapi.dieqiyun.top` | ❌ 超时；`api.github.com` 正常 → **不是断网** |
| 公共 DNS（8.8.8.8 / 1.1.1.1 / 223.5.5.5） | ❌ 全部超时 → 出站 53 端口也被接管了 |
| DNS over HTTPS（`dns.google/resolve`） | ✅ `38.34.175.121` → **域名活着，服务端没挂** |
| 直连 `38.34.175.121:443` | TCP 连得上，**TLS Client Hello 之后被 RST** → 按域名拦，不是按 IP |
| 经本机 Clash（127.0.0.1:7890） | ❌ 同样 TLS 失败（exit 35） → 代理没绕过去 |
| Tailscale | 在跑，但没有可用的 exit node |

🔑 **线索一直摆在 `/etc/resolv.conf` 里**：`search monash.edu tailc797d0.ts.net` ——
WSL 继承了 Windows 的 DNS 后缀，说明当时挂着学校 VPN。查了六项才想到看这一行。
**下次先看 `resolv.conf` 的 search 域和默认路由，再去 curl。**

S3 / S4 / S5 三个要调模型的阶段因此全部卡住，**与 scaffold 本身无关**。

**恢复之后要跑的第一条命令**（其余见 `DESIGN-run.md` §四）：

```bash
cd ~/swe-bench-eval
set -a; source ~/.config/mini-swe-agent/.env; set +a
PYTHONPATH=. .venv/bin/python -m agent.run --run-id s3-smoke --limit 2 --workers 2
```

## 七、🔴 09-16 的阻塞（二）：中转站是「已经装好 Codex 的 agent」，两个端点都不透传 tools

**三条结论**：

1. **只要请求体里出现 `tools` 字段，请求就静默挂起** —— 不返回也不报错，吃满超时。
   `chat/completions` 与 `responses` **两个端点都一样**，所以「换端点」不是退路。
2. **它转发的不是裸模型**，是一个预置了完整 Codex system prompt（约 4.4k token）的 agent。
   ——【原文】`responses` 响应体的 `instructions` 字段直接写着，见下。
3. **站点可用性约 89%**，有分钟级低谷，但 `model.py` 的退避重试吃得掉 —— **这一条不是阻塞**。

第 1 条**与 scaffold 无关**，也与 §六 的 VPN 无关（这一轮全程没挂 VPN，DNS 与 TLS 正常）。

**一条旁证**：S2 的 mini-SWE-agent baseline 在同一个中转站上跑通过 2 条【原文 执行计划 §五】——
而 mini 用的是**文本协议**（它只有一个 bash 工具），不是 function calling。
站点能用，透不过去的就是 `tools`。

### 怎么测出来的（可复现）

探针留在 WSL 家目录（不入库）：`~/probe_raw.sh`（四组二分）· `~/probe_c1.sh`（健康对照）·
`~/probe_c1b.sh`（同消息对照 + `tool_choice:none` + responses 端点）· `~/probe_uptime.sh`（可用性采样）。
凭据映射在 `~/env.sh`：Monash 侧 `.env` 用 `API_KEY`/`BASE_URL`，litellm 认的是
`OPENAI_API_KEY`/`OPENAI_BASE_URL`，且 `BASE_URL` 不带 `/v1`，要补。

判定的关键是**每次带 tools 的请求前后都夹一条裸请求**，否则会把站点抖动误读成 tools 的问题。

决定性的一轮【原文 `~/probe_c1b.sh` 输出，09-16】—— messages 完全相同，唯一变量是 `tools`：

| # | 请求 | 结果 |
| --- | --- | --- |
| 0 | 健康探测（裸） | 200 |
| A | 同一条消息，**无** tools | **200**，2.9s |
| B | 同一条消息，**加** tools（`tool_choice:"auto"`） | **000，挂满 90s** |
| C | 同一条消息，无 tools（站点还活着吗） | **200**，1.9s |
| D | 同一条消息，加 tools 但 **`tool_choice:"none"`** | **000，挂满 90s** |

**D 是决定性的**：`none` 意味着模型不许调工具，所以挂死的不是「模型调用工具」这个动作，
而是**转换层看到 `tools` 字段本身**。A/C 前后夹住，证明那 90 秒里站点是健康的。

同样的模式在 `gpt-5.6-luna` 和 `gpt-5.6-terra` 上都复现过，流式（`stream:true`）一样挂。

`responses` 端点复现得更干净【原文 `~/probe_resp2.sh` 输出，5 轮】—— 每轮事前健康检查都是 200：

| 轮 | 健康(事前) | responses + tools | 健康(事后) |
| ---: | --- | --- | --- |
| 1 | 200 | **000，挂满 60s** | 000 |
| 2 | 200 | **000** | 502 |
| 3 | 200 | **000** | 502 |
| 4 | 200 | **000** | 503 |
| 5 | 200 | **000** | 502 |

5/5 复现。与 `chat/completions` 不同的是，这里事后健康检查也多半跟着挂
——【判断】responses 的挂起请求会占住上游连接，`chat/completions` 那边不会。没有进一步验证。

### 为什么这是最难缠的失败方式

`model.py` 的 `_RETRYABLE` 含 `Timeout`，而 `REQUEST_TIMEOUT=180`、`MAX_ATTEMPTS=4`。
【推算】一条挂起的请求要走完 180×4 + 退避（2+4+8+抖动）≈ **12 分钟**才判死，不是立刻报错。
25 条 / 4 workers ≈ 7 批 → **约 84 分钟跑完，0 resolved**。
这正是交接单那句「别等跑完 10 条才发现」要防的情况。

### 顺带测到的两件事

- **中转站每次请求注入约 4.4k token 的前缀**：`"Say OK."`（约 3 token）报
  `prompt_tokens=4389`、`cached_tokens=3802`【原文 响应体 usage，多次一致】。

  **那段前缀是什么，`responses` 端点直接给了答案** —— 响应体的 `instructions` 字段【原文】：

  > `You are Codex, a coding agent based on GPT-5. You and the user share one workspace, and your`
  > `job is to collaborate with them until their goal is genuinely handled.\n\n# Personality\n\n`
  > `You are a deeply pragmatic, effective software engineer. ...`

  所以这个分组转发的**不是裸模型，是一个已经装好 Codex 的 agent**（模型列表里那个
  `codex-auto-review` 也是佐证）。两件事因此成立：① `tools` 透不过去讲得通；
  ② **它和 C16 直接冲突** —— 我们的 system prompt 写死「There is no shell」，
  而 Codex 那段假定自己有 shell、和用户共享 workspace。
  Responses API 的 `instructions` 参数本可覆盖它，09-16 测这一条时撞上 503，**没验成**。
  执行计划 §五 的成本估算也要按这 4.4k 前缀重算。
- **`returned_model` 对得上**：请求 `gpt-5.6-luna`，响应 `"model":"gpt-5.6-luna"`【原文 响应体】。
  这是 C15 那个悬置项（「中转站是否偷换模型」）的第一条正面证据，但只在裸请求下验过。

### 退路（还没选）

| 选项 | 代价 | 备注 |
| --- | --- | --- |
| **换支持 function calling 的供应商** | 改 `.env` 两行 | ✅ **09-16 选了这条，当天验通**（见下）。C1、C10 与整条 trajectory 结构一行没改 |
| 退回文本协议 | 一天 | C1 早写明的退路。要新写解析器 + 处理两类新失败，且「我写了个解析器」在面试里不值钱。**没用上** |
| ~~走 `/v1/responses` 端点~~ | —— | ❌ **已否**：5 轮全部挂起，两个端点一样不透传 tools |
| ~~换中转站的其他分组~~ | —— | ❌ **已否**（本人 09-16）：只有 0.1x / 0.15 两个池子，都是 Codex 的；没有纯 chat 分组 |

**换供应商的绝对成本很小**：执行计划 §五 实测单条约 $0.03、25 条约 $0.85，原话是
「成本不再是这个项目的约束」。倍率贵 10 倍在这个用量下也只是几美元。

### 09-16 的解法：换 DeepSeek，C1 当天验通

本人 09-16 在 `.env` 里换成 DeepSeek 官方端点（`https://api.deepseek.com`）。**同一组探针，结果反过来**：

| 探针 | 中转站 | DeepSeek |
| --- | --- | --- |
| 裸请求 | 200 | 200 |
| `"Say OK."` 的 `prompt_tokens` | **4389**（注入 Codex prompt） | **33**（干净） |
| `chat/completions` + tools | **挂起** | **200**，`prompt_tokens` 288（工具 schema 正常进 prompt） |

再用**真实路径**（`LiteLLMClient` + `build_tool_schemas()` 的 7 个工具）验一次【原文 `~/probe_fc.py` 输出】：

```
returned_model='deepseek-flash'
tool_calls=1
  - name='read_file' args={'path': 'setup.py'} error=None
C1_VERDICT=SUPPORTED
```

**C1 原样成立**，`loop.py` / `tools.py` 一行没改。

三条随之而来的事实：

- **DeepSeek 现在的模型是 `deepseek-flash` 和 `deepseek-v4-pro`**【原文 `/v1/models`，09-16】，
  不是文档里常见的 `deepseek-chat` / `deepseek-reasoner`。**用前先打一次 models 接口**
  （执行计划 §五 那个「先用免费的 models 接口确认模型真的存在」的动作，这次又救了一回）。
- 🔴 **`cost_limit` 这层保护失效了**：litellm 1.100.0 的价格表不认识 `deepseek-flash`，
  `completion_cost()` 抛异常 → `_to_reply` 按设计降级记 0【原文 `~/probe_fc.py` 输出 `cost=$0.000000`】。
  执行计划 §五 写的「litellm 认识全部 6 个模型，所以保护是真的有」**对中转站成立，对 DeepSeek 不成立**。
  止损现在只剩 `--max-steps` 和 `--wall-clock-limit`。
- ⚠️ **`.env` 在 Windows 侧编辑，是 CRLF**。不剥 `\r` 会混进 key（实测 `KEYLEN` 比真实长度多 1），
  curl 恰好容忍，litellm 未必。`~/env.sh` 已改成 source 一份 `sed 's/\r$//'` 过的副本。

### 已纠正的错误

第一轮测 `gpt-5.6-terra` 时，带 tools 的请求挂了 90s，随后的裸请求也 503，
我据此判成「站点抖动，不能归因给 tools」。**这个判断是错的** —— 加了前后夹健康对照才发现
tools 挂起并不影响后续请求（上表 C、D 之后的裸请求都 200），那次 503 是独立抖动撞在一起。
教训：**判断一个参数有没有问题，必须在同一分钟内做带/不带的对照**，不能靠前后两次请求的时间顺序推。

**第二处**：据「一分钟内从连续 200 掉到连续 8 次 503」我写过「站点可用性撑不住批量跑」。
随后 19 轮采样【原文 `~/probe_uptime.sh` 输出】只挂 2 次（成功率 ~89%，`#12–#21` 连续 10 轮全通），
**那次连续失败是低谷，不是常态**。`model.py` 的 4 次退避重试吃得掉这种抖动。
教训：**说「不稳定」之前先采够样本**，一段连续失败不构成可用性结论。

**第三处（09-18 随 C20 发现，都是交叉引用错，不影响行为）**：
① `loop.py` 里 `ModelReply` 的 docstring 把 `returned_model` 标成「决定 C14」，
上表里**记这件事的是 C15**（C14 是「model.py 单独一个模块」）。已改成 C15。
② 本节原写 `tests/test_loop.py`「22 条」，但 09-18 加测试**之前** pytest 只收集到 18 条，加完是 20 条。
22 这个数对不上任何一个时点，**来历【未知】**，按当前实测改成 20，不静默抹掉原数。

**第四处（09-18，㉖ 的证据链有一环是我补上的）**：`EVAL-P2.md` §六 ㉖ 给
「DeepSeek 返回 `prompt_cache_hit_tokens` / `_miss_` / `reasoning_tokens`」标的是【原文·实测】，
但它引的 `scripts/p2_cache_probe.py` 走的是**裸 HTTP**，而且**只打印了 hit 和 miss，没打印 reasoning_tokens**。
也就是说当时证的是「**API 返回**」，没证「**litellm 透出来**」，reasoning 那一项则连 API 侧都没直接证据。
09-18 离线补齐了缺的两环（转换器路径 + 三列齐全），结论没变，但**原来的标注比证据强**。
教训与⑳ 同型：**证据链要逐环点名，「实测过」三个字盖不住中间少的那一环。**
