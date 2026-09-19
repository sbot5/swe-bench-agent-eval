"""search_code：在容器里 grep。规格与决定见 docs/DESIGN-tools.md（S 系列）。

_parse_counts / _RECORD / _parse_grep_lines / _render_hits 四件只服务本工具（实测）。
"""
import posixpath
import re
import shlex

from agent.environment import REPO_ROOT, DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation
from agent.tools._common import (
    _EXIT_NOT_FOUND,
    _MAX_SELECTED_FILES,
    _TOP_FILES,
    DEFAULT_CONTEXT,
    DEFAULT_MAX_RESULTS,
    MAX_CONTEXT,
    MAX_LINE_CHARS,
    _validate_legal_path,
    _validate_positive_int,
)


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
