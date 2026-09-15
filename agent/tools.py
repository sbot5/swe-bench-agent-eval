"""六个工具。全部通过 environment 执行，全部返回统一的 Observation。

写的顺序：read_file -> list_files -> search_code -> apply_patch -> run_tests -> git_diff
规格、验收、决定、实测：docs/DESIGN-tools.md
"""
import posixpath
import re
import shlex
from typing import Final

from agent.environment import REPO_ROOT, DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation

DEFAULT_OFFSET: Final[int] = 1
DEFAULT_LIMIT: Final[int] = 200
DEFAULT_DEPTH: Final[int] = 2
DEFAULT_CONTEXT: Final[int] = 2
MAX_CONTEXT: Final[int] = 10
DEFAULT_MAX_RESULTS: Final[int] = 20
MAX_LINE_CHARS: Final[int] = 500
_TOP_FILES: Final[int] = 5
_MAX_SELECTED_FILES: Final[int] = 400  # 每个文件至少占「文件名 + 1 行」约 25 字符，预算装不下更多；也让命令远离 128KB 单参数上限
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


def _aggregate(files: list[str], base: str, depth: int) -> list[str]:
    """把相对仓库根的文件列表按相对 base 的 depth 层聚合成排好序的输出行；目录行带其下文件总数（L3、L7、L10）"""
    counts: dict[str, int] = {}

    for file in files:
        parts = posixpath.relpath(file, base).split("/")

        max_depth = min(depth, len(parts))

        for i in range(1, max_depth + 1):
            segment = posixpath.join(*parts[:i])
            full = posixpath.normpath(posixpath.join(base, segment))

            is_dir = i < len(parts)

            if is_dir:
                full += "/"

            counts[full] = counts.get(full, 0) + 1

    result: list[str] = []

    for path in sorted(counts):
        count = counts[path]

        if path.endswith("/"):
            result.append(f"{path} ({count} files)")
        else:
            result.append(path)

    return result


def _parse_counts(stdout: str) -> list[tuple[str, int]]:
    """解析 `git grep -c -z` 的输出（每行 `path\\0count\\n`），去重后按路径排序返回 (路径, 命中行数)。

    输出是 tracked / untracked 两次 grep 拼起来的，同一文件出现两次时计数相同（S4、S14）。
    """
    counts: dict[str, int] = {}
    for line in stdout.split("\n")[:-1]:
        path, _, count = line.rpartition("\0")
        counts[path] = int(count)
    return sorted(counts.items())


_RECORD = re.compile(r"([^\0]+)\0(\d+)\0(?:(\d+)\0)?(.*)", re.DOTALL)


def _parse_grep_lines(stdout: str) -> list[tuple[str, int, bool, str] | None]:
    """解析 `git grep -n -z --column -C` 的输出为 (路径, 行号, 是否命中, 行文本)；hunk 分隔 `--` 记为 None。

    命中行比上下文行多一个列号字段；对不上 `path\\0行号\\0` 结构的行（数据文件里的二进制碎片）跳过（S6、S15）。
    """
    records: list[tuple[str, int, bool, str] | None] = []
    for line in stdout.split("\n")[:-1]:
        if line == "--":
            records.append(None)
            continue
        match = _RECORD.fullmatch(line)
        if match is None:
            continue
        path, line_number, column, text = match.groups()
        records.append((path, int(line_number), column is not None, text))
    return records


def _render_hits(
    records: list[tuple[str, int, bool, str] | None],
    max_results: int,
    context: int,
) -> tuple[str, int, bool]:
    """把命中记录排成「文件名一行 + `行号:` 命中 / `行号-` 上下文」的文本，最多 max_results 条命中、不超字符预算。

    返回 (content, 实际显示的命中数, 是否因字符预算停下)。至少保留 1 条命中（S3、S9、S10）。
    """
    out: list[str] = []
    size = 0
    pending: list[str] = []  # 还不确定要不要的行：文件头、分隔符、下一条命中的前文
    kept = 0
    after_match = context + 1  # 距上一条已保留命中的上下文行数；初值让开头的上下文先进 pending
    current_path: str | None = None
    gap = False
    cut_by_budget = False

    def cost(lines: list[str]) -> int:
        return sum(len(line) + 1 for line in lines)

    for record in records:
        if record is None:
            gap = True
            continue

        path, line_number, is_match, text = record
        text = text.replace("\0", "\\0")  # -I 只看前 8000 字节，之后的 NUL 会混进行文本（S15）
        if len(text) > MAX_LINE_CHARS:
            text = f"{text[:MAX_LINE_CHARS]} ... [{len(text) - MAX_LINE_CHARS} more chars in this line]"

        if path != current_path:
            pending = (["", path] if out else [path])
            current_path = path
            after_match = context + 1
        elif gap:
            if after_match <= context:  # 分隔符前面紧跟的是已保留的内容，才需要画出来
                pending = ["--"]
            else:
                pending.append("--")
        gap = False

        line = f"{line_number:>6}{':' if is_match else '-'} {text}"

        if is_match:
            if kept == max_results:
                break
            if kept and size + cost(pending) + len(line) + 1 > MAX_CONTENT_CHARS:
                cut_by_budget = True
                break
            out.extend(pending)
            out.append(line)
            size += cost(pending) + len(line) + 1
            pending = []
            kept += 1
            after_match = 0
        elif after_match < context:  # 上一条命中的后文，直接收
            if size + len(line) + 1 > MAX_CONTENT_CHARS:
                cut_by_budget = True
                break
            out.append(line)
            size += len(line) + 1
            after_match += 1
        else:  # 可能是下一条命中的前文，先挂起
            pending.append(line)
            after_match += 1

    return "\n".join(out), kept, cut_by_budget


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

    # 6. 按 depth 聚合，目录行带文件数；超预算降 depth，参数 depth 保留请求值（L2、L3、L10）
    base = posixpath.relpath(path_validate_result, REPO_ROOT)
    lines = _aggregate(files=files, base=base, depth=depth)
    used_depth = depth

    while len("\n".join(lines)) > MAX_CONTENT_CHARS and used_depth > 1:
        used_depth -= 1
        lines = _aggregate(files=files, base=base, depth=used_depth)

    # 6'. depth=1 仍超预算：按预算截条目，至少留 1 条（同 read_file 决定 19；L2）
    total_entries = len(lines)
    if len("\n".join(lines)) > MAX_CONTENT_CHARS:
        kept: list[str] = []
        size = 0
        for line in lines:
            added = len(line) + (1 if kept else 0)  # 第 2 条起多一个换行
            if kept and size + added > MAX_CONTENT_CHARS:
                break
            kept.append(line)
            size += added
        lines = kept
    omitted = total_entries - len(lines)

    # 7. 组装：降过深度、截过条目都写进 summary；有子目录才给「往里看」的 next_actions（L2、L7）
    summary = f"{len(lines)} entries under {path!r} at depth {used_depth} ({len(files)} files in total)"
    if used_depth < depth:
        summary += f"; depth reduced from {depth} to {used_depth} to fit the output budget"
    if omitted:
        summary += f"; {omitted} of {total_entries} entries omitted"

    has_subdirs = any("/" in posixpath.relpath(f, base) for f in files)

    if omitted:
        next_actions = [
            (
                "The listing is cut at the output budget. List one of the directories shown, "
                "or use search_code if you know a name to look for."
            ),
        ]
    elif used_depth < depth:
        next_actions = [
            (
                f"To see deeper than depth {used_depth}, call list_files on one of the directories shown; "
                f"asking for depth={depth} on {path!r} again will be reduced the same way."
            ),
        ]
    elif has_subdirs:
        next_actions = ["To see inside a directory, call list_files with its path as shown."]
    else:
        next_actions = []

    return Observation.ok(
        summary=summary,
        content="\n".join(lines),
        next_actions=next_actions,
    )


def search_code(
    env: DockerEnvironment,
    pattern: str,
    path: str = ".",
    fixed_string: bool = False,
    context: int = DEFAULT_CONTEXT,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> Observation:
    """在容器仓库里按内容搜：pattern 默认按 PCRE 解释，fixed_string=True 按字面量；每条命中带 context 行上下文。

    没命中 -> ok；参数错 / 正则写错 -> INVALID_ARGUMENT；不存在 -> PATH_NOT_FOUND；越出 REPO_ROOT -> PATH_OUTSIDE_ROOT；
    超时 -> TIMEOUT；其余 -> UNCLASSIFIED。步骤、决定 S1–S15、实测：docs/DESIGN-tools.md §四。
    """
    args_ctx = (
        f"pattern: {pattern!r}, path: {path!r}, fixed_string: {fixed_string!r}, "
        f"context: {context!r}, max_results: {max_results!r}"
    )

    # 1. pattern / fixed_string / context / max_results（S1、S2、S3、S12）
    pattern_problem = None
    if type(pattern) is not str:
        pattern_problem = f"pattern should be str, received: {pattern!r}"
    elif not pattern:
        pattern_problem = "pattern should not be '' (it would match every line)"
    elif "\n" in pattern or "\0" in pattern:
        pattern_problem = f"pattern {pattern!r} contains a newline or '\\x00'; search is line by line"
    if pattern_problem:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=pattern_problem,
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Pass a non-empty, single-line pattern, e.g. 'def get_repr' or r'class \\w+Error'.",
                "This error is about the pattern argument; changing path will not help.",
            ]
        )

    if type(fixed_string) is not bool:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"fixed_string should be bool, received: {fixed_string!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Pass fixed_string=True to search the pattern literally, or omit it to search as a regex.",
            ]
        )

    if type(context) is not int or not 0 <= context <= MAX_CONTEXT:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"context should be an int between 0 and {MAX_CONTEXT}, received: {context!r}",
            content=f"Current args: {args_ctx}",
            next_actions=[
                f"Pass an integer context between 0 and {MAX_CONTEXT}, or omit it to use the default ({DEFAULT_CONTEXT}).",
                f"To see more than {MAX_CONTEXT} lines around a match, call read_file with an offset near its line number.",
            ]
        )

    if (err := _validate_positive_int("max_results", max_results, DEFAULT_MAX_RESULTS, args_ctx)) is not None:
        return err

    # 2. 路径：文件或目录都行，默认 "." 归一化为 REPO_ROOT（S11）
    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    # 3. 第一遍只计数：-c -z 输出小。--untracked 会漏掉已跟踪但匹配 .gitignore 的文件，所以跑两次取并集；
    #    两次都 >1 的退出码原样传出，任一次命中即 0，都没命中才 1（S4、S5、S14）
    quoted_path = shlex.quote(path_validate_result)
    quoted_pattern = shlex.quote(pattern)
    mode = "-F" if fixed_string else "-P"
    count = f"-I {mode} -c -z -e {quoted_pattern} -- {quoted_path}"

    count_result = env.execute(
        f"test -e {quoted_path} || exit {_EXIT_NOT_FOUND}; "
        f"git --literal-pathspecs grep {count}; a=$?; "
        f"git --literal-pathspecs grep --untracked {count}; b=$?; "
        "test $a -gt 1 && exit $a; test $b -gt 1 && exit $b; test $a -eq 0 || test $b -eq 0 || exit 1"
    )

    path_ctx = f"Current args: {args_ctx}, normalised path: {path_validate_result!r}"
    retry_actions = [
        "Retry once with the same arguments.",
        (
            f"If it fails again the same way, stop searching {path!r} and use list_files / read_file instead; "
            "changing the pattern will not fix this."
        ),
    ]

    # 4. 分派：超时先判；1 = 没命中，是 ok；128 = git 拒绝了 pattern（路径已校验过）（S7、S8）
    if count_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"Searching {path!r} timed out after {count_result.duration:.1f}s",
            content=path_ctx,
            next_actions=[
                "Retry once with a narrower path (a subdirectory or a single file).",
                "If a narrower search also times out, stop searching; this is an environment problem.",
            ]
        )

    if count_result.exit_code == _EXIT_NOT_FOUND:
        return Observation.error(
            failure_category=FailureCategory.PATH_NOT_FOUND,
            summary=f"Path: {path!r} does not exist",
            content=path_ctx,
            next_actions=[
                "Call list_files on the parent directory, or on '.', to see which paths actually exist.",
                "Or search from '.' (the default path) and let the results show where the code lives.",
            ]
        )

    if count_result.exit_code == 1:
        next_actions = []
        if not fixed_string:
            next_actions.append(
                "The pattern is a Perl-compatible regex: characters like ( ) [ ] . * + ? | need escaping. "
                "To search for text exactly as written, pass fixed_string=True."
            )
        next_actions += [
            "Binary files and files ignored by .gitignore are not searched.",
            (
                "If several differently-worded searches all find nothing, stop searching for this name "
                "and use list_files to explore the structure instead."
            ),
        ]
        return Observation.ok(
            summary=f"No matches for {pattern!r} under {path!r} ({'literal' if fixed_string else 'regex'} search)",
            content="",
            next_actions=next_actions,
        )

    if count_result.exit_code == 128:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"git grep rejected the pattern {pattern!r} (exit 128)",
            content=f"{path_ctx}, stderr: {count_result.stderr!r}",
            next_actions=[
                (
                    "Fix the regex using the error in stderr (e.g. escape '(' as '\\('), "
                    "or pass fixed_string=True to search the text literally."
                ),
                "If stderr is not about the pattern, stop searching and report it; retrying will not help.",
            ]
        )

    if count_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Searching {path!r} failed with unexpected exit code {count_result.exit_code}",
            content=f"{path_ctx}, exit code: {count_result.exit_code}, stderr: {count_result.stderr!r}",
            next_actions=retry_actions,
        )

    # 5. 按 git 的路径顺序取文件，累计命中数够 max_results 就停（S3、S4）
    counts = _parse_counts(count_result.stdout)
    total_matches = sum(count for _, count in counts)

    selected: list[str] = []
    running = 0
    for file, file_matches in counts:
        selected.append(file)
        running += file_matches
        if running >= max_results or len(selected) == _MAX_SELECTED_FILES:
            break

    # 6. 第二遍只搜点名的文件：--no-index 不看 .gitignore；--column 让命中行比上下文行多一个字段（S5、S6、S14）
    quoted_files = " ".join(shlex.quote(posixpath.join(REPO_ROOT, file)) for file in selected)
    hits_result = env.execute(
        f"git --literal-pathspecs grep --no-index -I {mode} -n -z --column -C {context} "
        f"-e {quoted_pattern} -- {quoted_files}"
    )

    if hits_result.timed_out or hits_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT if hits_result.timed_out else FailureCategory.UNCLASSIFIED,
            summary=f"Collecting matches for {pattern!r} under {path!r} failed after counting {total_matches} matches",
            content=(
                f"{path_ctx}, timed out: {hits_result.timed_out}, exit code: {hits_result.exit_code}, "
                f"stderr: {hits_result.stderr!r}"
            ),
            next_actions=retry_actions,
        )

    # 7. 排版：max_results 和字符预算谁先到听谁的，至少 1 条（S3、S9、S10）
    records = _parse_grep_lines(hits_result.stdout)
    content, shown, cut_by_budget = _render_hits(records, max_results, context)

    # 8. 组装：截断时给命中最多的几个文件，引导收窄 path（S3）
    if shown < total_matches:
        summary = f"Showing the first {shown} of {total_matches} matches for {pattern!r} under {path!r} ({len(counts)} files match)"
        if cut_by_budget:
            summary += "; cut at the output budget"
    else:
        summary = f"{total_matches} matches for {pattern!r} under {path!r} in {len(counts)} files"

    next_actions = [
        "To see more of a match, call read_file with its path and an offset a few lines before its line number.",
    ]
    if shown < total_matches:
        top = sorted(counts, key=lambda item: -item[1])[:_TOP_FILES]
        top_text = ", ".join(f"{file} ({count})" for file, count in top)
        next_actions.append(f"Files with the most matches: {top_text}.")
        if cut_by_budget:
            next_actions.append(
                "Narrow the search with a more specific pattern or a path from above; "
                "raising max_results will not show more, because the output budget is already full."
            )
        else:
            next_actions.append(
                f"Narrow the search with a more specific pattern or a path from above, "
                f"or raise max_results (currently {max_results}) if you need the remaining matches."
            )

    return Observation.ok(
        summary=summary,
        content=content,
        next_actions=next_actions,
    )
