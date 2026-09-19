"""apply_patch：按 (old_string, new_string) 锚点改容器里的文件。

规格与决定见 docs/DESIGN-tools.md（P 系列）。
_find_all / _line_number_at / _squeeze_whitespace / _closest_lines / _render_lines 只服务本工具（实测）。
"""
import base64
import difflib
import shlex

from agent.environment import DockerEnvironment
from agent.observation import FailureCategory, Observation
from agent.tools._common import (
    _CLOSEST_LINES,
    _EXIT_IS_DIR,
    _EXIT_NOT_FOUND,
    _EXIT_TOO_LARGE,
    _EXIT_WRITE_FAILED,
    _MAX_AMBIGUOUS_SHOWN,
    _SIMILARITY_FLOOR,
    DEFAULT_EDIT_CONTEXT,
    MAX_EDIT_FILE_BYTES,
    MAX_NEW_STRING_B64,
    _preview,
    _validate_legal_path,
)


def _find_all(haystack: bytes, needle: bytes) -> list[int]:
    """needle 在 haystack 里每次出现的字节偏移，从左到右且不重叠。needle 为空时返回 []。"""
    if not needle:
        return []

    offsets: list[int] = []
    start = 0
    while (index := haystack.find(needle, start)) != -1:
        offsets.append(index)
        start = index + len(needle)  # 不重叠：下一次从本次结尾之后找
    return offsets


def _line_number_at(content: bytes, offset: int) -> int:
    """字节偏移 offset 落在第几行（1 起）。"""
    return content.count(b"\n", 0, offset) + 1


def _squeeze_whitespace(text: str) -> str:
    """逐行去首尾空白、内部连续空白压成一个空格。只用来判断「是不是只差空白」（P7）。"""
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


def _closest_lines(content: str, anchor: str, limit: int = _CLOSEST_LINES) -> list[tuple[int, str]]:
    """按与 anchor 首个非空行的相似度挑出 content 里最像的几行，返回 (行号, 行文本)（P7）。

    相似度低于 _SIMILARITY_FLOOR 的不返回 —— 给一堆不像的行比不给更误导。
    """
    probe = next((line.strip() for line in anchor.splitlines() if line.strip()), "")
    if not probe:
        return []

    # b 固定为 probe：SequenceMatcher 只为第二个序列建索引，换 a 比换 b 便宜
    matcher = difflib.SequenceMatcher(a=None, b=probe, autojunk=False)

    scored: list[tuple[float, int, str]] = []
    for number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        matcher.set_seq1(stripped)
        # 两个上界一个比一个准，都比 ratio() 便宜：先用它们把绝大多数行挡在外面
        if matcher.real_quick_ratio() < _SIMILARITY_FLOOR or matcher.quick_ratio() < _SIMILARITY_FLOOR:
            continue
        ratio = matcher.ratio()
        if ratio >= _SIMILARITY_FLOOR:
            scored.append((ratio, number, line))

    scored.sort(key=lambda item: (-item[0], item[1]))  # 同分按行号，输出才稳定可复现
    return [(number, line) for _, number, line in scored[:limit]]


def _render_lines(text: str, first: int, last: int, context: int) -> str:
    """把 text 第 [first-context, last+context] 行带行号排出来，行号宽度与 read_file 一致。"""
    lines = text.splitlines()
    start = max(1, first - context)
    end = min(len(lines), last + context)
    return "\n".join(f"{number:>6}\t{lines[number - 1]}" for number in range(start, end + 1))


def apply_patch(env: DockerEnvironment, path: str, old_string: str, new_string: str) -> Observation:
    """把容器里某个文件中**唯一出现一次**的 old_string 换成 new_string，返回改动处的上下文。

    找不到 -> ANCHOR_NOT_FOUND；出现多次 -> ANCHOR_AMBIGUOUS；两串相同 -> FILE_UNCHANGED；
    参数错 / 是目录 / 文件过大 -> INVALID_ARGUMENT；不存在 -> PATH_NOT_FOUND；越出 REPO_ROOT -> PATH_OUTSIDE_ROOT；
    超时 -> TIMEOUT；其余 -> UNCLASSIFIED。步骤、决定 P1–P15、实测：docs/DESIGN-tools.md §四。
    """
    args_ctx = (
        f"path: {path!r}, old_string: {_preview(old_string)}, new_string: {_preview(new_string)}"
    )

    # 1. old_string / new_string：空锚点会匹配到任何位置，必须挡掉（P2、P10）
    for name, value in [("old_string", old_string), ("new_string", new_string)]:
        if type(value) is not str:
            return Observation.error(
                failure_category=FailureCategory.INVALID_ARGUMENT,
                summary=f"{name} should be str, received: {value!r}",
                content=f"Current args: {args_ctx}",
                next_actions=[
                    f"Pass {name} as a string copied verbatim from the file.",
                    f"This error is about the {name} argument; switching to another file will not help.",
                ],
            )

    if not old_string:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary="old_string should not be '' (an empty anchor matches nowhere and everywhere)",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Call read_file first, then pass as old_string a block of lines copied verbatim from it.",
                "apply_patch only edits existing text; it cannot create a file or append to the end of one.",
            ],
        )

    if old_string == new_string:
        return Observation.error(
            failure_category=FailureCategory.FILE_UNCHANGED,
            summary="old_string and new_string are identical, so this edit would change nothing",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Pass a new_string that differs from old_string.",
                "If the file already contains the change you wanted, move on instead of editing it again.",
            ],
        )

    encoded_new = base64.b64encode(new_string.encode()).decode()
    if len(encoded_new) > MAX_NEW_STRING_B64:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"new_string is too large to send in one edit ({len(new_string)} chars)",
            content=f"Current args: {args_ctx}",
            next_actions=[
                "Split the change into several smaller apply_patch calls, each anchored on its own block of lines.",
                "Retrying with the same new_string will fail the same way; it has to be split.",
            ],
        )

    # 2. 路径：通过则拿到归一化后的绝对路径（P6）
    path_validate_result = _validate_legal_path(path, args_ctx)
    if isinstance(path_validate_result, Observation):
        return path_validate_result

    # 3. test 守卫 + 大小守卫，再整文件读回来；base64 保证字节与容器里完全一致（P4、P8）
    quoted_path = shlex.quote(path_validate_result)

    read_result = env.execute(
        f"test -e {quoted_path} || exit {_EXIT_NOT_FOUND}; "
        f"test -d {quoted_path} && exit {_EXIT_IS_DIR}; "
        f"test \"$(stat -c %s {quoted_path})\" -le {MAX_EDIT_FILE_BYTES} || exit {_EXIT_TOO_LARGE}; "
        f"base64 -w0 {quoted_path}"
    )

    path_ctx = f"Current args: {args_ctx}, normalised path: {path_validate_result!r}"

    # 4. 分派：超时必须先判，此时 exit_code 是 None（同 read_file 决定 16、17）
    if read_result.timed_out:
        return Observation.error(
            failure_category=FailureCategory.TIMEOUT,
            summary=f"Reading {path!r} before editing timed out after {read_result.duration:.1f}s",
            content=path_ctx,
            next_actions=[
                "Retry once with the same arguments.",
                f"If it times out again, stop editing {path!r}; this is an environment problem.",
            ],
        )

    if read_result.exit_code == _EXIT_NOT_FOUND:
        return Observation.error(
            failure_category=FailureCategory.PATH_NOT_FOUND,
            summary=f"Path: {path!r} does not exist",
            content=path_ctx,
            next_actions=[
                "Call list_files on the parent directory to see which files actually exist.",
                "apply_patch cannot create files; it only edits text that is already there.",
            ],
        )

    if read_result.exit_code == _EXIT_IS_DIR:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path: {path!r} is a directory, not a file",
            content=path_ctx,
            next_actions=[
                f"Call list_files on {path!r} to see its contents, then apply_patch to one of the files inside it.",
                "This error is about the path argument; retrying on the same directory will not help.",
            ],
        )

    if read_result.exit_code == _EXIT_TOO_LARGE:
        return Observation.error(
            failure_category=FailureCategory.INVALID_ARGUMENT,
            summary=f"Path: {path!r} is larger than the {MAX_EDIT_FILE_BYTES} byte edit limit",
            content=path_ctx,
            next_actions=[
                "Edit a smaller file; this one is too large to be edited safely.",
                "Retrying will fail the same way; the limit is on the file, not on the arguments.",
            ],
        )

    if read_result.exit_code != 0:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Reading {path!r} before editing failed with unexpected exit code {read_result.exit_code}",
            content=f"{path_ctx}, exit code: {read_result.exit_code}, stderr: {read_result.stderr!r}",
            next_actions=[
                "Retry once with the same arguments.",
                f"If it fails again with the same stderr, stop editing {path!r}; changing the arguments will not fix this.",
            ],
        )

    # 5. 此时 exit_code 恒为 0。b64decode 失败说明读回来的不是 base64，归 UNCLASSIFIED 而不是静默当空文件
    try:
        # binascii.Error 是 ValueError 的子类，接住 ValueError 就够
        content_bytes = base64.b64decode(read_result.stdout, validate=True)
    except ValueError:
        return Observation.error(
            failure_category=FailureCategory.UNCLASSIFIED,
            summary=f"Reading {path!r} before editing returned output that is not base64",
            content=f"{path_ctx}, stdout head: {read_result.stdout[:200]!r}",
            next_actions=[
                "Retry once with the same arguments.",
                f"If it fails again, stop editing {path!r}; changing the arguments will not fix this.",
            ],
        )

    # 6. 匹配全在宿主机的纯函数里算（照 list_files L10）：容器只负责给原始字节
    content_text = content_bytes.decode("utf-8", errors="replace")
    offsets = _find_all(content_bytes, old_string.encode())

    # 7. 找不到：先答「是不是只差空白」，再给最接近的三行（P7）
    if not offsets:
        # _squeeze_whitespace 不增删行，所以压过的文本里的偏移换算出来就是原文行号（P7）
        squeezed_content = _squeeze_whitespace(content_text).encode()
        squeezed_hits = _find_all(squeezed_content, _squeeze_whitespace(old_string).encode())

        lines = [f"old_string was not found in {path!r}."]
        if squeezed_hits:
            text_lines = content_text.splitlines()
            located = [_line_number_at(squeezed_content, offset) for offset in squeezed_hits]
            lines.append(
                f"It does match {len(squeezed_hits)} place(s) once whitespace is ignored, "
                "so only the indentation or spacing in old_string is wrong. Those places start at:"
            )
            lines += [
                f"{number:>6}\t{text_lines[number - 1]}"
                for number in located[:_MAX_AMBIGUOUS_SHOWN]
            ]
        elif closest := _closest_lines(content_text, old_string):
            lines.append("Closest lines in the file:")
            lines += [f"{number:>6}\t{line}" for number, line in closest]
        else:
            lines.append("No line in the file is even close to the first line of old_string.")

        return Observation.error(
            failure_category=FailureCategory.ANCHOR_NOT_FOUND,
            summary=f"old_string does not appear in {path!r}",
            content="\n".join(lines),
            next_actions=[
                (
                    "Call read_file around the lines above and copy old_string verbatim from its output, "
                    "including leading whitespace (drop the line-number column)."
                ),
                (
                    f"If three edits to {path!r} fail in a row, stop editing this file and re-read it, "
                    "or work on a different file; guessing the text again will not work."
                ),
            ],
        )

    # 8. 出现多次：报全部位置，要求扩大锚点直到唯一（P2）
    if len(offsets) > 1:
        text_lines = content_text.splitlines()
        numbers = [_line_number_at(content_bytes, offset) for offset in offsets]
        shown = numbers[:_MAX_AMBIGUOUS_SHOWN]
        listing = "\n".join(f"{number:>6}\t{text_lines[number - 1]}" for number in shown)
        omitted = len(numbers) - len(shown)

        return Observation.error(
            failure_category=FailureCategory.ANCHOR_AMBIGUOUS,
            summary=f"old_string appears {len(offsets)} times in {path!r}; it has to be unique",
            content=(
                f"First line of each occurrence:\n{listing}"
                + (f"\n... and {omitted} more occurrence(s)" if omitted else "")
            ),
            next_actions=[
                (
                    "Extend old_string with the surrounding lines (e.g. the enclosing def or class line) "
                    "until it matches exactly one of the places above, then retry."
                ),
                (
                    f"If three edits to {path!r} fail in a row, stop editing this file; "
                    "apply_patch never edits more than one occurrence at a time."
                ),
            ],
        )

    # 9. 恰好一次：只回传新片段，前后两段在容器里按字节切开再拼（P5）
    start = offsets[0]
    end = start + len(old_string.encode())
    first_line = _line_number_at(content_bytes, start)
    last_line = _line_number_at(content_bytes, end)

    write_result = env.execute(
        f"tmp=$(mktemp) || exit {_EXIT_WRITE_FAILED}; "
        f"head -c {start} {quoted_path} > \"$tmp\" || exit {_EXIT_WRITE_FAILED}; "
        f"printf %s {shlex.quote(encoded_new)} | base64 -d >> \"$tmp\" || exit {_EXIT_WRITE_FAILED}; "
        f"tail -c +{end + 1} {quoted_path} >> \"$tmp\" || exit {_EXIT_WRITE_FAILED}; "
        # cat 回原文件而不是 mv：保住 inode、权限位和属主（bin/test 这种可执行文件靠它）
        f"cat \"$tmp\" > {quoted_path} || exit {_EXIT_WRITE_FAILED}; "
        "rm -f \"$tmp\""
    )

    if write_result.timed_out or write_result.exit_code != 0:
        return Observation.error(
            failure_category=(
                FailureCategory.TIMEOUT if write_result.timed_out else FailureCategory.IO_ERROR
            ),
            summary=f"Writing the edit back to {path!r} failed",
            content=(
                f"{path_ctx}, timed out: {write_result.timed_out}, exit code: {write_result.exit_code}, "
                f"stderr: {write_result.stderr!r}"
            ),
            next_actions=[
                "Retry once with the same arguments; the file was either left unchanged or is now truncated.",
                f"Call read_file on {path!r} to check its current state before editing it again.",
            ],
        )

    # 10. 新内容在宿主机上算得出来，不用再进容器读一次；给模型看改完长什么样（P12）
    new_text = (
        content_bytes[:start] + new_string.encode() + content_bytes[end:]
    ).decode("utf-8", errors="replace")
    new_last_line = first_line + len(new_string.splitlines()) - 1

    old_line_count = len(old_string.splitlines()) or 1
    new_line_count = len(new_string.splitlines()) or 1

    return Observation.ok(
        summary=(
            f"Edited {path!r}: replaced {old_line_count} line(s) at line {first_line}"
            f"{f'-{last_line}' if last_line != first_line else ''} with {new_line_count} line(s)"
        ),
        content=_render_lines(new_text, first_line, max(first_line, new_last_line), DEFAULT_EDIT_CONTEXT),
        next_actions=[
            "Call run_tests to check the edit, or git_diff to review everything changed so far.",
        ],
    )
