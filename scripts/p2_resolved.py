import json, pathlib

def load(run_id):
    p = pathlib.Path(f"logs/evaluation/{run_id}/results.json")
    d = json.loads(p.read_text())
    return set(d["resolved_ids"]), set(d["empty_patch_ids"]), set(d["unresolved_ids"]), d

p2r, p2e, p2u, p2d = load("p2-mine")
s5r, s5e, s5u, s5d = load("s5-mine")

print(f"S5 resolved {len(s5r)}/25  空 patch {len(s5e)}  有 patch 但没过 {len(s5u)}")
print(f"P2 resolved {len(p2r)}/25  空 patch {len(p2e)}  有 patch 但没过 {len(p2u)}")
print(f"\n两边都过 ({len(p2r & s5r)}):")
for k in sorted(p2r & s5r):
    print("   ", k)
print(f"\n只有 P2 过 ({len(p2r - s5r)}):")
for k in sorted(p2r - s5r):
    print("   ", k)
print(f"\n只有 S5 过 ({len(s5r - p2r)}):")
for k in sorted(s5r - p2r):
    print("   ", k)
print(f"\n空 patch：S5 {len(s5e)} 条  P2 {len(p2e)} 条")
print(f"  两边都空 ({len(p2e & s5e)}): {sorted(p2e & s5e)}")
print(f"  只有 P2 空 ({len(p2e - s5e)}): {sorted(p2e - s5e)}")
print(f"  只有 S5 空 ({len(s5e - p2e)}): {sorted(s5e - p2e)}")
print(f"\n有 patch 但没过：S5 {sorted(s5u)}\n                P2 {sorted(p2u)}")
