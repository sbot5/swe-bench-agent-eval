"""git_diff：取容器里仓库的当前 diff，也就是最终提交的 patch。

规格与决定见 docs/DESIGN-tools.md（G 系列）。
"""
import shlex

from agent.environment import DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation
from agent.tools._common import (
    _validate_legal_path,
)


def git_diff(env: DockerEnvironment, path: str = ".") -> Observation:
    """给模型看它自己到目前为止改了什么：`git diff` 的统计行 + 正文，外加未跟踪文件清单。

    这是 Agent 自查用的；harness 提取答案走 run.py 的 extract_patch，不占 Agent 步数（G1）。
    参数错 -> INVALID_ARGUMENT；越出 REPO_ROOT -> PATH_OUTSIDE_ROOT；超时 -> TIMEOUT；其余 -> UNCLASSIFIED。
    """
    args_ctx = f"path: {path!r}"

    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    quoted_path = shlex.quote(path_validate_result)
    path_ctx = f"Current args: {args_ctx}, normalised path: {path_validate_result!r}"

    retry_actions = [
        "Retry once with the same arguments.",
        "If it fails again the same way, stop calling git_diff and continue with the task; it is only a self-check.",
    ]

    # 1. 统计行和未跟踪清单**分两条命令**取：两段都以空格开头，混在一条 stdout 里分不开；
    #    串成 `a; b` 还会让 a 的退出码被 b 顶掉（不在 git 仓库时会静默报「没有改动」）（G2）
    stat_result = env.execute(f"git --no-pager --literal-pathspecs diff --stat -- {quoted_path}")

    if stat_result.timed_out or stat_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT if stat_result.timed_out else FailureCategory.UNCLASSIFIED,
            summary="git diff --stat failed",
            content=f"{path_ctx}, timed out: {stat_result.timed_out}, "
                    f"exit code: {stat_result.exit_code}, stderr: {stat_result.stderr!r}",
            next_actions=retry_actions,
        )

    others_result = env.execute(
        f"git --literal-pathspecs ls-files -z --others --exclude-standard -- {quoted_path}"
    )
    # 未跟踪清单取不到不算失败：它只是自查里的附注，不值得让整个 git_diff 报错
    others = others_result.stdout.split("\0")[:-1] if not others_result.timed_out and others_result.exit_code == 0 else []

    stat_lines = stat_result.stdout.strip().split("\n") if stat_result.stdout.strip() else []
    untracked = [f"?? {path}" for path in others]
    stat = "\n".join(stat_lines + untracked)

    if not stat_lines:
        if not untracked:
            return Observation.ok(
                summary="No changes yet: the working tree is identical to the base commit",
                content="",
                next_actions=[
                    "Use apply_patch to make the change the issue asks for; nothing has been edited so far.",
                ],
            )
        return Observation.ok(
            summary=f"No tracked file has been modified; {len(untracked)} untracked file(s) exist",
            content=stat,
            next_actions=[
                "Untracked files are not part of the answer; edit the existing source files with apply_patch instead.",
            ],
        )

    # 2. 正文单独取：--stat 已经说清楚改了几个文件，正文超预算时截头部（G3）
    diff_result = env.execute(f"git --no-pager --literal-pathspecs diff -- {quoted_path}")

    if diff_result.timed_out or diff_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT if diff_result.timed_out else FailureCategory.UNCLASSIFIED,
            summary="git diff failed after --stat succeeded",
            content=f"{path_ctx}, timed out: {diff_result.timed_out}, "
                    f"exit code: {diff_result.exit_code}, stderr: {diff_result.stderr!r}\n\n{stat}",
            next_actions=retry_actions,
        )

    body = diff_result.stdout
    budget = MAX_CONTENT_CHARS - len(stat) - 4
    cut = len(body) > budget
    if cut:
        body = body[:budget] + f"\n[TRUNCATED: {len(diff_result.stdout) - budget} more chars of diff]"

    next_actions = [
        "If anything above is not needed to fix the issue, revert that part with apply_patch before finishing.",
    ]
    if untracked:
        next_actions.append(
            "The '?? ' lines are files you created that are not part of the diff; "
            "delete them unless the fix really needs them."
        )
    if cut:
        next_actions.append(
            "The diff is cut at the output budget; call git_diff on a single file to see the rest."
        )

    # --stat 最后一行就是「N files changed, ...」，直接拿来当 summary，不自己数一遍
    tally = stat_lines[-1].strip()
    if untracked:
        tally += f", {len(untracked)} untracked file(s)"

    return Observation.ok(
        summary=f"Changes so far under {path!r}: {tally}",
        content=f"{stat}\n\n{body}",
        next_actions=next_actions,
    )
