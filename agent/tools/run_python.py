"""run_python：在容器里跑一段一次性 Python。规格与决定见 docs/DESIGN-tools.md（§四 Y1-Y11）。

能力上等价于 shell（Python 能起子进程），真实边界在容器层：environment 给容器加了 --network=none。
"""
import base64
import shlex

from agent.environment import RUN_PYTHON_LOG, DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation
from agent.tools._common import (
    CONDA_ACTIVATE,
    DEFAULT_SCRIPT_TIMEOUT,
    MAX_CODE_B64,
    MAX_SCRIPT_OUTPUT_CHARS,
    MAX_SCRIPT_TIMEOUT,
    SCRIPT_PATH,
    _keep_tail,
    _preview,
    _tail_with_path,
    _validate_positive_int,
)


def run_python(
    env: DockerEnvironment,
    code: str,
    timeout: int = DEFAULT_SCRIPT_TIMEOUT,
) -> Observation:
    """在容器的 testbed 环境里跑一段一次性 Python 脚本，报退出码和输出尾部。

    脚本自己挂了仍然是 ok —— 工具完成了它的活（observation 决定 1、3，同 run_tests 的 T6）。
    参数错 / code 过大 -> INVALID_ARGUMENT；超时 -> TIMEOUT；脚本文件写不进去 -> UNCLASSIFIED。
    **不解析输出、也不判断脚本「成功」**（Y11）：没有白名单可依据就不做判定，这是 T10 的反面。
    容器没有网卡（environment 的 `--network=none`，Y2），所以联网的代码一定失败。
    工作目录是 /testbed（execute 的 `-w`），`import` 拿到的是仓库里的代码。
    决定 Y1–Y11：docs/DESIGN-tools.md §四。
    """
    args_ctx = f"code: {_preview(code)}, timeout: {timeout!r}"

    # 1. timeout 有硬上限，且比 run_tests 的 900 紧：execute 的超时只杀宿主机上的客户端，
    #    容器里的死循环还活着，所以上限必须由本层守住（Y7、T5 同理）
    if (err := _validate_positive_int("timeout", timeout, DEFAULT_SCRIPT_TIMEOUT, args_ctx)) is not None:
        return err

    if timeout > MAX_SCRIPT_TIMEOUT:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"timeout should be at most {MAX_SCRIPT_TIMEOUT} seconds, received: {timeout!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                (
                    f"Pass a timeout between 1 and {MAX_SCRIPT_TIMEOUT}, or omit it to use the default "
                    f"({DEFAULT_SCRIPT_TIMEOUT})."
                ),
                "A one-off script should finish in seconds; if it needs longer, make it do less.",
            ],
        )

    # 2. code 必须是非空 str
    if type(code) is not str or not code.strip():
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"code should be a non-empty string of Python source, received: {code!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Pass the whole script as one string, exactly as you would write it in a .py file.",
                "This error is about the code argument; the script was not run.",
            ],
        )

    # 3. base64 送进去：code 是模型写的，含任意引号、换行、$ 和反引号，绝不能原样拼进命令（Y1，同 P5）
    encoded = base64.b64encode(code.encode()).decode()
    if len(encoded) > MAX_CODE_B64:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"code is too large to send in one command ({len(encoded)} base64 chars, limit {MAX_CODE_B64})",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Write a shorter script: reproduce one behaviour, not the whole test suite.",
                "If you need repository code, import it instead of pasting it into the script.",
            ],
        )

    quoted_script = shlex.quote(SCRIPT_PATH)

    # 3'. 写和跑分成两条命令，不用哨兵退出码（Y5）：脚本自己可以 sys.exit(94)，
    #     单条命令里的 `|| exit 94` 会把它误判成「文件没写进去」。apply_patch 没有这个问题，
    #     是因为它的 94 之后不再跑用户代码。
    write_result = env.execute(
        f"printf %s {shlex.quote(encoded)} | base64 -d > {quoted_script}",
        timeout=60,
    )
    if write_result.timed_out or write_result.exit_code != 0:
        detail = "timed out" if write_result.timed_out else f"exit code {write_result.exit_code}"
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Could not write the script to {SCRIPT_PATH} in the container ({detail})",
            content=f"Current args: {args_ctx}\n\n{_keep_tail(write_result.stderr, MAX_CONTENT_CHARS // 2)}",
            next_actions=[
                "This is not about your code; the container could not be written to.",
                "Retry once. If it fails again, stop using run_python and work with read_file and apply_patch.",
            ],
        )

    run_ctx = f"Current args: {args_ctx}, script written to {SCRIPT_PATH}"

    # 4. 在 testbed 环境里跑；stderr 并进 stdout，traceback 和 print 的相对顺序才是对的（同 T3）。
    #    **完整输出留在容器里**（Y12）：execute() 是 capture_output=True，整份 stdout 会先进
    #    宿主机内存，而 run_python 是唯一能产生任意大输出的工具（P1 实测 mini 两条 trajectory
    #    各 204MB）。改走 execute_to_file 之后，宿主机峰值才真的有上界 —— 原来的 _keep_tail
    #    只是不再复制第二份，那一份早就在内存里了。
    #    顺带把截断变成**可恢复的**：丢掉的那段还在容器里，模型能用 read_file 取回。
    budget = max(0, MAX_SCRIPT_OUTPUT_CHARS - len(run_ctx) - 4)
    exec_result = env.execute_to_file(
        f"{CONDA_ACTIVATE} && python {quoted_script}",
        log_name=RUN_PYTHON_LOG,
        tail_bytes=budget,
        timeout=timeout,
    )

    # 5. 超时先判。脚本自己非零退出是正常返回，不在这里分派（同 T6）
    #    超时这条路现在也能拿到输出：容器里的文件照读，不依赖 TimeoutExpired 那份 partial output
    if exec_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"The script timed out after {timeout}s",
            content=f"{run_ctx}\n\n{_tail_with_path(exec_result)}",
            next_actions=[
                "The script did not finish: make it do less, or add a print so you can see where it stops.",
                "If it looks like an infinite loop caused by your own edit, re-read the edit instead of rerunning.",
            ],
        )

    # 6. 截断已经在容器里做完了（Y12），这里只把「丢了多少 + 去哪读完整的那份」写给模型
    output = _tail_with_path(exec_result)
    blocks = [run_ctx, output if output.strip() else "(the script produced no output)"]

    # 7. 不判断脚本「成功」，只如实报退出码（Y4、Y11）。单位随截断口径改成字节（Y12）
    produced = f"{exec_result.total_bytes} bytes of output"
    if exec_result.exit_code == 0:
        summary = f"Script finished with exit code 0 ({produced})"
        next_actions = [
            "Read the output above: it is evidence about how the code behaves now, not proof that the issue is fixed.",
            "If this reproduces the issue, fix the cause with apply_patch and run the same script again to compare.",
        ]
    else:
        summary = f"Script exited with code {exec_result.exit_code} ({produced})"
        next_actions = [
            (
                "Read the traceback above: a non-zero exit may be the bug you are reproducing, "
                "or a mistake in the script itself."
            ),
            (
                "If the script is what is wrong (a NameError, a wrong import path), fix the script, "
                "not the repository."
            ),
        ]

    # 截断时多给一条路：丢掉的那段不是没了，是在容器里（Y12）
    if exec_result.truncated:
        next_actions.append(
            f"Only the tail is shown; the complete output is at {exec_result.path} "
            f"— read_file that path if you need the earlier part."
        )

    return Observation.ok(summary=summary, content="\n\n".join(blocks), next_actions=next_actions)
