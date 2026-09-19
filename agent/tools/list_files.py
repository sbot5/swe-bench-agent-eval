"""list_files：列容器里一个目录的 depth 层以内。规格与决定见 docs/DESIGN-tools.md（L 系列）。

_aggregate 只服务本工具（实测：全文件仅 list_files 调用），所以跟着搬过来。
"""
import posixpath
import shlex

from agent.environment import REPO_ROOT, DockerEnvironment
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation
from agent.tools._common import (
    _EXIT_IS_NOT_DIR,
    _EXIT_NOT_FOUND,
    DEFAULT_DEPTH,
    _validate_legal_path,
    _validate_positive_int,
)


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
