"""六个工具。全部通过 environment 执行，全部返回统一的 Observation。

写的顺序：read_file -> list_files -> search_code -> apply_patch -> run_tests -> git_diff
规格、验收、决定、实测：docs/DESIGN-tools.md
"""
import posixpath
import shlex
from typing import Final

from agent.environment import REPO_ROOT, DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation

DEFAULT_OFFSET: Final[int] = 1
DEFAULT_LIMIT: Final[int] = 200
_EXIT_NOT_FOUND: Final[int] = 90
_EXIT_IS_DIR: Final[int] = 91


def _validate_positive_int(name: str, val: object, default_val: int, args_context: str) -> Observation | None:
    """统一校验参数必须为大于等于 1 的整数"""
    summary = None
    if type(val) is not int:  # 不用 isinstance：bool 是 int 的子类
        summary = f"{name} should be int, received: {val!r}"
    elif val < 1:
        summary = f"{name} should be at least 1, received: {val!r}"

    if summary:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=summary,
            content=f"Current args: {args_context}",
            next_actions=[
                f"Pass an integer >= 1 as {name}, or omit {name} to use the default ({default_val}).",
                f"This error is about the {name} argument, not the file; switching to another file will not help.",
            ],
        )
    return None


def _validate_legal_path(path: object, args_context: str) -> str | Observation:
    """校验路径是否合法"""
    if type(path) is not str:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path should be str, received: {path!r}",
            content=f"Current args: {args_context}",
            next_actions=[
                "Pass path as a string relative to the repo root, e.g. 'astropy/io/fits.py'."
            ]
        )
    if not path:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary="Path should not be ''",
            content=f"Current args: {args_context}",
            next_actions=[
                "Pass a non-empty path relative to the repo root, e.g. 'astropy/io/fits.py'."
            ]
        )
    if '\x00' in path:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path: {path!r} includes '\\x00'",
            content=f"Current args: {args_context}",
            next_actions=[
                "Remove the '\\x00' from path and retry."
            ]
        )

    full_path = posixpath.normpath(
        posixpath.join(REPO_ROOT, path)
    )

    if full_path != REPO_ROOT and not full_path.startswith(REPO_ROOT + "/"):
        return Observation.error(
            failure_category=FailureCategory.PATH_OUTSIDE_ROOT,
            summary=f"Path: {path!r} is outside of the root: {REPO_ROOT}",
            content=f"Current args: {args_context}, normalised path: {full_path!r}",
            next_actions=[
                f"Use a path inside {REPO_ROOT}, relative to it, e.g. 'astropy/io/fits.py'.",
                f"Files outside {REPO_ROOT} cannot be read; do not retry with another absolute path outside it.",
            ]
        )

    return full_path


def read_file(
    env: DockerEnvironment,
    path: str,
    offset: int = DEFAULT_OFFSET,
    limit: int = DEFAULT_LIMIT,
) -> Observation:
    """读容器里的一个文件，按行范围返回，带行号。

    参数错 -> INVALID_ARGUMENT；路径越出 REPO_ROOT -> PATH_OUTSIDE_ROOT。
    决定、错误契约、实测：docs/DESIGN-tools.md §三。
    """
    args_ctx = f"path:{path!r}, offset: {offset!r}, limit: {limit!r}"

    # 集中校验各参数
    for name, val, default_val in [
        ("offset", offset, DEFAULT_OFFSET),
        ("limit", limit, DEFAULT_LIMIT),
    ]:
        if (err := _validate_positive_int(name, val, default_val, args_ctx)) is not None:
            return err

    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    quoted_path = shlex.quote(path_validate_result)
    end = offset + limit - 1

    cmd = (
        f"test -e {quoted_path} || exit {_EXIT_NOT_FOUND}; "
        f"test -d {quoted_path} && exit {_EXIT_IS_DIR}; "
        f"awk -v s={offset} -v e={end} "
        f"'NR >= s && NR <= e {{print}} END {{print NR > \"/dev/stderr\"}}' "
        f"{quoted_path}"
    )

    exec_result = env.execute(cmd)

    path_ctx = f"Current args: {args_ctx}, normalised path: {path_validate_result!r}"

    if exec_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"Reading {path!r} timed out after {exec_result.duration:.1f}s",
            content=path_ctx,
            next_actions=[
                "Retry once with the same arguments.",
                (
                    f"If it times out again, stop reading {path!r}; this is an environment problem, "
                    "and a smaller limit will not help because the whole file is still scanned."
                ),
            ]
        )

    if exec_result.exit_code == _EXIT_NOT_FOUND:
        return Observation.error(
            failure_category=FailureCategory.PATH_NOT_FOUND,
            summary=f"Path: {path!r} does not exist",
            content=path_ctx,
            next_actions=[
                "Call list_files on the parent directory to see which files actually exist, then read one of them.",
                "Do not guess other paths one by one; if you do not know where the code lives, use search_code.",
            ]
        )

    if exec_result.exit_code == _EXIT_IS_DIR:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path: {path!r} is a directory, not a file",
            content=path_ctx,
            next_actions=[
                f"Call list_files on {path!r} to see its contents, then read_file one of the files inside it.",
                "This error is about the path argument; retrying read_file on the same directory will not help.",
            ]
        )

    if exec_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Reading {path!r} failed with unexpected exit code {exec_result.exit_code}",
            content=f"{path_ctx}, exit code: {exec_result.exit_code}, stderr: {exec_result.stderr!r}",
            next_actions=[
                "Retry once with the same arguments.",
                (
                    f"If it fails again with the same stderr, stop reading {path!r} and continue with other files; "
                    "changing the arguments will not fix this."
                ),
            ]
        )

    # 此时exit_code恒为0
    lines = exec_result.stdout.split("\n")[:-1]

    try:
        total_lines = int(exec_result.stderr)
    except ValueError:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Reading {path!r} returned an unreadable line count",
            content=f"{path_ctx}, stderr: {exec_result.stderr!r}",
            next_actions=[
                "Retry once with the same arguments.",
                (
                    f"If it fails again with the same stderr, stop reading {path!r} and continue with other files; "
                    "changing the arguments will not fix this."
                ),
            ]
        )

    if total_lines == 0:
        return Observation.ok(
            summary=f"Path: {path!r} is an empty file (0 lines)",
            content="",
            next_actions=[]
        )

    if total_lines < offset:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"offset {offset} is beyond the end of {path!r}, which has {total_lines} lines",
            content=f"{path_ctx}, total lines: {total_lines}",
            next_actions=[
                f"Pass an offset between 1 and {total_lines}, e.g. offset=1 to read from the start.",
                "This error is about the offset argument; the file exists, so switching to another file will not help.",
            ]
        )

    content = ""
    last_line_number: int | None = None

    for idx, line in enumerate(lines, start=offset):
        formatted_line = f"{idx:>6}\t{line}\n"

        if content and len(content) + len(formatted_line) > MAX_CONTENT_CHARS:
            break

        content += formatted_line
        last_line_number = idx

    assert last_line_number is not None  # 第 5 步保证 lines 至少一行；这行只为类型收窄
    content = content.removesuffix("\n")  # render() 自己在 </content> 前加换行

    if last_line_number < total_lines:
        return Observation.ok(
            summary=f"Lines {offset}-{last_line_number} of {path!r} ({total_lines} lines in total)",
            content=content,
            next_actions=[
                f"To continue, call read_file with path={path!r}, offset={last_line_number + 1}, limit={limit}.",
            ]
        )
    else:
        return Observation.ok(
            summary=f"Lines {offset}-{last_line_number} of {path!r}, end of file reached ({total_lines} lines in total)",
            content=content,
            next_actions=[]
        )