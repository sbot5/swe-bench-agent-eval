# EVAL-P4-staged —— 分阶段 Round：整条指令换掉，能把 A 组从「考古」拉回「动手」吗

> 2026-09-22 **跑前锁定（预注册）**，= `Career/04-项目/16-plan.md` §⑤。
> **本文件在开跑之前 commit，§〇–§七 跑完一个字不许改**；结果只往 §八 及以下补。
> 跑次将用 `p4-r1` / `p4-r2`（冒烟 `p4-smoke`）。对照读：`p3-r1`/`p3-r2`（09-19）、`p2-rerun`（09-19）、`p2-mine`（09-18）、`s5-mine`（09-17）。
> 标注分级见仓库约定：【原文】直读落盘数据或源码 ·【推算】由数据算出 ·【判断】我的分析 ·【未知】查不到。

## 〇、这一跑回答哪一个问题

**唯一问题：把 40 轮切成 Collect / Implement / Verify 三段、每段把当前指令整条换掉，能不能让 A 组 8 条产生编辑动作？**

这一跑**不回答**下面三件事，读数时也不许拿来说：

1. **resolved 分数高不高** —— ⑦⑨ 已五次实证同配置单跑方差能吃掉一次修正的效果。
2. **C23（工具集每步可变）/ C24（缓存友好裁剪）好不好** —— 它们是本跑的**地基**，不是本跑的自变量；
   本跑没有同形状的 before 可比（㉞）。
3. **成本降没降** —— 见 §六，本跑成本与 09-21 之前不可比。

## 一、前提：已经关掉的路，本跑不重新论证

| 已关掉 | 证据 |
| --- | --- |
| A 组基线「从未动手」是真的 | A 组 8 条 × 3 跑（`s5-mine`/`p2-mine`/`p2-rerun`）`apply_patch` 调用数 **24/24 全 0**【原文 `docs/EVAL-P2-rerun.md` §三，经 `scripts/p3_preflight.py:18` 注释转引】 |
| **prompt 措辞**这条路 | P3：新条款触发条件出现 **6 次、模型 0 次照做**，动手 2/16、Fisher 单侧 **p = 0.154** 不显著【原文 `docs/EVAL-P3-prompt.md` §〇、§五】 |
| 「它卡在复现上」这个前提 | ㊺ 证伪：脚本层 85% `exit 0`，多条明说 "Reproduced."【原文 `Career/04-项目/CLAUDE.md` 当前状态】 |
| 「P3 那 2 次动手是效果」 | ㊻ 证伪：两条的第一刀都紧跟一次**成功复现**之后，走的是第 3 条原来就有的路【原文 `docs/EVAL-P3-prompt.md` §5.1】 |
| 「它在躲风险」这个前提 | 09-20 §五第 0 步证伪，且**证据方向相反**：会动手的 B 组反而更常评估「会不会改坏」 |

**现在确知的卡点**：复现完成之后它**转身去找上游的标准答案**（H2 11/16），而这**不是断网能拦住的**（㊸：
断网只换掉取件通道，模型改用记忆版考古）。

**所以本次自变量不是「再加一句」，是把整条当前指令换掉**【原文 `16-plan.md` §7】：

> **Collect**: obtain the facts needed to complete the goal, then end the Round after making measurable progress.
> **Implement**: complete the main action from the available facts, record the result, and end the Round.
> **Verify**: check that the deliverable satisfies the goal and remove temporary capabilities.
> 【原文 `scenario.py:22-26`，经 `16-plan.md:151-154` 转引 —— ⚠️ **本次没有重开 dsh 源码核对**，实现前须回原文逐字对一次】

「Implement：from the available facts 完成主要动作」这句话里**没有「去找答案」这个选项** —— 这是形状上的差别，
**不是证据**。它能不能拦住 `deepseek-flash` 仍然【未知】（`16-plan.md:164` 自己标的）。

## 二、自变量：一个复合变量，三个成分，不许拆开归功

| 成分 | 内容 |
| --- | --- |
| ① 段划分 | 40 轮切成三段的**边界规则**（怎么切、谁决定进下一段） |
| ② 段指令 | 每段的指令原文（整条替换，不是追加一句） |
| ③ Verify 段撤能力 | 照 dsh "remove temporary capabilities"，用 `tool_policy` 摘掉该段不该有的工具 —— **C23 的第一次真用** |

⚠️ **三者一起上，归因只能归给「分阶段」这一个复合变量。** 这是 P3 的教训（第 3 条 + 第 5 条 + `"two attempts"`
三个成分同属一个复合变量，㊳）。想单独知道哪个成分有用，是另一次实验的事，本跑答不了。

### 2.1 实现上还没定的三处（下个会话动手时定，**定完写回本节，然后才准开跑**）

| # | 选择 | 【判断】倾向与理由 |
| --- | --- | --- |
| ⒜ **指令怎么换** | 改 `system_prompt`（整棵前缀缓存树作废，㉕）· 还是在消息尾部追加一条 Round 指令（前缀保留） | **倾向尾部追加**。它同时决定成本口径（§六），必须写死，不许跑的时候临时决定 |
| ⒝ **段边界怎么定** | 固定轮数切 · 还是由信号触发（如首次 `exit 0` 进 Implement） | **倾向固定轮数**。触发器自己跑间极差中位 13 轮（`pylint-4551` 四跑 20/17/36/25）【原文 `docs/EVAL-repair-gate-N.md`】，用它当边界等于往自变量里掺一个自己就在摆的量 |
| ⒞ **三段各几轮** | —— | 【未知】，没有任何数据支持某个切法。定了就写进本节和指纹，两跑必须同一个切法 |

#### 〔2026-09-22 定死，开跑前不许再改〕

三处全定，外加一处 §2.1 原来没列、但 §四 第 5 条的指纹要求必须写死的（段→工具表）。**本节全程 $0。**

| # | 定成什么 | 依据 |
| --- | --- | --- |
| ⒜ 指令怎么换 | **骨架 `system_prompt` + 段指令在消息尾部追加**，`messages[0]` 全程不变 | 文档原给的二选一**都不自洽**：原 `SYSTEM_PROMPT` 的「How to work」六步【原文 `agent/loop.py:172-182`，09-22 直读】**本身就是段指令要替换的东西**，只在尾部追加会让两套流程并存（P3 ⒜「只改第 3 条会让 prompt 自相矛盾」的同型）；中途改写 `messages[0]` 则每个段边界让整棵前缀树作废，而未命中单价是命中的 50 倍【原文 `EVAL-P2-rerun.md:125-143`】。骨架版**删掉六步、保留 grading rules 五条**，段指令追加在尾部 → 两个毛病都没有。另**已核**：`trim_messages` 只折叠 `role=="tool"` 的消息【原文 `agent/loop.py:386`，09-22 直读】，所以段指令不会被 C24 的折叠吃掉 |
| ⒝ 段边界怎么定 | **固定轮数** | 照本节原倾向。**补一条更硬的**：触发器 T 不只是在摆（跑间极差中位 13 轮），`django-11138` **四跑全部 T=None**【原文 `EVAL-repair-gate-N.md`】→ 用信号当边界，那条实例**永远进不了 Implement 段** |
| ⒞ 三段各几轮 | **Collect 1–12 · Implement 13–32 · Verify 33–40** | 原标【未知】。本次用已落盘轨迹 $0 算出数据底（`scripts/stage_budget.py`，p2-mine + p2-rerun 各 25 条）：**B 组（动过手的）首刀轮号两跑中位 9 / 11**，12 轮覆盖 **62% / 53%** —— 即「正常实例到这儿都已经动手了」；**首刀之后还要用的轮数中位 14.5 / 9**，所以 Implement 20 + Verify 8 = 28 有余量。⚠️ 这**不是最优解，是有据可查的一个点**：同 16 条配对的首刀轮号跑间差中位 4.5、**max 28**（㊾，量具自己也在摆） |
| 段→工具表 | **Collect** `list_files search_code read_file run_python finish` · **Implement** `read_file apply_patch run_tests run_python git_diff finish` · **Verify** `read_file apply_patch run_tests git_diff finish` | **Collect 段摘掉 `apply_patch`** 是成分③ 的强制力所在 —— 不是靠指令劝住的（㊳：prompt 里加一条规则 ≠ 系统里多一条规则）；**Implement 起摘掉 `search_code`/`list_files`** 堵 H2 的考古向量；**`read_file` 三段都留**，摘掉读会打爆 `apply_patch` 的锚点匹配（gold 回放 66/66 那条性质靠它）；`finish` 必须全段留，否则 `_validated_declaration` 当场抛 `ValueError`。⚠️ **三段的工具顺序必须与 `build_tool_schemas()` 的原顺序一致**（由 `test_staged.py` 钉死）——见下方「已纠正的错误」 |

⚠️ **已纠正的错误（不静默改）**：`STAGE_TOOLS["IMPLEMENT"]` 头一版写成 `read_file run_python apply_patch
run_tests git_diff finish`，**集合对、顺序错**。`select_tool_schemas` 保持 schema 原顺序（C23：重排会让请求
前缀变一遍），而 `StepRecord.tools_declared` 落的是 `STAGE_TOOLS` 的顺序 —— 两边不一致，**落盘记录就与真正
发出去的工具表对不上**，后面按 `tools_declared` 重建每轮工具表的分析（C24 的 `scripts/cache_sim.py` 正是这么做的）
会拿到一个从未发生过的顺序。是 `scripts/p4_preflight.py` 打印的逐步工具集与 `STAGE_TOOLS` 一眼对不上才发现的；
**当时 197 条测试全绿** —— 因为原来的断言比的是集合。现已改成比列表，并新增
`test_every_stage_lists_its_tools_in_the_canonical_schema_order` 钉死。又一次「测试绿不等于口径对」。

**指纹**（`PYTHONPATH=. .venv/bin/python -m agent.staged` 打印；两跑的指纹必须逐字相同）：

- 切法 `[12, 32, 40]`
- `system_prompt_md5` = `f57fadb6fddfef93250c5713741c2032`
- `stage_notes_md5`：step 1 `9ec2957a9006d33adfee8a3b430361cb` · step 13 `69df19e3bad5d065918bef53172d9379` ·
  step 33 `ea63acc47bd65fc17bcd405fbfea7a1f`
- `tool_schema_template_md5` = `7a7bc0adddc6c9f041bc89d86f14f9c7`
- `stage_tools` 见上表

⚠️ **已纠正的错误（不静默改）**：指纹头一版哈希的是 `ROUND_*` **常量**、只记 `stage_notes_at` 的**键位**，
而循环真正收到的是 `STAGE_NOTES` —— 直接改它的文本就能换掉发给模型的指令而**指纹纹丝不动**；
同样，请求里发的是 `build_tool_schemas(hint)` 的**完整 schema**，工具描述或参数改了，`stage_tools`
那张名字表也看不出来。现已改成直接哈希 `STAGE_NOTES` 的值 + 工具 schema 模板（`TARGET_HINT` 替换前）。
配套的 mutation test 也从「改常量」改成「改 `STAGE_NOTES[1]`」并新增一条改工具描述的。
**另**：`summary.json` 现在记 `commit`（`git rev-parse HEAD`）—— 指纹只盖得住 staged 那几样，
`agent/` 其余任何改动都盖不住，而跨会话最容易发生的就是那种。

⚠️ **定切法时发现一个判据缺口。§3.3 不改，缺口照实记下**：两条对照的**自然首刀轮号**是
`django-14631` **25 / 38**、`sphinx-9711` **None / 22**（p2-mine 那一跑它根本没动手、本身就是 A 组成员）
【推算 `scripts/stage_budget.py`，源数据 p2-mine / p2-rerun 轨迹】。→ **Collect 段那道闸（1–12 轮不给 `apply_patch`）
切不到这两条**。所以「有没有把本来会动手的弄坏」这一问，本跑的对照**只覆盖得了 Implement 段摘 `search_code`/`list_files`
那个成分，Collect 闸的误伤记【未知】**。要真正检验它得换首刀早的实例当对照（如 `django-11163` 4/4、
`django-13512` 4/5），那要动已锁定的 §3.3/§3.4 —— **本人 09-22 拍板：不动，接受这个缺口。**
这是 ㊿「判据锁定挡得住改阈值、挡不住判据本身漏了量」的**第二次实证**。

**§2.2 那条线已于 09-22 接好**（§2.2 正文一个字不改，接法记在这里）：

- `agent/staged.py` **新建** —— P4 这一次实验的全部内容（骨架 prompt、三段指令原文、切法常量、段→工具表、`tool_policy`、`fingerprint()`）
- `agent/loop.py` 的 `run_episode` **加一个通用形参 `stage_notes: Mapping[int, str] | None`（决定 C25）** ——
  它只认「第几步追加哪条消息」这张表，**不知道「三段」这回事**；追加点排在 `tool_policy` 之后，
  所以同一步先出 `<tools_changed>` 再出 `<round>`（指令里会提到那几个工具，顺序反了就自相矛盾）
- `agent/run.py` —— `run_instance` 把 `system_prompt` / `tool_policy` / `stage_notes` 透传给 `run_episode`；
  `main` 加 `--staged`，并**校验 `--max-steps` 必须等于 40**（切法按 40 定死，对不上整批错位，当场 `parser.error`）；
  指纹随 `summary.json` 落盘

**§四 七条的状态**（全 $0）：

1. ✅ 假 env **181 → 199**（`tests/test_staged.py` 12 条 + `test_loop.py` 分段追加 6 条）· 真容器 **21** 全过 ·
   `ruff check agent tests` **18** 条，**逐文件与 HEAD 对比零新增**（`run.py` 4→4、`loop.py` 2→2，两个新文件 0）。
   ⚠️ **已纠正的错误（不静默改）**：`Career/04-项目/CLAUDE.md` 与各 DESIGN 里反复记的「ruff `agent tests` 仍 **15**」
   与 09-22 实测的 HEAD **18** 对不上，**差额来源【未知】**；本次没有动任何既有 lint，只是照实记下这个对不上
2. ✅ gold 回放 **25/25、0 编辑失败**，`preds.json` 与 **y12 / c21 / p3 三次历史基线逐字节相同**（`scripts/preds_diff.py`）。
   ⚠️ 照 §四 原话，这条**证不了本次改动** —— 假模型不看工具表【原文 `tests/gold_replay.py:72-75`】，
   它只保证「不传 `stage_notes`/`tool_policy` 时老路径没变」
3. ✅ 冒烟**改成 $0 版**：`scripts/p4_preflight.py` 用假模型跑满 40 步，打印指纹、逐步声明的工具集、三段指令原文，
   并自检 **6 条全过**：`messages[0]` 全程没被改写 · 三条段指令按序到位、一条不多一条不少 ·
   其余 system 消息只有工具变更通知 · **每步发出去的工具表 = 该步所属段的工具表（比列表不比集合）** ·
   Collect 拿不到 `apply_patch` · Implement/Verify 拿不到 `search_code`。
   ⚠️ 它**证不了模型会不会照做** —— 那是真跑才能答的，判据在 §三
4. ⬜ 10 条 `NetworkMode=none` 全覆盖 —— **跑时执行**，逐容器 `docker inspect`
5. ✅ 指纹已写进本节
6. ✅ 余额 **09-22 11:51 北京重读 ¥36.73**，与 09-20 收敛读数**同值** → 本次全程 $0 得到独立确认。
   ⚠️ 顺带修掉一个**已经坏掉的工具**：`~/env.sh` 里 `.env` 的路径还停在 **09-20 目录重组前**的
   `Career/07-swe-bench-agent/`，实际在 `Career/04-项目/` —— 不修根本查不了余额（本次已改，`~/env.sh` 不在任何仓库里）
7. ✅ 判据与本次改动已 commit，`git status` 干净

**Codex 二审（gpt-5.6-terra，报告 `.agent/reviews/20260922-135907-…md`）：BLOCKER 无、MAJOR 3 + MINOR 2，
五条全部成立、当天修完。**又一次是在**全部测试绿、preflight 六条也全过之后**才被审出来的：

- **MAJOR-1** `p4_run.sh` 固定 `p4-r1`/`p4-r2` 却没传 `--overwrite`，而 `run.py` 默认**跳过**已有 trajectory
  的实例 → 中断后重跑脚本，旧产物会混进 `preds`/`summary`/评测，两跑比较当场失真。
  改成 **fail-closed**：输出目录非空即退出，不做隐式复用
- **MAJOR-2** 指纹没盖住真正发出去的东西（详见上方「已纠正的错误」）
- **MAJOR-3** runner 存了 `rc` 只打印不判断，agent 失败后照样评测、照样跑第二跑 → 会产出一份
  **看起来完整**的实验日志。改成三道 fail-closed（agent 退出码 · trajectory 条数等于名单条数 ·
  评测退出码），并用 `trap` 回收 watcher
- **MINOR-1 / MINOR-2** 两条测试断言比它声称钉住的性质弱：一条改的是常量而非循环实际收到的
  `STAGE_NOTES`，一条只比最终 `messages` 而没看边界那一轮的**请求**。都已改成钉真对象

**开跑脚本**：`scripts/p4_run.sh`，照 `p3_run.sh` 逐行改写（同一个 `groupa_ids.txt` 10 条 = A 组 8 + 对照 2、
同一套 `NetworkMode` watcher、同样跑两遍 `p4-r1`/`p4-r2`），**唯一差异是多了 `--staged`**。

```bash
wsl -d swebench -e bash -lc 'bash /home/zixu/swe-bench-eval/scripts/p4_run.sh'
```

⚠️ **排空闲时段再跑**：09-22 11:51 北京正在高峰（工作日 9–12 / 14–18 高峰，其余含周末半价）。
⚠️ `--max-steps` 不传就是默认 **40**【原文 `agent/loop.py:16`】，正好等于切法要求的总轮数；
传了别的值 `--staged` 会当场 `parser.error`。

### 2.2 开跑前必须先接的一处线（现在还没接）

`run_episode` 的形参里 `system_prompt`（`loop.py:514`）和 `tool_policy`（`loop.py:515`）都已经有了【原文】，
但 **`run.py:157-164` 的调用两个都没传**【原文】—— 只传了 `instance_id` / `problem_statement` / `tools` /
`client` / `tool_schemas` / `config` 六个。所以「分阶段」现在**没有入口**，接线本身是 ⑤ 的第一步代码改动，
且它落在 §二的成分①②③ 里，不算额外变量。

## 三、判据（跑前锁定，跑完不许改）

### 3.1 主判据：A 组的动手数

**量**：A 组 8 条 × 2 跑 = **16 个实例-跑组合**中，`apply_patch` 调用数 > 0 的组合数。

- 基线：**0/24**（三跑）
- P3：**2/16**（Fisher 单侧 p = 0.154，不显著）

**过线阈值：≥ 5/16，且两跑各 ≥ 2。**

【推算】阈值怎么来的 —— 固定边际的 2×2 精确检验（基线 0/24 对本次 k/16）。因为基线那侧观测为 0，
「比观测更极端」只有「k 次动手全落在本次这一侧」一种格局，所以单侧
`p = C(16,k) / C(40,k)`：

| k（本次动手组合数） | 单侧 p |
| ---: | ---: |
| 2 | 0.15385 |
| 3 | 0.05668 |
| 4 | 0.01991 |
| **5** | **0.00664** |
| 6 | 0.00209 |

**算法自校验**：k=2 代入得 0.15385，与 P3 文档已发布的 **p = 0.154** 一致【原文 `docs/EVAL-P3-prompt.md` §〇】→ 算法没写错。

**为什么不取 k=4（p = 0.0199 也过 0.05）**【判断】：4/16 只比 P3 多 2 次，而 P3 那 2 次**已经被证明可以是方差**（㊻）。
「两跑各 ≥ 2」这一条是防止单跑包办 —— ⑦⑨ 的老形态正是「两跑动手的不是同一条」。

### 3.2 必报的反向指标：有 patch 但 unresolved

⚠️ **空 patch 变成错 patch 是失败模式换型，不是提升**，而且我们正是在朝 SWE-agent 那个 edit loop 的病推。

**报法**：A 组每条出 `(patch_chars > 0, resolved)` 四格表，与基线三跑的同表并排。
**主判据过线但错 patch 大量增加时，结论写「换了失败模式」，不许只写主判据过线。**

### 3.3 对照两条：只能否定，不能肯定

`django__django-14631`（P2 相对 S5 **救回**的）· `sphinx-doc__sphinx-9711`（P2 **带沟里**的），
查「有没有把本来会动手的弄坏」。**它们自己在三跑里就不稳**，动手数【原文 `docs/EVAL-P3-prompt.md` §1.3】：

| 实例 | s5-mine | p2-mine | p2-rerun |
| --- | --- | --- | --- |
| `django-14631` | 0 | 5 | 2 |
| `sphinx-9711` | 2 | 0 | 2 |

→ **读法先锁死**：两条**两跑全为 0** 才算警报；没掉**不算**「没弄坏」的证据（㊶ 选对照组之前先量它自己的方差；
(51) 交叉验证也要先问它有没有检验能力 —— 这里分母是 2）。

### 3.4 样本与跑次

A 组 8 条 + 对照 2 条 = **10 条 × 2 跑**，照 P3 的形状（`scripts/p3_run.sh`）。

A 组名单【原文 `scripts/p3_preflight.py:19-27`】：`django-10554` · `django-11138` · `pylint-4551` · `pylint-8898` ·
`sphinx-11510` · `sphinx-8638` · `sympy-17630` · `sympy-18211`。

**单跑不算数**（⑦⑨ 五次实证）。

### 3.5 「有没有被遵守」是独立判据，必须单报

P3 最贵的一课（㊴）：**「有没有照做」与「有没有用」是两个问题，判别量不一样。**
主判据没过线时，**不许直接写「分阶段无效」**，要先答这一条：

- **量**：Implement 段内「找上游答案」标记出现率 vs Collect 段内的同一标记率（用 `scripts/areason_markers.py`
  与 `scripts/switch_point.py` 已有的标记口径，不新造）。
- **判法**：Implement 段的考古率**没有下降** → 本次结论是「**指令没被遵守**」，
  与「分阶段无效」是两回事，「分阶段能不能拦住它」仍然**未被检验**（同 P3 §5.5 的写法）。
- ㊳ **prompt 里加一条规则 ≠ 系统里多了一条规则**。本次成分③（Verify 段摘工具）是唯一做进 scaffold 的那一半，
  成分①②仍然只是「建议」—— 读数时要分开看。

## 四、跑前验证（全 $0，照 P3 §三，每条都要过才准开跑）

1. 假 env 测试全绿 · 真容器测试全绿 · `ruff check agent tests` 无新增
2. **gold 回放 25/25 且 patch 逐字节相同** —— ⚠️ 这条闸**证不了本次改动**：假模型不看工具表【原文 `tests/gold_replay.py:72-75`】，
   它只保证「不传 `tool_policy` 时老路径没变」
3. 冒烟 `p4-smoke` 1 条，肉眼读一遍三段的 Round 指令真的换了
4. 10 条实例 `NetworkMode=none` 全覆盖（P1 立的规矩，逐容器 `docker inspect`）
5. **指纹写进本文件**：`system_prompt` md5 + 三段指令各自 md5 + 段→工具表映射 + 切法（⒞ 的轮数）
6. **余额跑前重读**（`~/s5_balance.sh`）。最近一次收敛读数 **¥36.73**（09-20 11:44 北京，延迟结算 ¥0.97 占 17%）
7. 判据（本文件）**已 commit**，且 `git status` 干净

## 五、成本

- 预算 **≈¥5.8 空闲价**（北京 00:30–08:30），照 ㉖ 三列 × 官方分时单价【推算】。余额 ¥36.73 → 约还够 6 次
- ⚠️ **本跑成本与 09-21 之前不可比**（㉞）：C23 会在工具表变化时插一条 `tools_changed_message`、C24 把裁剪改成了攒 5 条批量折叠，
  两处都动了请求形状
- **本跑顺带是 C24 的第一个实测读数**：直读 traj 的 `steps[].cache_hit_tokens` / `cache_miss_tokens`
  【原文 `agent/loop.py:116-117` 落在 `Step` 上，`agent/run.py:170-183` 把 `steps` 整体写进 `*.traj.json`】。
  ⚠️ **这是读数不是验证** —— 没有同形状的 before，只能与 `docs/EVAL-cache-sim.md` 的模拟值（攒 5 条：
  未命中字符 −53.9%、¥4.35 → ¥2.17、峰值 27,985 → 34,178，经 `16-plan.md:320` 转引）对照，差多少记多少
- ⚠️ **若 §2.1 ⒜ 最后选了「改 `system_prompt`」**，则每进一段都把整棵前缀缓存树作废（㉕），
  成本会明显高于 ¥5.8 —— **那是实现选择的代价，不是 C24 失效**，不许混写

## 六、【未知】（不要用常识填）

1. 三段各切几轮 —— 没有任何数据支持某个切法（§2.1 ⒞）
2. 分阶段能不能拦住 `deepseek-flash` —— 形状不是证据（`16-plan.md:164`）
3. 换指令的实现形状对缓存的影响幅度 —— 只有模拟值，没有实测
4. 对照两条的检验能力 —— 分母 2，自己就在摆（§3.3）
5. `tools_changed_message` 插入会让前缀在哪一轮断 —— C23 上线后**从未真跑过**

## 七、复核命令（每条都能自己跑一遍）

```bash
cd ~/swe-bench-eval

# A 组名单与对照名单的出处
sed -n '18,29p' scripts/p3_preflight.py

# run.py 还没接线（本文件 §2.2）
sed -n '157,164p' agent/run.py
grep -n 'tool_policy\|system_prompt' agent/run.py   # 预期：无输出

# run_episode 的两个形参确实存在（本文件 §2.2）
sed -n '506,516p' agent/loop.py

# 缓存字段确实落盘（本文件 §五）
grep -n 'cache_hit_tokens\|cache_miss_tokens' agent/loop.py
python3 -c "import json;d=json.load(open('results/inference/p3-r1/sympy__sympy-18211.traj.json'));print(list(d['steps'][0].keys()))"

# §3.1 的阈值算法
python3 -c "
from math import comb
for k in (2,3,4,5,6): print(k, round(comb(16,k)/comb(40,k),5))
"
```

## 八、结果（跑完往下补；以上各节不许改）

〔2026-09-22 跑完补写。**§〇–§七 一字未改**。本节内若发现写错，留「已纠正」条目，不静默改。〕

### 8.0 一句话

**主判据过线，但过线的方式不是设计的那个方式。**

分阶段 Round 把 A 组从「三跑 24/24 从未动手」变成 **7/16 动手**（固定边际精确检验单侧 **p = 0.00061**，
远过 §3.1 锁定的 ≥5/16 且两跑各 ≥2）。但：

- **5/7 的首刀落在 Verify 段开始后的 2–6 轮内**，而 `apply_patch` 早在**轮 13**（Implement 段开始）就已放开
  —— 它整整拖了 22 轮不用（§8.3）
- 同期 **Implement 段的考古率不降反升**，三把尺子同向，按 §3.5 预锁读法判为「**指令没被遵守**」（§8.5）

→ 按 §二「一个复合变量，三个成分，不许拆开归功」，结论只能写成
「**这个复合干预让 A 组动手数从 0/24 变成 7/16**」，**不许写成「分阶段设计有效」**；
按 §3.5，「**分阶段能不能拦住它**」**仍然未被检验**。

### 8.1 元信息

| 项 | 值 |
| --- | --- |
| 时间 | AEST 2026-09-22 14:57–15:23（**北京 12:57–13:23，空闲时段**） |
| 退出码 | 0（两跑推理 + 两次评测，fail-closed 三道闸未触发） |
| 样本 | A 组 8 + 对照 2 = 10 条 × 2 跑，`--max-steps 40`，`--staged` |
| infra / error | **0 / 0**（两跑） |
| 容器断网 | `NetworkMode=none` **10/10**（两跑，`p4_run.sh` 逐容器 `docker inspect`，§四 第 4 条） |
| ㉖ 三列 | **0 轮 None**（r1 377 轮 / r2 361 轮，按 `step["index"]` 去重后） |
| 成本 | 余额 **¥36.73 → ¥31.23 = ¥5.50**，§五 预算 ≈¥5.8【推算】命中 |
| 延迟结算 | 15:24 中途读数 ¥31.74 → 16:17 收敛 ¥31.23，**¥0.51 占 9.3%**（P1 20% · P2 8% · 重跑 10%） |
| 余额 | **¥31.23**，空闲价约还够 **5 次** |

### 8.2 §3.1 主判据：**过线**

| | A 组动手数 | 动手的实例 |
| --- | ---: | --- |
| 基线三跑（s5-mine / p2-mine / p2-rerun） | **0/24** | — |
| P3 两跑 | 2/16 | `sphinx-8638`(r1) · `sympy-18211`(r2) |
| **P4 r1** | **4/8** | `pylint-8898` · `sphinx-11510` · `sympy-17630` · `sympy-18211` |
| **P4 r2** | **3/8** | `pylint-4551` · `sympy-17630` · `sympy-18211` |
| **P4 合计** | **7/16** | 去重 **5/8 条**实例至少动手过一次 |

阈值 ≥5/16 且两跑各 ≥2 —— **两条都满足**（4 和 3）。单侧 p = C(16,7)/C(40,7) = **0.00061**。

⚠️ **⑦⑨ 第六次实证**：两跑都动手的只有 `sympy-17630`、`sympy-18211` **2 条**，
**换位 3 条**（r1 的 `pylint-8898`/`sphinx-11510` 在 r2 归零，r2 的 `pylint-4551` 在 r1 归零）。

### 8.3 §3.1 的补量：首刀落在哪个段（**判据没锁这个量**）

| 跑 | 实例 | 首刀轮 | 段 | 距 Implement 开始 | 距 Verify 开始 |
| --- | --- | ---: | --- | ---: | ---: |
| r1 | `pylint-8898` | 34 | VERIFY | +22 | **+2** |
| r1 | `sphinx-11510` | 35 | VERIFY | +23 | **+3** |
| r1 | `sympy-17630` | 34 | VERIFY | +22 | **+2** |
| r1 | `sympy-18211` | 19 | IMPLEMENT | +7 | −13 |
| r2 | `pylint-4551` | 38 | VERIFY | +26 | **+6** |
| r2 | `sympy-17630` | 35 | VERIFY | +23 | **+3** |
| r2 | `sympy-18211` | 15 | IMPLEMENT | +3 | −17 |

**落段分布：VERIFY 5 · IMPLEMENT 2**，而在 Implement 段动手的两次**是同一条实例**（`sympy-18211`）。
**把它去掉，Implement 段动手数 = 0/14。**

【原文 `agent/staged.py` 的 `STAGE_TOOLS`】Verify 段相对 Implement 段唯一的差别是**摘掉 `run_python`**；
`apply_patch` 在两段都可用。→ 首刀的时间点与「**能跑脚本的工具被摘掉**」重合（+2/+3/+2/+6/+3 轮），
**不与「允许动手」重合**（那是 +22~+26 轮之前的事）。

⚠️ **这是【判断】不是结论**：n=5，且「轮数快用完」与「run_python 被摘」在本设计里**完全共线**
（Verify 段就是最后 8 轮）。要分开，得另做一个「摘 `run_python` 但不在末段」的跑。

### 8.4 §3.2 反向指标：失败模式换型**发生了**，而且差点被上游标签盖掉

| | 有 patch 且 resolved | **有 patch 但没过** | 空 patch |
| --- | ---: | ---: | ---: |
| 基线三跑（A 组 0/24 动手） | 0 | **0** | 24 |
| P4 r1 | 2 | **2** | 4 |
| P4 r2 | 2 | **1** | 5 |

有 patch 但没过的三条，逐条开日志核过：

| 实例 | harness 标签 | `failure_reasons` | 日志实际 | 归因 |
| --- | --- | --- | --- | --- |
| `sphinx-11510`(r1) | unresolved | — | F2P `test_include_source_read_event` 挂 | 错 patch |
| `pylint-8898`(r1) | **ambiguous** | `missing_module` | **`1 failed, 19 passed`**，挂的是 F2P `test_csv_regex_error - DID NOT RAISE` | **错 patch** |
| `pylint-4551`(r2) | **ambiguous** | `no_tests_collected` | **`ImportError: cannot import name 'get_annotation' from 'pylint.pyreverse.utils'`**，收集中断 | **错 patch，且更坏 —— 把整个测试收集打断了** |

⚠️ **两条 `ambiguous` 都不是环境问题，是 Agent 自己的 patch 打的。**
`pylint-4551` 的 patch 改的正是 `pylint/pyreverse/utils.py` 与 `writer.py`，删掉了测试模块要导入的 `get_annotation`。

⚠️ **口径陷阱（新，必须记）**：`agent/report.py:11` 与 `:40` 的注释把 `E2_ambiguous` 写成
「harness 自己的 infra_failure / ambiguous 单列，**那是环境的锅**」。这对 harness 的 `ambiguous` **不成立** ——
【原文 `SWE-bench/swebench/harness/infra_failure.py:22,25`】`TIER_ENVIRONMENT` 与 `TIER_AMBIGUOUS` 是两个 tier，
【原文 `SWE-bench/swebench/harness/reporting.py:105-108`】只有 `TIER_ENVIRONMENT` 进 `infra_failure_ids`，
**其余进 `ambiguous_failure_ids`**。照那句注释读数，本次最重要的反向指标会被抹掉 2/3。

**上游自己在同一处写明了**【原文 `SWE-bench/swebench/harness/infra_failure.py:23-24`，紧挨 `TIER_AMBIGUOUS` 的注释】：

> Can come from either a broken environment or **a bad patch**; reported separately
> so it is **never mistaken for a confirmed environment fault**.

—— 上游特意把这一桶单列，就是**为了不让人把它当成已确认的环境故障**；我们的注释正好把它当成了环境故障。

✅ **项目自己的分桶没错**：`agent/report.py --run-id p4-r1/p4-r2` 把这两条都归成 **`M2_fail_to_pass`**，
与逐条读日志一致。**错的是直读 `results.json` 的 `ambiguous_failure_ids`**（09-22 头一版探针正是这么读的）
**和 report.py 里那句注释**。

**按 §3.2 的读法**：错 patch 从 0 增到 3/16，**失败模式换型确实发生了**；但空 patch 仍占 9/16，
**「空 patch → 错 patch」是发生了而不是「大量增加」**，主判据过线与它并列写，不许只写前者。

### 8.5 §3.5 合规性（独立判据）：判「**指令没被遵守**」

A 组每轮打三把尺子（口径不新造：行为层 = `switch_point` 的 ARCH 判定去掉 FIX 短路；
词面层 = `areason_markers` 的 `MARKERS["ARCH"]`）：

| 跑 | 段 | 轮数 | 行为层 ARCH | **可探测轮内** | 词面层 ARCH | 有 reasoning |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| r1 | COLLECT | 96 | 2 (2.1%) | **2/59 = 3.4%** | 19 (19.8%) | 93.8% |
| r1 | IMPLEMENT | 159 | 25 (15.7%) | **25/85 = 29.4%** | 83 (52.2%) | 96.9% |
| r1 | VERIFY | 55 | 0 (0.0%) | 0/0 (n/a) | 24 (43.6%) | 98.2% |
| r2 | COLLECT | 96 | 0 (0.0%) | **0/57 = 0.0%** | 19 (19.8%) | 91.7% |
| r2 | IMPLEMENT | 152 | 25 (16.4%) | **25/80 = 31.2%** | 78 (51.3%) | 96.1% |
| r2 | VERIFY | 56 | 0 (0.0%) | 0/0 (n/a) | 27 (48.2%) | 96.4% |

**三把尺子同向：Implement 段的考古率不但没下降，而且比 Collect 段高一个量级。**
→ 按 §3.5 预锁的判法：**结论是「指令没被遵守」**，与「分阶段无效」是两回事，
「分阶段能不能拦住它」**仍然未被检验**。这是 **㊸ 的第二次实证** —— 摘掉 `search_code`
只换掉了考古的**通道**，模型改用 `run_python` 考古（29.4% / 31.2%）。

⚠️ **判别量被自变量本身掐掉了，所以必须补量**（㊿ 第三次）：
行为层的 ARCH 有两条探测通道（`search_code` 查询里的 PR 词面 + `run_python` 代码的 `classify`），
而**自变量正是「Implement 段起摘掉 `search_code`」**：

- COLLECT 段：两条通道都在
- IMPLEMENT 段：**只剩 `run_python` 一条**
- VERIFY 段：**两条都没有**（工具表里既无 `search_code` 也无 `run_python`）
  → **「Verify 段行为层考古率 0%」是仪器读数，不是事实**；同段词面层仍有 43.6% / 48.2%

所以「按轮算」的跨段比较是拿两把不同灵敏度的尺子比读数。补量后（分母只取**能被探测到的轮**）
结论**更强**而不是更弱：**3.4% / 0% → 29.4% / 31.2%**。

### 8.6 §3.3 对照两条：**不报警**，但按预锁读法不算证据

| 实例 | s5-mine | p2-mine | p2-rerun | **p4-r1** | **p4-r2** |
| --- | ---: | ---: | ---: | ---: | ---: |
| `django-14631` | 0 | 5 | 2 | **5**（首刀 18，RESOLVED） | **0**（空 patch） |
| `sphinx-9711` | 2 | 0 | 2 | **3**（首刀 23，RESOLVED） | **2**（首刀 13，RESOLVED） |

§3.3 锁的读法是「两跑全为 0 才算警报」—— **没有一条两跑全 0，不报警**。
但同一条也锁了：**没掉不算「没弄坏」的证据**（分母 2，它自己在五跑里就摆 0/5/2/5/0）。
`django-14631` 一跑 RESOLVED、一跑空 patch，**它自己的方差仍然能吃掉一次修正的效果**（⑦⑨）。

§2.1 记过的**对照缺口**在本跑成立：两条的自然首刀是 25/38 与 None/22，Collect 闸（轮 1–12）切不到它们
→ 「有没有把本来会动手的弄坏」本跑只覆盖得了 Implement 段那个成分，**Collect 闸的误伤仍记【未知】**。

### 8.7 §五 C24 的第一个真跑缓存读数

| 跑 | 轮数 | None 轮 | hit token | miss token | **命中率** | **峰值 prompt** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| p4-r1 | 377 | **0** | 6,099,072 | 1,528,576 | **80.0%** | **54,850** |
| p4-r2 | 361 | **0** | 5,819,647 | 1,409,944 | **80.5%** | **52,159** |

- **命中率这一面，模拟说对了**：基线整跑直读 58.8%【原文 `EVAL-P2-rerun.md:125-143`】→ 本次 80.0/80.5%，
  未命中占比 41.2% → 20.0%，**相对降 51.5%**，模拟给的是「未命中字符 −53.9%」。
  ⚠️ 口径不同（字符 vs token、25 条 vs 10 条），只能说**同量级同方向**，不是逐项对上。
- **峰值这一面，模拟低估了 61%**：`EVAL-cache-sim` 预测攒 5 条峰值 27,985 → **34,178**，实测 **54,850**。
  当初选「攒 5 条」而不是攒 20/40 的理由之一就是「峰值不撞 64K 窗口」——
  **实测离 64K 只剩 14% 余量**，这条理由的安全边际比当初以为的薄得多。
  ⚠️ 不可比因素已知且未剥离：模拟跑在 25 条**旧**轨迹上，没有 C23 插入的 `tools_changed_message`，
  也没有三段指令本身的字数。**单独归因仍【未知】。**
- ⚠️ 照 §五 最后一条：本跑 §2.1 ⒜ 选的是「骨架 `system_prompt` + 段指令**尾部追加**」，
  **没有**中途改 `messages[0]`，所以不存在「每进一段作废整棵前缀树」那种代价。

### 8.8 仪器：一处已纠正

**已纠正的错误（不静默改）**：09-22 头一版临时探针（`~/p4_probe.py`、`~/p4_read.py`）把
`CUT = (12, 32, 40)` 和 `STAGE_TOOLS` **手抄**了一份进脚本，于是它报的「工具表违规 0」
**只证明「落盘 == 那份手抄表」，不证明「落盘 == 真正发出去的表」** ——
与 09-22 Codex 二审 ⒝「指纹盖不住真正发出去的东西」**同型，同一天犯了第二次**。

已改：`scripts/p4_read.py` 与 `scripts/p4_analysis.py` 一律 `from agent.staged import STAGE_TOOLS, stage_of` 直读。
**重算后违规数仍为 0**（两跑全部步，`tools_declared` 与 `agent/staged.py` 的表逐列表相同）——
**结论没变，但证据链换了一条能站住的。**

### 8.9 §六【未知】结算

| # | 【未知】 | 本跑之后 |
| --- | --- | --- |
| 1 | 三段各切几轮 | **仍【未知】**，且 §8.3 给了反证：Implement 段那 20 轮基本没被用来动手 |
| 2 | 分阶段能不能拦住 `deepseek-flash` | **仍未被检验** —— §3.5 判「指令没被遵守」 |
| 3 | 换指令的实现形状对缓存的影响幅度 | **部分答了**（58.8% → 80.0/80.5%），但与 C23 混在一起，单独归因仍【未知】；峰值比模拟高 61% |
| 4 | 对照两条的检验能力 | **答了，而且是否定的** —— `django-14631` 两跑 5 / 0，自己从 RESOLVED 摆到空 patch |
| 5 | `tools_changed_message` 让前缀在哪一轮断 | **仍【未知】，但已经可查** —— 数据在库里，按轮看 miss 分布即可，**$0** |

### 8.10 本跑新增可讲的事

- **(53) 「过线」和「按设计过线」是两个问题。** 主判据只锁了动手数，没锁在哪动手。7/16 过线，
  但 5/7 的首刀发生在「能跑脚本的工具被摘掉」之后 2–6 轮，而不是「允许动手」之后的第 1 轮。
  预注册挡得住改阈值，挡不住**把量当成机制**。
- **(54) 判别量被自变量本身掐掉。** 合规性判据要比 Implement 段与 Collect 段的考古率，
  而自变量正是「在 Implement 段摘掉 `search_code`」—— 两段的探测灵敏度不一样，Verify 段更是结构性为 0。
  **先问「这把尺子在这个段还量得到吗」**，再看读数。补量后结论更强：3.4%/0% → 29.4%/31.2%。
- **(55) 上游工具给的标签会把你自己的失败摘出去。** harness 把两条标成 `ambiguous`、
  `failure_reasons` 写 `missing_module` / `no_tests_collected`，看起来像环境问题；
  逐条开日志，一条是正常跑完的 `1 failed, 19 passed`，另一条是自己的 patch 删掉了
  `get_annotation` 导致收集中断。**两条都是 Agent 自己打的。** 而 `report.py` 的注释正把
  `ambiguous` 说成「环境的锅」。**上游的桶名不是你的归因。**
- **(56) 模拟对了率、错了峰值。** `EVAL-cache-sim` 的未命中降幅（−53.9% 字符 vs 实测 −51.5% token）
  同量级同方向，但峰值 34,178 vs 实测 54,850，**低估 61%**，而当初选攒 5 条的理由之一正是峰值安全。
  **省钱那一面容易模拟，撞窗口那一面不容易。**

### 8.11 复核命令

```bash
cd ~/swe-bench-eval

# 主表 + §3.1 主判据（段边界与工具表从 agent/staged.py 直读，不手抄）
PYTHONPATH=. python3 scripts/p4_read.py

# §3.5 合规性（含两处补量）+ §3.2 四格 + §五 缓存读数
PYTHONPATH=. python3 scripts/p4_analysis.py

# §3.1 的 p 值
python3 -c "from math import comb; print(round(comb(16,7)/comb(40,7), 5))"

# §8.4 两条 ambiguous 的日志实际（不是标签）
# logs/ 在 .gitignore 里；scripts/p4_collect_eval.sh 已把这两份日志原文摊进 results/
tail -c 400 results/evaluation/p4-r1/pylint-dev__pylint-8898.test_output.txt
grep -n 'ImportError' results/evaluation/p4-r2/pylint-dev__pylint-4551.test_output.txt

# §8.4 项目自己的归因表（两条都归 M2_fail_to_pass，不是 E2_ambiguous）
PYTHONPATH=. .venv/bin/python -m agent.report --run-id p4-r1
PYTHONPATH=. .venv/bin/python -m agent.report --run-id p4-r2

# §8.4 harness 的 ambiguous 到底是什么（不是环境的锅）
sed -n '22,26p' SWE-bench/swebench/harness/infra_failure.py
sed -n '104,109p' SWE-bench/swebench/harness/reporting.py

# §8.1 余额（收敛读数）
bash ~/s5_balance.sh
```
