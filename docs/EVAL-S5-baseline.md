# S5-baseline —— mini-SWE-agent 跑同 25 条：跑前估价与跑法定稿

**2026-09-17 写，跑之前的文档 —— 还没跑。** 标注分级照 `.claude/rules/fact-sourcing.md`：
【原文】直读并给行号／【推算】写明算法／【判断】我的分析／【未知】查不到，不许填补。

本文件是 S5 的后半段：`DESIGN-run.md:183` 原话「**S5：冻结 scaffold，dev 25 条正式跑；baseline 用 mini
跑同样 25 条**」—— 前半段 09-17 跑完了（resolved 12/25），后半段一直没跑。run-id 用 **`s5-baseline`**，
因为 `agent/report.py:4` 的用法写死是 `--run-id s5-mine --compare s5-baseline`【原文】。

---

## 〇 结论先行

| 问题 | 答 |
| --- | --- |
| 25 条要多少钱 | **点估 ¥2.3 ~ ¥2.4**【推算，两种估法，见 §二】 |
| 最坏多少 | **¥13.5** —— 25 条全部跑满 40 步【推算】 |
| 余额够不够 | 够。**本次实测 ¥21.99**【原文 `api.deepseek.com/user/balance`，2026-09-17】（`CLAUDE.md` 里记的 ¥3.50 已过时，其间充过值【判断】） |
| 能直接照旧命令跑吗 | **不能，会整跑报废。** 三处必须先改，三处都实测过，见 §三 |

---

## 一 为什么必须估：能用的量只有「字符数」

| 本来想用的数 | 为什么不能用 |
| --- | --- |
| mini 自己记的成本 | `model_stats` 只有 `instance_cost` 和 `api_calls`，**没有 token 数**【原文 `results/inference/s2-baseline/*.traj.json`】 |
| S2 的 $0.06 | 那是 **09-06 在中转站上、模型是 `gpt-5.6-luna`** 的账【原文 同上 `info.config.model.model_name`；`README.md:21`】。换了供应商和模型就不是同一笔价 |
| 我方落盘的 `total_cost` | **恒为 0**【原文 `s5-mine/*.traj.json`，25 条全 0】。litellm 不认 `openai/deepseek-flash` 这个名字（§五 ①） |
| 官方 usage 账单 | 面板里没有按 run 拆的口径【未知】 |

**唯一可信的成本是余额差**：S5 的 25 条 = **¥5.27**【原文 `CLAUDE.md` S5 行，余额 9.92→4.65】。
所以估法只能是：**两边轨迹里实际发出去的字符数当代理量，用 S5 的余额差反推单价，再乘 mini 的字符量。**

口径（写死在 `scripts/mini_cost_est.py` 文件头，可复跑）：
- 两边都是 append-only 会话、每轮重发全 history → **每次模型调用的输入 = 该 assistant 消息之前的全部消息**；
  `cum_in` 把每次调用当时的 history 字符数累加，这才是计费意义上的输入量（不是最终 history 的长度）。
- `out` = assistant 消息的 content + `tool_calls` 序列化后的字符数。
- 字符≠token，但**两边同尺度**，配对比值不受这个常数影响。

---

## 二 估算结果

复跑：`python3 scripts/mini_cost_est.py`（只读 `results/`，不调模型，不花钱）。

### 2.1 两边的实测量【原文 轨迹文件】

| | 条数 | 模型调用 | 累计输入(字符) | 输出(字符) |
| --- | ---: | ---: | ---: | ---: |
| mini S2（09-06，中转站，`gpt-5.6-luna`） | 2 | 31 | 2,013,763 | 39,527 |
| 我方 S5（09-17，DeepSeek 官方，`deepseek-flash`） | 25 | 703 | 58,929,593 | 191,874 |

单条明细：`django-11138` mini 20 次调用 / 1.57M 字符，`sphinx-9698` mini 11 次 / 0.44M 字符。

### 2.2 单价锚点【推算】

**¥5.27 / 59,121,467 字符 = ¥0.089 / 百万字符**（输入累计 + 输出合并计，理由见 2.4）。

### 2.3 两种估法

**S2 那 2 条实例都在 25 条 subset 里，而且我方 S5 有同实例的轨迹** —— 所以能配对，不必只做均值外推。

| 估法 | 算法 | 结果 |
| --- | --- | --- |
| **A 配对外推**（首选） | 同 2 条：mini 2,053,290 字符 vs 我方 4,430,225 字符 → 比值 **0.463**；乘我方 25 条总量 | **¥2.44** |
| B 均值 × 25 | mini 每条均值 1.03M 字符 × 25 | **¥2.29** |
| C 仅按调用次数 | mini 15.5 次/条 vs 我方 28.1 次/条 | 不作数：忽略了上下文增长，必然低估 |

两种估法差 6%【判断】，量级可信。

### 2.4 交叉验算：反推缓存命中率

litellm 1.100.0 的价格表里 `deepseek-flash` 是 **输入 $0.30 / 百万 token、缓存命中 $0.006、输出 $1.20**
【原文 `litellm.model_cost["deepseek-flash"]`，其 `source` 字段指向 api-docs.deepseek.com】。

按 3.7 字符/token【判断，经验值未实测】换算，S5 的输入约 15.9M token：
**全价不命中缓存本该 ¥34.37，实际只花 ¥5.27 → 隐含缓存命中率 88%**【推算】。

落在 0~1 且偏高，与 append-only 会话（每轮只在尾部追加）的预期一致【判断】→ 说明 2.2 那个锚点
**已经把缓存折扣包含进去了**，可以直接用。这也是为什么输入与输出能合并计：输出只占 0.33% 字符，
即便按 4 倍单价算也淹没在缓存折扣的不确定性里【推算】。

### 2.5 上限：点估**只**在「mini 像 S2 那样早早收工」时成立

S2 那 2 条只用了 11 步和 20 步就交卷【原文】，远没碰到上限。若 25 条里有实例一路跑到步数上限，账完全不同。

模型：history 每步线性增长 g 字符 → 累计输入 ≈ 0.5·g·n²（等差求和）。反解实测的 g：

| | g（字符/步） |
| --- | ---: |
| mini `django-11138` | 7,856 |
| mini `sphinx-9698` | 7,314 |
| **mini 平均** | **7,585** |
| 我方 S5 平均（同法） | 4,301 |

**mini 每步比我方贵 1.76 倍**【推算】—— 【判断】它只有一个 bash 工具，`cat` 整文件进上下文；
我方 `read_file` 有 10000 字符截断（`DESIGN-observation.md` 决定 22），两边阈值虽同，但它的 `cat`
本来就常常整篇命中上限。

| step_limit | 单条跑满 | 25 条全跑满 |
| ---: | ---: | ---: |
| **40** | 6.07M 字符 = ¥0.54 | **¥13.52** |
| 250（mini 原配置） | 237M 字符 = **¥21.13** | ¥528.22 |

→ **一条跑满 250 步就能吃掉现在的全部余额。** 这是 §三 ① 的硬理由，不是风格偏好。

---

## 三 跑前必须改的三处（都实测过）

### ① `step_limit: 250` → **40**

【原文 `.venv/.../minisweagent/config/benchmarks/swebench.yaml:112-113`：`step_limit: 250` / `cost_limit: 3.`】

两个理由，**方法论的那个更重要**：
1. **控制变量**：我方 `--max-steps 40` 限的是模型轮数（`loop.py:408`），mini 的 step 也是「一次模型调用 +
   一条 bash」，两者对齐的量是 **API 调用数**。不对齐就等于给 baseline 6.25 倍预算，相对 baseline 的实验变量
   从三个（`DESIGN-observation.md` §八）变成四个，后面所有差异都说不清是哪一个造成的。
2. 成本：见 2.5，单条 ¥21.13。

代价要写进报告：**mini 在 S2 只用了 11/20 步**【原文】，所以 40 步对它不算紧；但 25 条里若有实例被 40 步截断，
「baseline 被我限了预算」这条质疑是成立的，得用 `exit_status` 里 `step_limit` 的条数说话，不能含糊。

### ② `cost_tracking` 必须设 `ignore_errors`，否则 **25 条全废成空 patch**

链条【原文 `models/litellm_model.py:108-125`】：
`openai/deepseek-flash` litellm 价格表**不认识**（§五 ①实测）→ `completion_cost` 返回 0 →
`if cost <= 0.0: raise ValueError` → `except` 里 `cost_tracking != "ignore_errors"` 就 **`raise RuntimeError`**。

更坏的是它**不会让整批崩**：`run/benchmarks/swebench.py:157-176` 每条实例外面套 `except Exception`，
把 `exit_status` 记成 `"RuntimeError"`、`result` 记成 `""`，照样写进 `preds.json`【原文】。
→ **拿到的是一份 25 条全空 patch 的 preds.json，评出来 0/25 resolved，看起来像「baseline 很差」而不是「我配错了」。**
而且容器已经起过、第一次 API 调用已经花过钱（【推算】每条约 ¥0.01 量级，总额可忽略，废掉的是时间和一次可信的结果）。

三个走法，选 **B**：

| | 做法 | 拿到什么 | 代价 |
| --- | --- | --- | --- |
| A | `-m deepseek/deepseek-flash` | litellm 认价（实测认），`cost_limit: 3.` 复活，还有逐条成本 | 换了 litellm 的 provider 路由（读 `DEEPSEEK_API_KEY`、自己拼 base url），与 S5 的 `openai/` 兼容路由**不是同一条请求路径** → 多一个不可比因素 |
| **B ✅** | `-m openai/deepseek-flash` + `MSWEA_COST_TRACKING=ignore_errors` | 请求路径与 S5 **完全一致**；成本口径两边同样是「假 $0 + 余额差」，**对称** | `cost_limit` 这层止损失效，止损只剩 `step_limit` |
| C | 保留 `openai/` 名字 + 喂 `litellm_model_registry` 价格表【原文 `litellm_model.py:32` 的字段与 `:61-62` 的 register_model】 | 路径一致且有真成本 | 多一个没验过的机制；真要逐条成本时再上 |

选 B 的判据仍是那条：**「它能不能让某个面试追问变得可答？」** —— 「两边成本口径为什么不同」是个我不想背的追问；
而「baseline 的止损只有步数上限」有 2.5 的上限表兜底，答得出来。

### ③ 必须先 `source ~/env.sh`，不能靠 mini 自己的 `.env`

`mini-extra` 启动时打印 `Loading global config from '/home/zixu/.config/mini-swe-agent/.env'`，
而那个文件里还是 **`OPENAI_BASE_URL=https://hgapi.dieqiyun.top/v1`**【原文，2026-09-17 实测】——
正是被校内网 DNS + SNI 两层屏蔽的中转站（`EVAL-S5-badcase.md` §4.1）。

**实测它不会覆盖我们导出的值**（`scripts/s5_baseline_preflight.sh` 探针 [1][3]）：

```
[1] env.sh 导出后:            OPENAI_BASE_URL=https://api.deepseek.com/v1
[1] import minisweagent 之后: OPENAI_BASE_URL=https://api.deepseek.com/v1
[3] 生效 key 指纹: eb1693bf   中转站 .env: 354675e8   Monash .env: eb1693bf
```

代码依据【原文】：`minisweagent/__init__.py:36` 是 `load_dotenv(dotenv_path=...)`，**不带 `override`**
（python-dotenv 默认 `override=False`，已有环境变量赢）；带 `override=True` 的那处在
`run/utilities/config.py:22`，只被 `mini-extra config` 子命令和交互式 `mini` 用到，**`mini-extra swebench`
走不到**。

→ **顺序是硬要求**：先 `source ~/env.sh` 再启动。漏了就打被屏蔽的域名，第四次栽同一个坑。
→ 没有去改那个 `.env`：官方端点的凭据只留在 gitignore 过的 Monash `.env` 一处（`~/env.sh:1-2` 的约定），
   不复制第二份。**决定：不动 mini 的 `.env` / 理由：凭据不留第二份副本，且实测不覆盖 / 否决：把官方 key 写进它**。

---

## 四 定稿命令

```bash
# 0. 凭据 + 跑前余额（③：顺序是硬要求）
source ~/env.sh
bash ~/s5_balance.sh                              # 记下跑前余额，这是成本的唯一来源

# 1. 零成本探针：端点、key 指纹、25 条正则命中、价格表（不调模型）
bash ~/swe-bench-eval/scripts/s5_baseline_preflight.sh

# 2. 正式跑
cd ~/swe-bench-eval
export MSWEA_COST_TRACKING=ignore_errors          # ②：否则 25 条全废成空 patch
YAML=.venv/lib/python3.12/site-packages/minisweagent/config/benchmarks/swebench.yaml
.venv/bin/mini-extra swebench \
  --subset verified --split test \
  --filter "$(cat ~/s5_baseline_filter.txt)" \
  -o results/inference/s5-baseline \
  -w 4 \
  -m openai/deepseek-flash \
  -c "$YAML" -c agent.step_limit=40               # ①：-c 一旦给了，默认配置就不再加载，必须显式带上 yaml

# 3. 评测：与 S5 同一套 harness、同样的 -j
.venv/bin/swebench eval verified -p results/inference/s5-baseline/preds.json --run-id s5-baseline -j 6

# 4. 跑后余额 + 并排归因表
bash ~/s5_balance.sh
PYTHONPATH=. .venv/bin/python -m agent.report --run-id s5-mine --compare s5-baseline
```

**怎么验证跑对了**（第一条实例落盘后就能看，不用等整批）：

| 验什么 | 怎么看 | 期望 |
| --- | --- | --- |
| 步数上限真的是 40 | `grep -o '"step_limit":[^,]*' results/inference/s5-baseline/*/*.traj.json \| sort -u` | 只有 `40` |
| 用的是官方端点 | 轨迹里 `info.config.model.model_name` + 没有 `APIConnectionError` | `openai/deepseek-flash` |
| 没有 ② 那种整批报废 | `grep -c RuntimeError results/inference/s5-baseline/*/*.traj.json` | 0 |
| 花了多少 | 跑前/跑后 `s5_balance.sh` 的差 | 落在 ¥2.3 ~ ¥13.5 之间；**超出 ¥13.5 说明 2.5 的模型错了，回来改这份文档** |
| 25 条都跑了 | `python3 -c` 数 `preds.json` 的键 | 25 |

⚠️ 中断可续：mini 默认跳过 `preds.json` 里已有的实例（`swebench.py:231`，不给 `--redo-existing`）【原文】。
所以想分批就**分两次跑同一条命令**，中间查余额；不想分批就一次跑完。

---

## 五 已纠正的错误

① **「litellm 价格表不认识 `deepseek-flash`」这句不准确** ——
【原文 `DESIGN-run.md:70`】和【原文 `DESIGN-loop.md:245`】都这么写，2026-09-17 实测：
价格表**认识** `deepseek-flash`，也认识 `deepseek/deepseek-flash`，**只不认 `openai/deepseek-flash`**。

→ 真因是 **`openai/` 这个 provider 前缀**，不是模型缺价。两条推论：
- 我方 `cost=$0.0000` 的根因要改口径（那两处文档待改，本次没动代码也没动它们）；
- **我方只要把 CLI 参数换成 `deepseek/deepseek-flash` 就可能拿到真实成本，`agent/` 一行都不用改**
  （`s5-frozen` 的冻结不受影响）。值得单独花几毛钱、跑 1 条验一次；验通了 `--cost-limit` 也跟着复活。
  **本次没做** —— 它会改变请求路径，属于新变量，不能和 baseline 这一跑混在一起。

② **余额不是 ¥3.50**：【原文 `CLAUDE.md` S6 行】记的是 09-17 跑 S6 前的 ¥4.35→3.50；
本次实测 **¥21.99**【原文 余额接口】。中间充过值【判断】。

---

## 六 【未知】（跑之前诚实列出，不猜）

1. **mini 在 `deepseek-flash` 上的缓存命中率**。2.2 的锚点是我方 88% 命中的那条曲线；mini 同为 append-only、
   每步重发全 history，【判断】应当接近，但没测过。若它明显更低，实际花费会高于点估（极端：全不命中，
   按 2.4 的全价比例约 6.5 倍 → ¥16 量级【推算】，仍在余额内）。
2. **3.7 字符/token** 是经验值，未在本项目实测。只用于 2.4 的量级核对，不影响 A/B 两种估法。
3. **mini 版本**：现在装的是 **2.4.6**【原文 `mini-extra` 启动横幅】；S2 那次的版本没记录【未知】。
   旁证：S2 的产物是扁平的 `*.traj.json`，而 2.4.6 写 `<output>/<instance_id>/<instance_id>.traj.json`
   【原文 `swebench.py:130`】→ **两者很可能不是同一版**。prompt 模板若变过，S2 的 2/2 resolved 与这次不可比；
   §2.3 的配对比值也只是字符量的比值，不保证行为同构。**跑完要做的第一件事：把这次 `django-11138` /
   `sphinx-9698` 的 `system_template` 指纹与 S2 的对一下**（S5 badcase 里用过同一招：md5 指纹排除 prompt 差异）。
4. **40 步上限会不会改变 mini 的行为**（比如提交前不再跑测试）。跑完看 `exit_status` 分布。
5. **S2 的 `$0.06` 折算不出 token**：只有总价，拆不出输入/输出，所以没法用它独立验证 2.2 的锚点【未知】。

---

## 七 面试可讲的事（接 `CLAUDE.md` 的编号，⑮⑯）

⑮ **没有 token 数也能把成本估到可决策**：mini 只落盘总价和调用数，我方落盘的成本是假的 $0 ——
可用的量只剩「轨迹里实际发出去的字符」。做法是四层：**代理量**（累计输入字符，不是最终 history 长度）→
**实测锚点**（拿唯一可信的余额差反推 ¥/百万字符）→ **配对外推**（S2 那 2 条正好都在 25 条 subset 里，
我方有同实例轨迹，于是用比值而不是均值）→ **上限与交叉验算**（按 0.5·g·n² 反推「全部跑满」的最坏账；
再用 litellm 价格表回算，得出隐含缓存命中率 88%，落在 0~1 才敢用这个锚点）。
**点估 ¥2.4、上限 ¥13.5、余额 ¥21.99 → 可以跑**；差 6% 的两种估法互相印证。

⑯ **第四次同型陷阱，这次在跑之前抓住了**：前三次分别是 S3′ 的静默挂起、S5 的黑名单判定、S6 的「漏 `--model`」。
这次跑前逐条核配置，抓到两个都会让整跑报废的东西 ——
mini 自带 `.env` 还指向被屏蔽的中转站（实测不覆盖，但**顺序**是硬要求），
以及 `cost_tracking` 默认值会在第一次模型调用之后抛 `RuntimeError`，而它**每条实例单独兜住异常**，
结果是一份「25 条全空 patch」的 `preds.json`、评出 0/25 —— **看起来像 baseline 很弱，其实是我配错了**。
教训是⑬的正面应用：**动手前先问「这次的配置和上次成功那次差在哪」**，而不是跑完再归因。
