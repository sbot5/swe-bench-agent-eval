"""P2 探针里两条 FAIL 的归因对照：同镜像、同命令，只差一张网卡。$0。

    cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p2_nonet_control.py

两条 FAIL 的假设：
  astropy-7166   —— 已知的 pytest 3.3.1 `-o` 吞目标（§五 ⑤），与网络无关
  django-13512   —— 探针自己喂错了目标格式（PASS_TO_PASS 是 `test_x (a.b.C)`，django 要 `a.b.C.test_x`，T9）

不走 run_tests：要问的是「断网会不会改变测试本身的输出」，解析那一层与这个问题无关，
直接对拍容器里的**原始输出**更硬。命令按 run_tests 第 3 步一字不差地拼（含 -w /testbed）。

读法：两边输出一样 -> 网络不是原因。只在无网那侧失败 -> 是断网造成的，Y2 要重新考虑。
"""
import shlex
import subprocess
import sys

from agent.tools import CONDA_ACTIVATE
from agent.run import REPO_ROOT_DIR, derive_test_command, load_instances

CASES = [
    ("astropy__astropy-7166", "astropy/utils/tests/test_misc.py::test_isiterable"),
    ("django__django-13512", "admin_utils.tests.NestedObjectsTests.test_cyclic"),  # 改成 T9 要求的点号写法
]


def run(image: str, command: str, no_network: bool) -> tuple[int, str]:
    cmd = ["docker", "run", "--rm", "-w", "/testbed"]
    if no_network:
        cmd.append("--network=none")
    cmd += [image, "bash", "-c", command]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                            timeout=600, check=False)
    return result.returncode, result.stdout


def main() -> int:
    instances = {row["instance_id"]: row for row in load_instances(REPO_ROOT_DIR / "subset_ids.txt", None)}
    mismatched = []

    for instance_id, target in CASES:
        instance = instances[instance_id]
        test_command, _ = derive_test_command(instance)
        quoted = " ".join(shlex.quote(item) for item in shlex.split(target))
        command = f"( {CONDA_ACTIVATE} && {test_command} {quoted} ) 2>&1"
        image = f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"
        print(f"=== {instance_id} ===\n    {command}")

        outputs = {}
        for label, no_net in (("no-network", True), ("with-network", False)):
            code, out = run(image, command, no_net)
            outputs[label] = out
            tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
            print(f"    {label:13s} exit={code:<4} last line: {tail[:100]}")

        same = outputs["no-network"] == outputs["with-network"]
        print(f"    -> 输出{'完全相同' if same else '不同'}\n")
        if not same:
            mismatched.append(instance_id)

    if mismatched:
        print(f"差异出现在: {', '.join(mismatched)} —— 断网改变了结果，Y2 要重新考虑")
        return 1
    print("两条都与网络无关：有网 / 无网的原始输出逐字节相同")
    return 0


if __name__ == "__main__":
    sys.exit(main())
