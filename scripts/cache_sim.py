"""在已有轨迹上模拟几种上下文裁剪，量「前缀缓存失效」到底花了多少钱（ⓐ′④ 第一步，$0）。

为什么先模拟再改代码：`EVAL-P2-rerun.md` §4.2 已经实测坐实「每轮重算折叠边界 → 前缀从新折叠那条
断开、其后全部未命中」，但 §4.4 留了一条【未知】——「换一种缓存友好的裁剪能省多少」。
轨迹里落了完整 `messages`（`run.py:180`），所以这件事 $0 就能算，不必先改代码再花钱跑一次。

口径（是【推算】，不是实测）：
  - 每轮的视图 = 该轮 assistant 消息之前的全部历史，按该方案裁一遍 —— 与 `loop.py` 的调用点同构
  - 命中 = 与**上一轮视图**的公共前缀（先按消息逐条比，首条不同的消息再比字符级前缀）
  - 字符 → token 的比例由**本跑自己的** `prompt_tokens` 回归，先报校准误差再报结论
  - DeepSeek 的前缀缓存以 64 token 为块、且跨轮还有更早的树，这里都不建模

用法：
    PYTHONPATH=. .venv/bin/python scripts/cache_sim.py results/inference/p2-rerun
"""
import json
import sys
from pathlib import Path

from agent.loop import (
    KEEP_FULL_OBSERVATIONS,
    _ELIDED_PREFIX,
    build_tool_schemas,
    select_tool_schemas,
    trim_messages,
)

# 空闲价，元/百万 token【原文 EVAL-P2-rerun.md §五】
PRICE_MISS = 1.0
PRICE_HIT = 0.02


# ----------------------------------------------------------------- 候选裁剪

def trim_batched(messages, keep_full, batch):
    """⒝ 攒够 batch 条再批量折叠：折叠边界每 batch 条才动一次，其余与现状逐字相同。

    保护窗口因此在 [keep_full, keep_full + batch) 之间浮动 —— prompt 长一点，换的是
    「每轮断一次前缀」变成「每 batch 轮断一次」。
    """
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    folded = max(0, ((len(tool_indices) - keep_full) // batch) * batch)
    protected = set(tool_indices[folded:])
    return _fold(messages, protected)


def trim_projected(messages, limit):
    """⒜ 照 dsh 改成纯函数投影：每条 tool 消息只看它自己 + 一个常数，投影后永不再变。

    【原文 dsh `context.py:9-18` project_tool_result(limit=520)】。前缀因此永远不会因裁剪而失效，
    代价是**最近的观察也被砍**——这一条不是免费的，脚本把砍掉的字符量单列出来。
    """
    out = []
    for message in messages:
        if message.get("role") != "tool":
            out.append(message)
            continue
        content = message["content"]
        out.append({**message, "content": content if len(content) <= limit else content[:limit]})
    return out


def _fold(messages, protected):
    out = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or index in protected:
            out.append(message)
            continue
        head = message["content"].split("\n</summary>")[0].removeprefix("<summary>\n")
        out.append({**message, "content": f"{_ELIDED_PREFIX} {head}"})
    return out


# ----------------------------------------------------------------- 模拟

def rebuild_views(messages, trim):
    """把一条轨迹还原成「每轮发出去的那份视图」。第 k 个 assistant 消息之前的历史就是第 k 轮发的。"""
    views = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            views.append(trim(messages[:index]))
    return views


def _texts(view):
    return [json.dumps(m, ensure_ascii=False, sort_keys=True) for m in view]


def hit_chars(previous, current):
    """两轮视图的公共前缀字符数。"""
    total = 0
    for old, new in zip(previous, current):
        if old == new:
            total += len(new)
            continue
        common = 0
        for a, b in zip(old, new):
            if a != b:
                break
            common += 1
        return total + common
    return total


def declared_by_turn(steps):
    """每轮声明了哪几个工具。C23 之前的轨迹这一列是 None，表示「当时就是全集」。"""
    out = {}
    for step in steps:
        out.setdefault(step["index"], step.get("tools_declared"))
    return out


def tools_text_for(declared, _cache={}):
    """把该轮的工具表序列化。⚠️ 轨迹里**没有落工具表全文**（`run.py:170-180` 只存 messages），
    所以用当前的 `build_tool_schemas()` 近似当时那份 —— 是【推算】。C23 之后至少工具**名**是准的。
    """
    key = None if declared is None else tuple(declared)
    if key not in _cache:
        schemas = build_tool_schemas()
        if declared is not None:
            schemas = select_tool_schemas(schemas, declared)
        _cache[key] = json.dumps(schemas, ensure_ascii=False, sort_keys=True)
    return _cache[key]


def simulate(all_messages, all_steps, trim):
    """返回 (总字符, 命中字符, 未命中字符, 单轮峰值)。第 1 轮整份都是未命中（冷启动）。

    工具表也在请求前缀里，所以逐轮算进去：**按那一轮实际声明的工具集**重建（决定 C23 之后工具集会变，
    一律用全集会把摘掉工具那几轮的前缀算错）。
    """
    total = hit = peak = 0
    for messages, steps in zip(all_messages, all_steps):
        declared_map = declared_by_turn(steps)
        previous = None
        for turn, view in enumerate(rebuild_views(messages, trim), start=1):
            texts = [tools_text_for(declared_map.get(turn))] + _texts(view)
            size = sum(len(t) for t in texts)
            total += size
            peak = max(peak, size)  # C8 当初的判据是上下文上限，不是钱 —— 峰值必须一起看
            if previous is not None:
                hit += hit_chars(previous, texts)
            previous = texts
    return total, hit, total - hit, peak


# ----------------------------------------------------------------- 实测对照

def measured(all_steps):
    """从轨迹里直读三个读数，按轮去重（同一轮的多个 tool_call 共享同一次请求）。"""
    prompt = hit = miss = 0
    for steps in all_steps:
        seen = {}
        for step in steps:
            seen.setdefault(step["index"], step)
        for step in seen.values():
            prompt += step.get("prompt_tokens") or 0
            hit += step.get("cache_hit_tokens") or 0
            miss += step.get("cache_miss_tokens") or 0
    return prompt, hit, miss


def main(run_dir):
    paths = sorted(Path(run_dir).glob("*.traj.json"))
    if not paths:
        raise SystemExit(f"no trajectories under {run_dir}")

    all_messages, all_steps = [], []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        all_messages.append(data["messages"])
        all_steps.append(data["steps"])

    m_prompt, m_hit, m_miss = measured(all_steps)
    keep = KEEP_FULL_OBSERVATIONS
    narrowed = sum(1 for steps in all_steps for step in steps if step.get("tools_declared") is not None)

    base_total, base_hit, base_miss, base_peak = simulate(
        all_messages, all_steps, lambda ms: trim_messages(ms, keep))
    ratio = m_prompt / base_total  # 字符 → token，单密度：本跑自己回归
    print(f"{len(paths)} 条轨迹 · keep_full={keep} · 工具表 {len(tools_text_for(None)):,} 字符/轮（计入前缀）"
          f"{f' · 其中 {narrowed} 步有 tools_declared' if narrowed else ' · 全部是 C23 之前的轨迹（工具集恒为全集）'}")
    print(f"单密度 {ratio:.4f} token/字符（{base_total:,} 字符 ↔ 实测 prompt {m_prompt:,} token）\n")

    print("== 校准 1：单密度模型 vs 轨迹里的实测值 ==")
    print(f"{'':16} {'模拟 token':>14} {'实测 token':>14} {'偏差':>9}")
    for label, sim, real in (("未命中", base_miss * ratio, m_miss), ("命中", base_hit * ratio, m_hit)):
        gap = (sim - real) / real * 100 if real else float("nan")
        print(f"{label:16} {sim:14,.0f} {real:14,.0f} {gap:+8.1f}%")

    # 两段的字符密度本来就不同：未命中段是刚读进来的代码全文，命中段里有大量中文 summary 与 elided 行。
    # 拿现状这一跑把两个密度各回归一次，再用它们换算候选方案（⚠️ 现状那一行因此必然对齐，不算验证）
    hit_density = m_hit / base_hit
    miss_density = m_miss / base_miss
    print(f"\n== 校准 2：双密度（各自回归）==\n"
          f"命中段 {hit_density:.4f} token/字符（{1 / hit_density:.2f} 字符/token）· "
          f"未命中段 {miss_density:.4f}（{1 / miss_density:.2f} 字符/token）")
    print("→ 未命中段每 token 的字符数更多，与「那一段是代码全文」一致【判断】")

    print("\n== 候选方案 ==")
    print(f"{'方案':26} {'prompt':>11} {'峰值/轮':>9} {'未命中字符':>12} {'降幅':>7} {'输入成本':>9} {'省':>7}")
    base_cost = (m_miss * PRICE_MISS + m_hit * PRICE_HIT) / 1e6

    rows = [("现状 trim_messages(每轮重算)", lambda ms: trim_messages(ms, keep))]
    rows += [(f"⒝ 攒 {n} 条再折叠", (lambda n: lambda ms: trim_batched(ms, keep, n))(n)) for n in (5, 10, 20, 40)]
    rows += [(f"⒜ 纯函数投影 limit={n}", (lambda n: lambda ms: trim_projected(ms, n))(n)) for n in (520, 2000)]

    for label, trim in rows:
        total, hit, miss, peak = simulate(all_messages, all_steps, trim)
        cost = (miss * miss_density * PRICE_MISS + hit * hit_density * PRICE_HIT) / 1e6
        print(f"{label:26} {total * ratio:11,.0f} {peak * ratio:9,.0f} {miss:12,.0f} "
              f"{(miss / base_miss - 1) * 100:+6.1f}% {cost:8.2f}元 {(1 - cost / base_cost) * 100:+6.1f}%")

    print("\n注 1：`未命中字符` 那一列不依赖任何密度假设，是模拟器真正算准的量；成本列是它乘上校准 2 的密度。")
    print("注 2：`prompt` 与 `峰值/轮` 是模型每轮实际收到的量。⒜ 的 prompt 变小不是省钱，是少给模型信息；")
    print("      ⒝ 的 prompt 变大是保护窗口在 [keep_full, keep_full+N) 之间浮动的代价 —— 峰值要留在上下文窗口内。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/inference/p2-rerun")
