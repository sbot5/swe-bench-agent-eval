"""run_tests：在容器里跑测试并判定通过。规格与决定见 docs/DESIGN-tools.md（T 系列、§五）。

_PASSING_STATUSES 是 T10 的白名单，紧跟其后的裸字符串是它的说明，两者必须一起读。
_split_test_targets / _count_statuses 只服务本工具（实测）。
"""
import shlex
from typing import Callable, Final

from agent.environment import DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation
from agent.tools._common import (
    _MAX_FAILED_TESTS_SHOWN,
    CONDA_ACTIVATE,
    DEFAULT_TEST_COMMAND,
    DEFAULT_TEST_TIMEOUT,
    MAX_TEST_TIMEOUT,
    _keep_tail,
    _validate_positive_int,
)

_PASSING_STATUSES: Final[frozenset[str]] = frozenset({"PASSED", "SKIPPED", "XFAIL"})
"""只有这几个状态算「过了」，其余一律算没过 —— 白名单，不是黑名单（T10）。

09-17 S4 的教训：SWE-bench 的 pytest parser 按 `line.startswith(状态)` 认行，
`ERROR: -o/--override-ini expects option=value style.` 被当成一条测试，状态是**带冒号的 `ERROR:`**，
黑名单 `{"FAILED", "ERROR"}` 认不出来，于是一次都没跑起来的运行被报成 `All 1 test(s) passed`。
parser 的输出是第三方数据：key 未必是测试、value 未必是已知状态。全文见 DESIGN-tools.md §五。
"""


def _split_test_targets(target: str) -> list[str] | None:
    """按 shell 规则把 target 拆成一个个测试目标；引号不配对时返回 None（T2）。"""
    try:
        return shlex.split(target)
    except ValueError:
        return None


def _count_statuses(status_map: dict[str, str]) -> dict[str, int]:
    """把 {测试名: 状态} 数成 {状态: 条数}，状态按字母序，输出才稳定。"""
    counts: dict[str, int] = {}
    for status in status_map.values():
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def run_tests(
    env: DockerEnvironment,
    target: str,
    test_command: str = DEFAULT_TEST_COMMAND,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    log_parser: Callable[[str], dict[str, str]] | None = None,
    target_hint: str = "",
) -> Observation:
    """在容器里跑测试：test_command 后面接 target，通过的测试只报数量，失败的报名字和原始输出尾部。

    测试挂了仍然是 ok —— 工具完成了它的活（observation 决定 1、3）。
    一条测试结果都解析不出来 -> UNCLASSIFIED；解析出来的全是「过了」但命令非零退出 -> 同样 UNCLASSIFIED（T11）；
    参数错 -> INVALID_ARGUMENT；超时 -> TIMEOUT。
    test_command / log_parser / target_hint 由 run.py 按实例绑定，模型看不到这三个参数；
    **target 没有默认值**，因为默认跑评分目标等于告诉模型 grader 用哪些测试（T8）。
    决定 T1–T11：docs/DESIGN-tools.md §四。
    """
    args_ctx = f"target: {target!r}, test_command: {test_command!r}, timeout: {timeout!r}"

    # 1. timeout 有硬上限：死循环的测试会把整条实例挂死（T5）
    if (err := _validate_positive_int("timeout", timeout, DEFAULT_TEST_TIMEOUT, args_ctx)) is not None:
        return err

    if timeout > MAX_TEST_TIMEOUT:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"timeout should be at most {MAX_TEST_TIMEOUT} seconds, received: {timeout!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                f"Pass a timeout between 1 and {MAX_TEST_TIMEOUT}, or omit it to use the default ({DEFAULT_TEST_TIMEOUT}).",
                "If the suite really needs longer than that, run a narrower target instead of raising the timeout.",
            ],
        )

    # 2'. target 必填：不给默认目标，模型得自己从仓库里挑测试（T8）
    hint = target_hint or "e.g. 'path/to/tests/test_module.py'"
    if type(target) is not str or not target.strip():
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"target should be a non-empty string naming what to run, received: {target!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                f"Name the tests to run in the form this repository uses: {hint}.",
                "Use list_files or search_code to find the test file that covers the code you edited.",
            ],
        )

    # 2. 拆分后逐个 quote：target 是模型写的，绝不能原样拼进命令（environment 决定 23）
    targets = _split_test_targets(target)
    if targets is None:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"target {target!r} has an unbalanced quote and cannot be split into test targets",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Pass target as plain space-separated test targets, without quotes.",
                "This error is about the target argument; the tests were not run.",
            ],
        )

    quoted_targets = " ".join(shlex.quote(item) for item in targets)
    command = f"{test_command} {quoted_targets}".strip()

    # 3. 测试要在 testbed 环境里跑；stderr 并进 stdout，log_parser 要的是一整份日志（T3）
    exec_result = env.execute(f"( {CONDA_ACTIVATE} && {command} ) 2>&1", timeout=timeout)

    run_ctx = f"Current args: {args_ctx}, command: {command!r}"

    # 4. 超时先判。测试失败的退出码是正常返回，不在这里分派（T6）
    if exec_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"Tests timed out after {timeout}s",
            content=f"{run_ctx}\n\n{_keep_tail(exec_result.stdout, MAX_CONTENT_CHARS // 2)}",
            next_actions=[
                "Run a narrower target: a single test file, or a single test inside it.",
                (
                    "If a single test file also times out, stop running tests and re-read your edit — "
                    "it may have introduced an infinite loop."
                ),
            ],
        )

    log = exec_result.stdout
    status_map = log_parser(log) if log_parser is not None else {}
    counts = _count_statuses(status_map)

    # 5. 一条结果都没有：目标名写错，或者代码根本 import 不了。两者都要模型自己看输出分辨（T7）
    if not status_map:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"No test results could be parsed from the run (exit code {exec_result.exit_code})",
            content=f"{run_ctx}\n\n{_keep_tail(log, MAX_CONTENT_CHARS - len(run_ctx) - 4)}",
            next_actions=[
                (
                    "Read the output above: either the target does not name any test "
                    f"(the command was `{command}`), or the code failed to import."
                ),
                "If it is an import error caused by your own edit, fix the edit; do not rerun the same target.",
                f"If the target is wrong, name it in the form this repository uses: {hint}.",
            ],
        )

    # 6. 通过的测试对模型零信息量，只留数量；没过的给名字（T4）
    not_passing = sorted(name for name, status in status_map.items() if status not in _PASSING_STATUSES)
    tally = ", ".join(f"{count} {status.lower()}" for status, count in counts.items())

    # 6'. 第二道防线：解析出来的全是「过了」，可命令自己非零退出 —— 这一跑不算数（T11）
    #     pytest 测试失败时退出码也非零，所以只在 not_passing 为空时才判，不会误伤正常的失败。
    if not not_passing and exec_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=(
                f"The test command exited with code {exec_result.exit_code} although all "
                f"{len(status_map)} parsed result(s) look passing ({tally}) — the run did not complete"
            ),
            content=f"{run_ctx}\n\n{_keep_tail(log, MAX_CONTENT_CHARS - len(run_ctx) - 4)}",
            next_actions=[
                "Read the output above: the test runner itself failed, so these results do not mean your change works.",
                "If the failure is caused by your own edit (an import error, a syntax error), fix the edit first.",
                f"Otherwise run a different target in the form this repository uses: {hint}.",
            ],
        )

    blocks: list[str] = [run_ctx]
    if not_passing:
        shown = not_passing[:_MAX_FAILED_TESTS_SHOWN]
        listing = "\n".join(f"- {name}" for name in shown)
        if len(not_passing) > len(shown):
            listing += f"\n- ... and {len(not_passing) - len(shown)} more"
        blocks.append(f"Tests that did not pass:\n{listing}")

    spent = sum(len(block) + 2 for block in blocks)
    blocks.append(_keep_tail(log, max(0, MAX_CONTENT_CHARS - spent)))

    if not_passing:
        summary = f"{len(not_passing)} test(s) not passing out of {len(status_map)} ({tally})"
        next_actions = [
            "Read the traceback above, then use search_code / read_file to find the code it points at.",
            "Fix the cause with apply_patch, then run the same target again to confirm it now passes.",
        ]
    else:
        summary = f"All {len(status_map)} test(s) passed ({tally})"
        next_actions = [
            "Call git_diff to review every change you made, then finish if the change is complete.",
            (
                "Passing a narrow target does not mean nothing else broke: "
                "run the tests near the code you edited before finishing."
            ),
        ]

    return Observation.ok(summary=summary, content="\n\n".join(blocks), next_actions=next_actions)
