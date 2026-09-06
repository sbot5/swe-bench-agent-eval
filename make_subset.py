"""
从 SWE-bench Verified (500 条) 抽出两个不相交的评测集，共 75 条。

产出
    subset_ids.txt  : 25 条（dev）  —— 开发集，scaffold 迭代时反复跑
    holdout_ids.txt : 50 条（test） —— 留出集，只在最后跑一次

    ⚠️ holdout 防的不是 Agent，是我自己。
    Agent 每次只拿到一个仓库 + 一条 issue，跑完容器就销毁，跨实例没有任何记忆，
    不存在「泄露给它」这回事。真正会累积的是**我的调参决定**：
    每次看到 dev 上的失败就改 prompt / 工具 / 裁剪策略，十轮之后分数变高了，
    但其中有多少是真变强、有多少是记住了这 25 条的特点，我自己分不清。
    holdout 从不参与迭代，所以它的分数没有被我调过。

设计（2026-09-06 已定，见 11-CodingAgent项目执行计划.md §三）

  为什么按 difficulty 分层而不是 repo
      难度是 OpenAI 做 Verified 时标注的（93 位工程师标了 1699 个样本），
      用它能顺势讲标注方法论；更要紧的是**只有它能指导 scaffold 迭代** ——
      「hard 全挂」告诉我该改规划能力，「django 挂得多」什么也没告诉我，
      因为 django 只是碰巧占 46.2%。

  为什么过采样 hard（8/9/8 而不是按比例的 10/13/2）
      测的是能力边界，不是平均分。按比例抽 hard 只有 2 条，看不出边界，
      分层这件事本身就白做了。
      代价要主动说出口：总分因过采样偏低，不能直接和排行榜比，只报分层数字。

  为什么有 repo 上限
      django 全量占 46.2%，三层都会被它主导（hard 层里 48.9%，最严重）。
      不加上限，「难度剖面」会退化成「django 的难度剖面」,
      分不清是「真的难」还是「django 难」。

  为什么 holdout 的 cap 是 6 不是 3
      cap 约束的是**份额**，不是条数。
      dev 的 hard 层 8 条、cap 3 -> 单仓库最多占 37.5%；
      holdout 的 hard 层 16 条，cap 若仍为 3 -> 只有 18.75%，份额差一倍。
      两个集的组成一旦不同，dev 与 holdout 的分数差就分不清是过拟合
      还是组成差异，留出集的意义就没了。所以 cap 随 n 等比放大。
      实测对齐（django 的份额，dev vs holdout）：
          easy    3/8  = 37.5%   vs   6/16 = 37.5%
          medium  3/9  = 33.3%   vs   6/18 = 33.3%
          hard    3/8  = 37.5%   vs   6/16 = 37.5%

  为什么两个集用同一个 seed 也没问题
      不相交是靠 exclude 保证的，不是靠 seed。
      同一个 seed 作用在不同的池子上（holdout 的池子已剔除 dev 那 25 条），
      本来就会产生不同结果。seed 的职责只有一个：同样的输入给同样的输出。
      换个 seed 也行，但没有额外好处，反而多一个要记录的参数。
      main() 里那句 assert 交集为空是冗余的 —— 正因为冗余，
      它验证的是「我以为的机制真的生效了」。不相交是结构上不可能，
      不是碰巧没撞上。

可复现性：要重跑出同样这 75 条，需要记录五样
    1. 数据集与 split（SWE-bench/SWE-bench_Verified, split=test, n=500）
    2. seed
    3. 两组配额与 cap
    4. 排除集（holdout 的池子依赖 dev 的内容）
    5. **抽样算法本身** —— 同一个 seed 配不同算法，结果完全不同
       （这里用的是「拷贝 pool -> rng 打乱 -> 从头贪心扫描 -> repo 计数封顶」）
    -> 所以真正保证可复现的是**把这个文件提交进仓库**，光记 seed 不够。

跑法
    python make_subset.py

验收
    1. 🔴 dev 的 25 条必须一字未变 —— S1 已用 gold patch 验证过那 25 条的环境
       （25/25 resolved）。dev 一变，那个验证就作废，得重跑 S1。
       所以改这个脚本之前先备份：
           cp subset_ids.txt /tmp/dev_before.txt
           python make_subset.py && diff /tmp/dev_before.txt subset_ids.txt
    2. selfcheck() 的九条全 PASS（两个集各跑一遍）
    3. 两集交集为空
    4. 连跑两次，两个文件都逐行相同（验 seed 是不是真的钉住了）
"""

import random
from collections import Counter, defaultdict

from datasets import load_dataset



# ── 已知不可用的实例 ────────────────────────────────────────────────────
# 判据：跑 gold patch（维护者的真实修复）都得不到 resolved。
# 这类实例无论 Agent 做什么都拿不到分，留在集里只会稀释信号。
#
# ⚠️ 只对 holdout 生效，不对 dev 生效。
#    因为 dev 那 25 条已经全部 gold 验证通过（S1: 25/25），里面没有坏的；
#    而一旦把它加进 dev 的排除集，dev 的候选池会从 500 变成 499，
#    同一个 seed 打乱 499 个和打乱 500 个结果完全不同 —— dev 会整体变，
#    已经跑过的 S1-dev 就作废了。
KNOWN_BAD = {
    "django__django-13344":
        "gold patch 下 FAIL_TO_PASS 2/2 通过（修复本身是对的），"
        "但 PASS_TO_PASS 挂 2 条：test_touch (FileBasedCacheTests) 与 "
        "test_expiration (DBCacheWithTimeZoneTests)。两条都是 "
        "「设 N 秒超时 -> time.sleep(N+1) -> 断言已过期」的实时依赖测试。"
        "已验证：孤立跑通过（7.1s）、基线跑完整 cache 套通过（481 条 / 13.3s），"
        "但评测时套件变成 487 条 / 67.9s（test_patch 改了 tests/runtests.py）后失败。"
        "两次独立运行结果完全一致，非 flaky，是判定不稳定。"
        "对应 SWE-bench Verified 论文所述「61.1% 的单元测试会误杀正确解法」的残留。"
        "2026-09-06 排除。",
}


def stratum(difficulty: str) -> str:
    """4 个难度标签压成 3 层。'>4 hours' 只有 3 条，合进 hard。"""
    if difficulty == "<15 min fix":
        return "easy"
    if difficulty == "15 min - 1 hour":
        return "medium"
    return "hard"  # "1-4 hours" + ">4 hours"


def load_pools(exclude):
    """返回 {层: [{'instance_id':..., 'repo':...}, ...]}

    注意最后那个 sort：它保证遍历顺序确定。
    没有它，即使 seed 固定，两次跑也可能不一样（见 PYTHONHASHSEED）。
    """
    ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    pools = defaultdict(list)
    for row in ds:
        if row["instance_id"] not in exclude:
            pools[stratum(row["difficulty"])].append(
                {"instance_id": row["instance_id"], "repo": row["repo"]}
            )
    for s in pools:
        pools[s].sort(key=lambda r: r["instance_id"])
    return pools


# ==========================================================================
# ↓↓↓  这一个函数是你写的。上面下面都是脚手架，不用动  ↓↓↓
# ==========================================================================
def pick(pool, n, cap, rng):
    """从 pool 里挑 n 条，同一个 repo 最多 cap 条。

    参数
      pool : [{'instance_id':..., 'repo':...}, ...]，已按 instance_id 排好序
      n    : 要挑几条
      cap  : 同一 repo 的上限
      rng  : random.Random 实例 —— 所有随机都必须走它，不要用 random.xxx()

    返回
      [instance_id, ...]，长度必须正好 == n

    ------------------------------------------------------------------
    你要做的那个决定（(a) 还是 (b)，两种都能过验收，但面试说法不同）：

      (a) 打乱 pool，从头扫，某条的 repo 没到 cap 就收下，够 n 条就停
          -> 面试说法：「分层随机抽样 + 每仓库上限约束」，一句话说完
          -> 结果仍会偏向大仓库（因为它们在池子里条数多），但被 cap 压住

      (b) 按 repo 轮转：每个 repo 先各取 1 条，不够再第 2 轮、第 3 轮，
          到 cap 或凑够 n 为止
          -> 覆盖最均匀
          -> 面试要多解释一句「我为什么偏离纯随机」

      hard 层里 django 占 48.9%，这个选择在那一层看得出差别。

    ------------------------------------------------------------------
    提示（不看也行）：
      - 打乱用 rng.shuffle(某个列表)，它会原地改，所以先 list(pool) 拷一份
      - 记每个 repo 已取几条：used = Counter()，判断 used[repo] < cap
      - 凑不够 n 条就该报错，不要静默返回少于 n 条 —— 静默是最难查的 bug
    """
    items = list(pool)
    rng.shuffle(items)
    used = Counter()
    result = []
    for item in items:
        repo = item["repo"]
        if used[repo] < cap:
            result.append(item["instance_id"])
            used[repo] += 1
        if len(result) == n: break
    if len(result) < n:
        raise ValueError(f"挑不够 {n} 条，只有 {len(result)} 条可用")
    return result
# ==========================================================================
# ↑↑↑  你写的到此为止  ↑↑↑
# ==========================================================================


def selfcheck(chosen, pools, quota, cap):
    """验收标准的可执行版。九条，全过才算数。"""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            ok = False

    flat = [i for ids in chosen.values() for i in ids]

    total = sum(quota.values())
    check(f"总数 {total}", len(flat) == total, f"实际 {len(flat)}")
    check("无重复", len(set(flat)) == len(flat))

    for s, want in quota.items():
        check(f"{s} 层配额 {want}", len(chosen[s]) == want, f"实际 {len(chosen[s])}")

    for s in quota:
        repo_of = {r["instance_id"]: r["repo"] for r in pools[s]}
        c = Counter(repo_of[i] for i in chosen[s])
        worst = max(c.values()) if c else 0
        check(f"{s} 层 repo 上限 <= {cap}", worst <= cap,
              f"最多的仓库有 {worst} 条 | {dict(c)}")

    all_ids = {r["instance_id"] for s in pools for r in pools[s]}
    check("id 全部存在于数据集", set(flat) <= all_ids)

    return ok

def build(quota, cap, out_path, exclude, seed):
    rng = random.Random(seed)          # 独立实例，不污染全局
    pools = load_pools(exclude)

    chosen = {}
    for s in ("easy", "medium", "hard"):   # 固定顺序，不要用 dict 的遍历顺序
        chosen[s] = pick(pools[s], quota[s], cap, rng)

    ok = selfcheck(chosen, pools, quota, cap)

    flat = [i for s in ("easy", "medium", "hard") for i in chosen[s]]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(flat) + "\n")
    print(f"\n写出 {len(flat)} 条到 {out_path}")
    print(f"seed={seed} quota={quota} repo_cap={cap}")

    if not ok:
        raise SystemExit(1)
    else:
        return flat

def main():
    # dev 的排除集必须保持为空 —— 见 KNOWN_BAD 上方的说明
    dev = build(quota={"easy": 8, "medium": 9, "hard": 8}, cap=3, out_path="subset_ids.txt",
                exclude=frozenset(), seed=42)
    holdout = build(quota={"easy": 16, "medium": 18, "hard": 16}, cap=6, out_path="holdout_ids.txt",
                    exclude=set(dev) | set(KNOWN_BAD), seed=42)

    # 冗余检查。冗余正是它的价值：验证「我以为的机制真的生效了」
    assert set(dev) & set(holdout) == set(), "dev 与 holdout 出现交集"
    assert set(holdout) & set(KNOWN_BAD) == set(), "holdout 里混进了已知不可用实例"
    print()
    print(f"已排除 {len(KNOWN_BAD)} 条已知不可用实例: {sorted(KNOWN_BAD)}")

if __name__ == "__main__":
    main()
