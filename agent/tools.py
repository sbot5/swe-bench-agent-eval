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
DEFAULT_DEPTH: Final[int] = 2
_EXIT_NOT_FOUND: Final[int] = 90
_EXIT_IS_DIR: Final[int] = 91
_EXIT_IS_NOT_DIR: Final[int] = 92


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
    """读容器里的一个文件：返回第 offset 起最多 limit 行，带行号，超出字符预算提前截停。

    没读完 -> ok + 续读 offset；空文件 -> ok；参数错 / 是目录 / offset 越界 -> INVALID_ARGUMENT；
    不存在 -> PATH_NOT_FOUND；越出 REPO_ROOT -> PATH_OUTSIDE_ROOT；超时 -> TIMEOUT；其余 -> UNCLASSIFIED。
    七个步骤、决定、错误契约、实测：docs/DESIGN-tools.md §三。
    """
    args_ctx = f"path:{path!r}, offset: {offset!r}, limit: {limit!r}"

    # 1. offset / limit：先查类型再比大小（决定 5、6）
    for name, val, default_val in [
        ("offset", offset, DEFAULT_OFFSET),
        ("limit", limit, DEFAULT_LIMIT),
    ]:
        if (err := _validate_positive_int(name, val, default_val, args_ctx)) is not None:
            return err

    # 2. 路径：通过则拿到归一化后的绝对路径（决定 7–11）
    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    # 3. test 守卫分出不存在 / 是目录；awk 只打印请求范围，总行数 NR 走 stderr（决定 13、14）
    #    awk 程序必须整段在同一对单引号里；不加提前 exit，否则 NR 不是总行数
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

    # 4. 分派：超时必须先判，此时 exit_code 是 None（决定 16、17）
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

    # 5. 此时 exit_code 恒为 0。awk 每行都补 \n，所以 [:-1] 去掉末尾空串；空文件判断先于越界（决定 1、15、18）
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

    # 6. 加行号，按字符预算截停但至少留 1 行；放进去时记行号，break 后的循环变量是被拒的那行（决定 4、19）
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

    # 7. limit 截、预算截都归一为 last < total：没读完就给续读 offset，否则说明已到末尾
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


def list_files(env: DockerEnvironment, path: str = ".", depth: int = DEFAULT_DEPTH) -> Observation:
    """列容器里一个目录：depth 层以内的文件和目录，每行一个相对 REPO_ROOT 的路径，目录带其下文件数。

    参数错 / 是文件 -> INVALID_ARGUMENT；不存在 -> PATH_NOT_FOUND；越出 REPO_ROOT -> PATH_OUTSIDE_ROOT；
    超时 -> TIMEOUT；其余 -> UNCLASSIFIED。七个步骤、决定 L1–L9、实测：docs/DESIGN-tools.md §四。
    """
    args_ctx = f"path: {path!r}, depth: {depth!r}"

    # 1. depth：先查类型再比大小（L1）
    if (err := _validate_positive_int(
        name="depth",
        val=depth,
        default_val=DEFAULT_DEPTH,
        args_context=args_ctx,
    )) is not None:
        return err

    # 2. 路径：默认 "." 归一化为 REPO_ROOT，无需特判（L8）
    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    # 3. test 守卫分出不存在 / 不是目录；-z 保原文件名，--literal-pathspecs 关通配且必须在 ls-files 之前（L4、L5）
    quoted_path = shlex.quote(path_validate_result)

    cmd = (
        f"test -e {quoted_path} || exit {_EXIT_NOT_FOUND}; "
        f"test -d {quoted_path} || exit {_EXIT_IS_NOT_DIR}; "
        f"git --literal-pathspecs ls-files -z --cached --others --exclude-standard -- {quoted_path}"
    )

    exec_result = env.execute(cmd)

    path_ctx = f"Current args: {args_ctx}, normalised path: {path_validate_result!r}"

    # 4. 分派：超时必须先判，此时 exit_code 是 None（同 read_file 决定 16、17；L9）
    if exec_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"Listing {path!r} timed out after {exec_result.duration:.1f}s",
            content=path_ctx,
            next_actions=[
                "Retry once with the same arguments.",
                (
                    f"If it times out again, stop listing {path!r}; this is an environment problem, "
                    "and a smaller depth will not help because every file under the path is still listed."
                ),
            ]
        )

    if exec_result.exit_code == _EXIT_NOT_FOUND:
        return Observation.error(
            failure_category=FailureCategory.PATH_NOT_FOUND,
            summary=f"Path: {path!r} does not exist",
            content=path_ctx,
            next_actions=[
                "Call list_files on the parent directory, or on '.', to see which directories actually exist.",
                "Do not guess other paths one by one; if you do not know where the code lives, use search_code.",
            ]
        )

    if exec_result.exit_code == _EXIT_IS_NOT_DIR:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path: {path!r} is a file, not a directory",
            content=path_ctx,
            next_actions=[
                f"Call read_file on {path!r} to see its contents.",
                "This error is about the path argument; retrying list_files on the same file will not help.",
            ]
        )

    if exec_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Listing {path!r} failed with unexpected exit code {exec_result.exit_code}",
            content=f"{path_ctx}, exit code: {exec_result.exit_code}, stderr: {exec_result.stderr!r}",
            next_actions=[
                "Retry once with the same arguments.",
                (
                    f"If it fails again with the same stderr, stop listing {path!r} "
                    "and continue with other directories; changing the arguments will not fix this."
                ),
            ]
        )

    # 5. 此时 exit_code 恒为 0：-z 输出以 \0 结尾，split 后去掉末尾空串；为空 -> ok 并说明（L9）
    files = exec_result.stdout.split("\0")[:-1]

    if not files:
        return Observation.ok(
            summary=f"Directory {path!r} has no files to list",
            content="",
            next_actions=[
                (
                    "Files ignored by .gitignore (build outputs, __pycache__, *.egg-info) are not listed; "
                    "you should not need to read or edit them."
                ),
                "Call list_files on the parent directory to look elsewhere.",
            ]
        )

    # 6. 按 depth 聚合，目录行带文件数；超预算降 depth（L2、L3）
    # 7. 组装 Observation.ok（L7）
