"""工具层的共享件：常量、参数校验、两个跨工具的格式化 helper。

常量集中在这里而不是跟着各工具分散：DESIGN-tools.md 的 P/T/G/L/S/Y 编号大量引用它们，
集中一处好查；分散则 run_tests 要去 import run_python 的常量，凭空多出横向依赖。

_validate_positive_int / _validate_legal_path 被 5 个工具用，_preview 被 2 个，_keep_tail 被 2 个。
"""
import posixpath
from typing import Final

from agent.environment import OVERFLOW_DIR, OVERFLOW_LOGS, REPO_ROOT, TailResult
from agent.observation import MAX_CONTENT_CHARS, FailureCategory, Observation

DEFAULT_OFFSET: Final[int] = 1
DEFAULT_LIMIT: Final[int] = 200
DEFAULT_DEPTH: Final[int] = 2
DEFAULT_CONTEXT: Final[int] = 2
MAX_CONTEXT: Final[int] = 10
DEFAULT_MAX_RESULTS: Final[int] = 20
MAX_LINE_CHARS: Final[int] = 500
DEFAULT_EDIT_CONTEXT: Final[int] = 3
DEFAULT_TEST_TIMEOUT: Final[int] = 300
MAX_TEST_TIMEOUT: Final[int] = 900
DEFAULT_TEST_COMMAND: Final[str] = "python -m pytest -rA"
# 每条实例的测试命令从它自带的 eval_script 里抽（P13）；这里只是 run.py 没传时的兜底
CONDA_ACTIVATE: Final[str] = "source /opt/miniconda3/bin/activate && conda activate testbed"
MAX_EDIT_FILE_BYTES: Final[int] = 2 * 1024 * 1024  # apply_patch 是唯一整读文件的工具，要自己设上限（P8）
MAX_NEW_STRING_B64: Final[int] = 64 * 1024  # base64 后要塞进 docker exec 的单参数，离 128KB 上限留一半余量（P5）
DEFAULT_SCRIPT_TIMEOUT: Final[int] = 60
MAX_SCRIPT_TIMEOUT: Final[int] = 300  # 比 run_tests 的 900 紧：一次性复现脚本不该跑几分钟（Y7）
MAX_CODE_B64: Final[int] = 64 * 1024  # 与 MAX_NEW_STRING_B64 同理由（Y1）
SCRIPT_PATH: Final[str] = "/tmp/agent_run_python.py"  # 写 /tmp 不写 /testbed，否则 git_diff 会列成未跟踪文件（Y9）
# read_file 能读回的那几份溢写日志的**完整路径**。清单的唯一来源是 environment.OVERFLOW_LOGS
# —— 能写进去的和能读回来的必须是同一份，分两处写早晚会错开（Y12）
_OVERFLOW_LOG_PATHS: Final[frozenset[str]] = frozenset(
    f"{OVERFLOW_DIR}/{name}" for name in OVERFLOW_LOGS
)
MAX_SCRIPT_OUTPUT_CHARS: Final[int] = MAX_CONTENT_CHARS  # 工具层就截断，不把整份交给 Observation（Y6）
_TOP_FILES: Final[int] = 5
_MAX_SELECTED_FILES: Final[int] = 400  # 每个文件至少占「文件名 + 1 行」约 25 字符，预算装不下更多；也让命令远离 128KB 单参数上限
_CLOSEST_LINES: Final[int] = 3
_SIMILARITY_FLOOR: Final[float] = 0.5
_MAX_AMBIGUOUS_SHOWN: Final[int] = 20
_MAX_FAILED_TESTS_SHOWN: Final[int] = 25
_EXIT_NOT_FOUND: Final[int] = 90
_EXIT_IS_DIR: Final[int] = 91
_EXIT_IS_NOT_DIR: Final[int] = 92
_EXIT_TOO_LARGE: Final[int] = 93
_EXIT_WRITE_FAILED: Final[int] = 94


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


def _validate_legal_path(path: object, args_context: str, *,
                         allow_overflow: bool = False) -> str | Observation:
    """校验路径是否合法。

    allow_overflow 只给 read_file 开（Y12）：溢写日志在 OVERFLOW_DIR，那是 REPO_ROOT **之外**
    —— 放仓库里的话 git_diff 会把它列成未跟踪文件（Y9 当初把脚本挪出去就是这个理由）。
    口子开得尽量窄：只放行那一个目录下的路径，其余 5 个调用方一个字都不动，
    尤其 apply_patch 拿不到这个开关 —— 模型能读那份输出，但改不了它。
    """
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

    # 溢写日志的例外：**逐个文件**放行，不是放行那个目录 —— 模型能用 run_python 往
    # OVERFLOW_DIR 写文件，按目录放行等于让它自己造一条读任意内容的路（Codex 审稿 MAJOR-1）
    if allow_overflow and full_path in _OVERFLOW_LOG_PATHS:
        return full_path

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


def _preview(value: object, limit: int = 60) -> str:
    """把参数缩成一行短引用给错误信息用；字符串超长则截断并标出总长度（P14）。"""
    if not isinstance(value, str):
        return repr(value)
    if len(value) <= limit:
        return repr(value)
    return f"{value[:limit]!r}... ({len(value)} chars in total)"


def _keep_tail(text: str, limit: int) -> str:
    """只保留尾部 limit 个字符，丢掉的部分换成一行说明。

    和 observation._truncate 的头尾各留一半不同：测试输出的开头是 session 头，
    失败详情和统计行都印在最后，留尾部信息密度高得多（T4）。
    """
    if limit < 0:
        raise ValueError("Limit must be non-negative")

    if len(text) <= limit:
        return text

    # limit 为 0 时 text[-0:] 是整串，必须特判（observation._truncate 踩过同一个坑）
    kept = text[-limit:] if limit else ""
    # 丢掉的那半**不物化**：原来是 text[:n] 再 .splitlines()，等于把它整份复制一遍再切成列表。
    # run_python 让模型能 print 出任意大的输出（P1 实测 mini 单条 trajectory 到 204MB），
    # 那一份复制会直接打在宿主机内存上。count 是流式的，不分配（Y6）。
    dropped_chars = len(text) - limit
    dropped_lines = text.count("\n", 0, dropped_chars)
    notice = (
        f"[TRUNCATED: dropped the first {dropped_chars} chars / {dropped_lines} lines "
        "of output; the tail is kept because failures and the summary are printed last]"
    )
    return f"{notice}\n\n{kept}" if kept else notice


def _tail_with_path(result: TailResult) -> str:
    """尾部 + 被截断时「丢了多少、完整的那份在哪」（Y12）。

    和 _keep_tail 的分工：截断已经在**容器里**做完了（execute_to_file 的 tail -c），
    这里只负责把丢掉的量和取回的路径写给模型 —— 截断从此是**可恢复**的，
    不再只是「保护上下文」。路径在 OVERFLOW_DIR，read_file 的窄口子放行。

    单位是**字节**不是字符：截断是 tail -c 做的，这里报 chars 会对不上账。
    丢掉的量按**预算**算（total_bytes - tail_bytes），不按 len(tail.encode()) ——
    理由见 TailResult.truncated，那样算在多字节边界上会得出错的数，超时时甚至是负数
    （Codex 审稿 2026-09-21 MAJOR-2 / MAJOR-3）。
    """
    notices = []

    if result.truncated:
        dropped = result.total_bytes - result.tail_bytes
        notices.append(
            f"[TRUNCATED: dropped the first {dropped} of {result.total_bytes} bytes of output; "
            f"the tail is kept because failures and the summary are printed last. "
            f"The complete output is in the container at {result.path} — "
            f"read_file that path if you need the part that was dropped.]"
        )

    if result.timed_out:
        # 进程还活着，文件还在长 —— 报的数是读那一刻的快照，不许写成终值
        notices.append(
            f"[NOTE: the process was still running when this was read, so "
            f"{result.total_bytes} bytes is a snapshot, not the final size. "
            f"What it has written so far is at {result.path}.]"
        )

    if not notices:
        return result.tail

    head = "\n".join(notices)
    return f"{head}\n\n{result.tail}" if result.tail else head
