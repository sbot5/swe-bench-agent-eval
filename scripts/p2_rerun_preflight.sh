#!/bin/bash
# P2 原样重跑（run-id p2-rerun）跑前零成本探针，2026-09-19。不调模型、不起容器、不花钱。
#
# 「原样」要验的前提：
#   [1] agent/ 相对 6010258（㉖ 落盘三列）没改动；相对 P2 那跑的代码，差异只有 ㉖ 那一处
#   [2] system prompt 指纹与 P2 轨迹里的 bdf7e67c 相同（改 prompt = 成本基线不可比，㉕）
#   [3] 实例集与 p2-mine 完全相同
#   [4] 生效的端点与 key（只印指纹，绝不印 key 本身）
#   [5] run-id 没被占用（不覆盖任何旧产物）
#   [6] docker 在、没有残留容器、25 个镜像都在本机
#   [7] 余额（跑前读数；成本只能写余额差）
set -u
source ~/env.sh
cd ~/swe-bench-eval

echo "[1] HEAD: $(git log --oneline -1)"
echo "[1] 工作区改动: $(git status --short | wc -l) 处"
echo "[1] agent/ 相对 6010258 的改动（空 = 没改）:"
git diff --stat 6010258 -- agent/
echo "[1] P2 结果入库那次（063f4c3）相对 P2 代码（365e9cb）的 agent/ 改动（空 = P2 就跑在 365e9cb 的 agent/ 上）:"
git diff --stat 365e9cb 063f4c3 -- agent/
echo "[1] 这次（6010258）相对 P2 代码（365e9cb）的 agent/ 改动（应只有 ㉖）:"
git diff --stat 365e9cb 6010258 -- agent/

PYTHONPATH=. .venv/bin/python - <<'PY'
import collections
import hashlib
import json
import os
import pathlib
import subprocess

from agent.loop import SYSTEM_PROMPT
from agent.run import load_instances

def md5_8(s):
    return hashlib.md5(s.encode()).hexdigest()[:8]

fps = collections.Counter()
for tf in sorted(pathlib.Path("results/inference/p2-mine").glob("*.traj.json")):
    msgs = json.loads(tf.read_text()).get("messages") or []
    if msgs and msgs[0].get("role") == "system":
        fps[md5_8(msgs[0]["content"])] += 1
print("[2] 当前代码 SYSTEM_PROMPT 指纹:", md5_8(SYSTEM_PROMPT))
print("[2] p2-mine 轨迹里的指纹:      ", dict(fps))

ids = [ln.strip() for ln in open("subset_ids.txt", encoding="utf-8") if ln.strip()]
preds = json.loads(pathlib.Path("results/inference/p2-mine/preds.json").read_text())
p2_ids = set(preds) if isinstance(preds, dict) else {p["instance_id"] for p in preds}
print("[3] subset_ids.txt:", len(ids), "条，去重", len(set(ids)), "条；与 p2-mine 实例集相同:", set(ids) == p2_ids)

key = os.environ.get("OPENAI_API_KEY", "")
print("[4] OPENAI_BASE_URL=", os.environ.get("OPENAI_BASE_URL"))
print("[4] 生效 key 指纹:", md5_8(key.strip()) if key else "<空>", " 长度", len(key))

for d in ("results/inference/p2-rerun", "results/evaluation/p2-rerun",
          "results/inference/p2-rerun-smoke", "results/evaluation/p2-rerun-smoke"):
    print("[5]", "已存在!" if os.path.exists(d) else "空闲  ", d)

insts = load_instances(pathlib.Path("subset_ids.txt"), None)
missing = [i["image"] for i in insts
           if subprocess.run(["docker", "image", "inspect", i["image"]], capture_output=True).returncode != 0]
print("[6] 镜像:", len(insts) - len(missing), "/", len(insts), "在本机；缺:", missing if missing else "无")
PY

echo "[6] docker: $(docker info --format '{{.ServerVersion}}' 2>&1)"
echo "[6] 残留 swebench-agent- 容器: $(docker ps -a --filter name=swebench-agent- -q | wc -l) 个"
echo "[6] 磁盘: $(df -h ~ | tail -1)"
echo "[7] 余额: $(bash ~/s5_balance.sh)"
