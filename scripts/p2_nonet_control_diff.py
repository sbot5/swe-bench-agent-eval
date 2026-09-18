"""把 p2_nonet_control.py 报出的「输出不同」逐字打出来。一次性诊断脚本。"""
import difflib
import subprocess

IMG = "swebench/sweb.eval.x86_64.django_1776_django-13512:latest"
CMD = ("( source /opt/miniconda3/bin/activate && conda activate testbed && "
       "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 "
       "admin_utils.tests.NestedObjectsTests.test_cyclic ) 2>&1")


def run(no_net: bool) -> tuple[str, str]:
    cmd = ["docker", "run", "--rm", "-w", "/testbed"]
    if no_net:
        cmd.append("--network=none")
    cmd += [IMG, "bash", "-c", CMD]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                       timeout=600, check=False)
    return r.stdout, r.stderr


out_nonet, err_nonet = run(True)
out_net, err_net = run(False)

print(f"stdout 长度: no-net={len(out_nonet)}  with-net={len(out_net)}")
print(f"stderr 长度: no-net={len(err_nonet)}  with-net={len(err_net)}")
print(f"stderr(no-net)={err_nonet[:200]!r}")
print(f"stderr(with-net)={err_net[:200]!r}")
print("=== stdout diff ===")
for line in difflib.unified_diff(out_nonet.splitlines(), out_net.splitlines(),
                                 "no-network", "with-network", lineterm="", n=1):
    print(line)
print("=== end ===")
