"""P2 断网后的回归探针：七个仓库各一条，确认 run_tests 在无网容器里照常跑得起来。$0。

    cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p2_nonet_run_tests_probe.py

为什么要它：`--network=none`（决定 Y2）是为 run_python 加的，但它是**容器级**的，
run_tests 一起被断了网。容器冒烟只验过 astropy 一个仓库；若 sphinx 之类的测试要联网取件，
下一次付费跑会整批报废 —— 这是 ⑬/㉑ 的同型陷阱，在跑前用 $0 排掉。

目标取该实例 PASS_TO_PASS 的第一条：这些是**已知在原始环境里通过**的测试，
断网后仍通过就说明网络不是它们的前提。探针用评分目标不违反 T8/R2 ——
那两条约束的是 Agent 能看到什么，不是我做基础设施体检时能看到什么。
"""
import json
import sys

from agent.environment import DockerEnvironment
from agent.observation import ToolStatus
from agent.run import REPO_ROOT_DIR, build_log_parser, derive_test_command, load_instances
from agent.tools import run_tests


def main() -> int:
    instances = load_instances(REPO_ROOT_DIR / "subset_ids.txt", None)

    by_repo: dict[str, dict] = {}
    for row in instances:
        by_repo.setdefault(row["repo"], row)

    failures: list[str] = []
    for repo, instance in sorted(by_repo.items()):
        instance_id = instance["instance_id"]
        targets = json.loads(instance["PASS_TO_PASS"]) if isinstance(instance["PASS_TO_PASS"], str) \
            else instance["PASS_TO_PASS"]
        if not targets:
            print(f"SKIP {repo:28s} {instance_id}: no PASS_TO_PASS")
            continue
        target = targets[0]
        test_command, _hint = derive_test_command(instance)

        image = f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"
        try:
            with DockerEnvironment(image) as env:
                net = env.execute("python -c \"import socket;socket.create_connection(('pypi.org',443),timeout=5)\"")
                obs = run_tests(env, target, test_command=test_command, timeout=300,
                                log_parser=build_log_parser(instance))
        except Exception as exc:  # noqa: BLE001 - 探针要把每个仓库都跑完，不能一条炸了就停
            print(f"FAIL {repo:28s} {instance_id}: {type(exc).__name__}: {exc}")
            failures.append(repo)
            continue

        online = net.exit_code == 0
        ok = obs.status == ToolStatus.OK and "not passing" not in obs.summary
        print(f"{'PASS' if ok else 'FAIL'} {repo:28s} {instance_id}\n"
              f"     network_reachable={online}  target={target[:70]}\n"
              f"     {obs.summary}")
        if online:
            failures.append(f"{repo} (container still has network!)")
        if not ok:
            failures.append(repo)

    print()
    if failures:
        print(f"PROBE FAILED for: {', '.join(failures)}")
        return 1
    print(f"PROBE OK: {len(by_repo)} repos ran their tests with no network")
    return 0


if __name__ == "__main__":
    sys.exit(main())
