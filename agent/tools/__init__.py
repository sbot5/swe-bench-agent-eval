"""七个工具。全部通过 environment 执行，全部返回统一的 Observation。

写的顺序：read_file -> list_files -> search_code -> apply_patch -> run_tests -> git_diff -> run_python
规格、验收、决定、实测：docs/DESIGN-tools.md

**已纠正的错误**：原 `tools.py` 开头一直写「六个工具」，run_python 在 09-18 加入后没更新这一行，
到 09-19 拆包时才发现。不静默改，记在这里。

一个工具一个模块，各自带只服务自己的 helper；跨工具的常量与 helper 在 `_common.py`。
本文件只做重导出，**不放逻辑**。

重导出里带下划线开头的私有 helper，是有意的：`tests/test_tools.py` 按 `from agent.tools import _keep_tail`
这样的写法直接测这 13 个纯函数（分层取舍见 DESIGN-tools.md §七）。拆包时让测试文件一个字节都不用改，
「拆分没有改变任何行为」才有最强的证据；否则测试和被测代码一起变，验证就说不清了。
"""
from agent.tools._common import (
    CONDA_ACTIVATE,
    DEFAULT_CONTEXT,
    DEFAULT_DEPTH,
    DEFAULT_EDIT_CONTEXT,
    DEFAULT_LIMIT,
    DEFAULT_MAX_RESULTS,
    DEFAULT_OFFSET,
    DEFAULT_SCRIPT_TIMEOUT,
    DEFAULT_TEST_COMMAND,
    DEFAULT_TEST_TIMEOUT,
    MAX_CODE_B64,
    MAX_CONTEXT,
    MAX_EDIT_FILE_BYTES,
    MAX_LINE_CHARS,
    MAX_NEW_STRING_B64,
    MAX_SCRIPT_OUTPUT_CHARS,
    MAX_SCRIPT_TIMEOUT,
    MAX_TEST_TIMEOUT,
    SCRIPT_PATH,
    _keep_tail,
    _preview,
    _validate_legal_path,
    _validate_positive_int,
)
from agent.tools.apply_patch import (
    _closest_lines,
    _find_all,
    _line_number_at,
    _render_lines,
    _squeeze_whitespace,
    apply_patch,
)
from agent.tools.git_diff import git_diff
from agent.tools.list_files import _aggregate, list_files
from agent.tools.read_file import read_file
from agent.tools.run_python import run_python
from agent.tools.run_tests import _count_statuses, _split_test_targets, run_tests
from agent.tools.search_code import (
    _parse_counts,
    _parse_grep_lines,
    _render_hits,
    search_code,
)

__all__ = [
    # 常量
    "CONDA_ACTIVATE",
    "DEFAULT_CONTEXT",
    "DEFAULT_DEPTH",
    "DEFAULT_EDIT_CONTEXT",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_OFFSET",
    "DEFAULT_SCRIPT_TIMEOUT",
    "DEFAULT_TEST_COMMAND",
    "DEFAULT_TEST_TIMEOUT",
    "MAX_CODE_B64",
    "MAX_CONTEXT",
    "MAX_EDIT_FILE_BYTES",
    "MAX_LINE_CHARS",
    "MAX_NEW_STRING_B64",
    "MAX_SCRIPT_OUTPUT_CHARS",
    "MAX_SCRIPT_TIMEOUT",
    "MAX_TEST_TIMEOUT",
    "SCRIPT_PATH",
    # 私有 helper：tests/test_tools.py 直接测它们，见上方 docstring
    "_aggregate",
    "_closest_lines",
    "_count_statuses",
    "_find_all",
    "_keep_tail",
    "_line_number_at",
    "_parse_counts",
    "_parse_grep_lines",
    "_preview",
    "_render_hits",
    "_render_lines",
    "_split_test_targets",
    "_squeeze_whitespace",
    "_validate_legal_path",
    "_validate_positive_int",
    # 七个工具
    "apply_patch",
    "git_diff",
    "list_files",
    "read_file",
    "run_python",
    "run_tests",
    "search_code",
]
