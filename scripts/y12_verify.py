"""ⓐ′② 的真容器验收。假 env 测不了「宿主机峰值内存有上界」—— 那是本条改动的全部理由。

判据（16-plan.md §②）：
  1. 大输出 -> 宿主机峰值内存有上界
  2. 观察里有完整输出的路径
  3. read_file 能把丢掉的那段读回来
"""
import resource
import sys

from agent.environment import DockerEnvironment
from agent.tools.read_file import read_file
from agent.tools.run_python import run_python

IMAGE = "swebench/sweb.eval.x86_64.sympy_1776_sympy-22714:latest"
MB = 1024 * 1024


def maxrss_mb() -> float:
    """宿主机这个进程的峰值常驻内存（Linux 下 ru_maxrss 单位是 KB）。峰值只涨不跌。"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> int:
    before = maxrss_mb()
    print(f"[host] maxrss before: {before:.1f} MB")

    with DockerEnvironment(IMAGE) as env:
        # 50MB 输出。旧实现（execute + capture_output）会把这 50MB 整份读进宿主机内存。
        obs = run_python(env, "print('A' * 50_000_000)", timeout=120)
        after_run = maxrss_mb()

        print(f"[host] maxrss after run_python: {after_run:.1f} MB  (+{after_run - before:.1f} MB)")
        print(f"[obs ] status={obs.status} summary={obs.summary}")
        print(f"[obs ] content chars: {len(obs.content)}")
        print(f"[obs ] next_actions: {obs.next_actions}")

        head = obs.content[:200].replace("\n", " | ")
        print(f"[obs ] content head: {head}")

        # 判据 3：模型能不能把完整的那份读回来
        # ⚠️ 这一步自己也会吃内存：日志是**一行** 50MB，read_file 的 awk 把整行吐给
        # execute()，而 execute 仍是 capture_output —— 所以单独量一次，别把账算到 run_python 头上
        before_read = maxrss_mb()
        back = read_file(env, "/tmp/agent-overflow/run_python.log", offset=1, limit=1)
        after_read = maxrss_mb()
        print(f"[read] status={back.status} summary={back.summary}")
        print(f"[host] maxrss after read_file: {after_read:.1f} MB  "
              f"(+{after_read - before_read:.1f} MB on this step alone)")

        # 顺带确认它没污染仓库：git status 必须是干净的
        st = env.execute("git status --porcelain")
        print(f"[git ] status --porcelain -> {st.stdout!r}")

    after = maxrss_mb()
    grew = after - before
    grew_run = after_run - before  # 判据 1 只问 run_python 那一步，read_file 是另一条路

    print()
    print(f"[host] maxrss total: {after:.1f} MB (+{grew:.1f} MB overall, "
          f"+{grew_run:.1f} MB from run_python)")
    print("=== 判据 ===")
    ok_mem = grew_run < 10
    ok_path = "/tmp/agent-overflow/run_python.log" in obs.content
    ok_read = str(back.status) == "ok"
    ok_clean = st.stdout.strip() == ""
    print(f"1. 宿主机峰值内存有上界（run_python 那一步 +{grew_run:.1f} MB < 10 MB）: {ok_mem}")
    print(f"2. 观察里有完整输出的路径:                      {ok_path}")
    print(f"3. read_file 能读回那份完整输出:                 {ok_read}")
    print(f"4. 仓库没被污染（git status 干净）:              {ok_clean}")

    return 0 if all([ok_mem, ok_path, ok_read, ok_clean]) else 1


if __name__ == "__main__":
    sys.exit(main())
