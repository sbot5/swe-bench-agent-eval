"""C21 落盘体量估算：加了 reasoning_content 之后 traj 会涨多少。

为什么先估再改：P1 踩过一次 —— 两条 traj 各 204MB，因为 observation 截断**只保护上下文、
不保护落盘**（EVAL-S5-baseline-nonet.md）。reasoning_content 是**文本**不是数字，
和 ㉖ 那三列不是一个量级，加之前必须先知道会涨到多大。

估法：㉖ 的仪器已经把 reasoning_tokens 落进 p2-rerun 的 traj 了（764 轮全有读数），
拿它 × 每 token 的字符数当代理量。**每 token 字符数用 c21_reasoning_probe.py 的实测**，
不拍脑袋：探针里 174 字符 / 55 token = 3.16，12 字符 / 7 token = 1.71，
61 字符 / 18 token = 3.39 —— 英文推理文本大致 2~3.4 字符/token，取上界 3.4 算最坏。

只读，$0。用法：
  cd ~/swe-bench-eval && python3 scripts/c21_size_est.py
"""
import json
import pathlib

RUN = pathlib.Path("results/inference/p2-rerun")
CHARS_PER_TOKEN = 3.4  # 探针实测的上界，故意取最坏


def main():
    per_instance = []
    total_steps = 0
    steps_with_reading = 0
    steps_none = 0

    for path in sorted(RUN.glob("*.traj.json")):
        data = json.loads(path.read_text())
        steps = data.get("steps") or []
        # 一轮多工具会重复落同一份 usage，按 index 去重（CLAUDE.md ⑮ 的口径更正记过这件事）
        seen = {}
        for step in steps:
            seen.setdefault(step.get("index"), step)

        tokens = 0
        for step in seen.values():
            total_steps += 1
            value = step.get("reasoning_tokens")
            if value is None:
                steps_none += 1
            else:
                steps_with_reading += 1
                tokens += value

        per_instance.append((path.name.replace(".traj.json", ""),
                             tokens, len(seen), path.stat().st_size))

    per_instance.sort(key=lambda row: -row[1])
    grand_tokens = sum(row[1] for row in per_instance)
    grand_bytes = sum(row[3] for row in per_instance)

    print(f"{RUN}：{len(per_instance)} 条 traj，去重后 {total_steps} 轮")
    print(f"  有 reasoning_tokens 读数 {steps_with_reading} 轮 / None {steps_none} 轮")
    print(f"  现有落盘 {grand_bytes / 1e6:.1f} MB\n")

    print(f"{'实例':<34} {'reasoning_tok':>13} {'轮':>4} {'现有KB':>8} {'预计+KB':>8}")
    for name, tokens, turns, size in per_instance[:8]:
        print(f"{name:<34} {tokens:>13,} {turns:>4} {size / 1e3:>8.0f} "
              f"{tokens * CHARS_PER_TOKEN / 1e3:>8.0f}")

    added = grand_tokens * CHARS_PER_TOKEN
    print(f"\n合计 reasoning {grand_tokens:,} token")
    print(f"预计新增 {added / 1e6:.2f} MB（× {CHARS_PER_TOKEN} 字符/token，取实测上界）")
    print(f"→ 一跑从 {grand_bytes / 1e6:.1f} MB 涨到约 {(grand_bytes + added) / 1e6:.1f} MB"
          f"（{(grand_bytes + added) / grand_bytes:.2f} 倍）")
    worst = per_instance[0]
    print(f"最坏单条：{worst[0]} 约 +{worst[1] * CHARS_PER_TOKEN / 1e3:.0f} KB")
    print("\n⚠️ JSON 落盘会把换行写成 \\n（2 字符），实际略高于本估；量级不变。")


if __name__ == "__main__":
    main()
