"""真 token 统计。⚠️ 一轮多个 tool_call 会落多条 StepRecord 且共享同一轮的 token，
必须按 step['index']（模型轮数）去重，否则重复计数。
"""
import json, pathlib

def scan(run):
    tot_in = tot_out = turns = 0
    per = {}
    for tf in sorted(pathlib.Path(f"results/inference/{run}").glob("*.traj.json")):
        d = json.loads(tf.read_text())
        seen = {}
        for st in d.get("steps", []):
            seen.setdefault(st["index"], (st["prompt_tokens"], st["completion_tokens"]))
        i = sum(v[0] for v in seen.values())
        o = sum(v[1] for v in seen.values())
        per[d["instance_id"]] = (i, o, len(seen), d.get("api_calls"))
        tot_in += i; tot_out += o; turns += len(seen)
    return tot_in, tot_out, turns, per

s5 = scan("s5-mine"); p2 = scan("p2-mine"); sm = scan("p2-smoke")
print(f"{'':<8}{'输入 tok':>14}{'输出 tok':>13}{'去重轮数':>10}")
for name, r in (("S5", s5), ("P2", p2), ("冒烟", sm)):
    print(f"{name:<8}{r[0]:>14,}{r[1]:>13,}{r[2]:>10,}")
print(f"{'P2/S5':<8}{p2[0]/s5[0]:>14.2f}{p2[1]/s5[1]:>13.2f}{p2[2]/s5[2]:>10.2f}")

# 交叉验算：两跑两方程解输入/输出单价（元/百万 token）。无需外部价格表。
S5_YUAN, P2_YUAN = 5.27, 10.23      # 余额差；P2 含冒烟那 1 条
a1, b1, c1 = s5[0]/1e6, s5[1]/1e6, S5_YUAN
a2, b2, c2 = (p2[0]+sm[0])/1e6, (p2[1]+sm[1])/1e6, P2_YUAN
det = a1*b2 - a2*b1
if abs(det) < 1e-9:
    print("\n两跑的输入/输出比例几乎相同，解不出单价（方程退化）")
else:
    p_in = (c1*b2 - c2*b1) / det
    p_out = (a1*c2 - a2*c1) / det
    print(f"\n=== 两跑联立反推单价（元/百万 token）===")
    print(f"  输入 {p_in:.3f}   输出 {p_out:.3f}")
    print(f"  ⚠️ 负数或离谱值 = 模型不成立（说明两跑的缓存命中率不同，不能用同一对单价）")
    print(f"  校验：S5 预测 ¥{a1*p_in + b1*p_out:.2f} (实 {S5_YUAN})，P2 预测 ¥{a2*p_in + b2*p_out:.2f} (实 {P2_YUAN})")

print(f"\n=== 单位成本 ===")
print(f"  S5: ¥{S5_YUAN/25:.3f}/条   P2: ¥{P2_YUAN/26:.3f}/条（26 = 25 + 冒烟 1）")
print(f"  按输入 tok 算元/百万： S5 {S5_YUAN/(s5[0]/1e6):.2f}   P2 {P2_YUAN/((p2[0]+sm[0])/1e6):.2f}")
