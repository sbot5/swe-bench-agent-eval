"""工具的单测：DESIGN-tools.md §二 四条验收的可执行版。

    .venv/bin/python -m pytest tests/ -v            # 假 env，秒级
    .venv/bin/python -m pytest tests/ -v -m slow    # 加上真容器那一份

分三层（取舍见 DESIGN-tools.md §七）：
  纯函数     本文件上半，不碰 env
  假 env     本文件下半，把每条错误路径都触发一遍
  真容器     tests/test_container_smoke.py，只留冒烟
"""
import base64

import pytest

from agent.observation import FailureCategory, ToolStatus
from agent.tools import (
    _aggregate,
    _closest_lines,
    _count_statuses,
    _find_all,
    _keep_tail,
    _line_number_at,
    _parse_counts,
    _parse_grep_lines,
    _preview,
    _render_hits,
    _render_lines,
    _split_test_targets,
    _squeeze_whitespace,
    apply_patch,
    git_diff,
    list_files,
    read_file,
    run_tests,
    search_code,
)
from tests.fake_env import FakeEnvironment, ok, timed_out

# --------------------------------------------------------------------- 纯函数


def test_find_all_is_non_overlapping():
    assert _find_all(b"abcabc", b"abc") == [0, 3]
    assert _find_all(b"aaaa", b"aa") == [0, 2]  # 重叠的那次不算
    assert _find_all(b"abc", b"zzz") == []
    assert _find_all(b"abc", b"") == []  # 空锚点匹配不到任何位置，而不是到处都是


def test_line_number_at_counts_newlines():
    assert _line_number_at(b"a\nb\nc", 0) == 1
    assert _line_number_at(b"a\nb\nc", 2) == 2
    assert _line_number_at(b"a\nb\nc", 4) == 3


def test_squeeze_whitespace_keeps_line_count():
    text = "  a   b \n\tc  \n\n d "
    assert _squeeze_whitespace(text) == "a b\nc\n\nd"
    assert len(_squeeze_whitespace(text).splitlines()) == len(text.splitlines())


def test_closest_lines_ranks_by_similarity_and_drops_the_unlike():
    content = "def foo(a, b):\n    return a\nclass Unrelated:\n"
    assert _closest_lines(content, "def foo(a, c):") == [(1, "def foo(a, b):")]
    assert _closest_lines(content, "zzzzzzzzzzzzzz") == []
    assert _closest_lines("", "anything") == []


def test_render_lines_clamps_to_the_file():
    text = "l1\nl2\nl3"
    assert _render_lines(text, 2, 2, 1) == "     1\tl1\n     2\tl2\n     3\tl3"
    assert _render_lines(text, 1, 1, 10) == "     1\tl1\n     2\tl2\n     3\tl3"


def test_keep_tail_never_returns_everything_when_limit_is_zero():
    # observation._truncate 踩过的坑：text[-0:] 是整串
    assert "abcdef" not in _keep_tail("abcdef", 0)
    assert _keep_tail("abcdef", 10) == "abcdef"
    assert _keep_tail("abcdef", 3).endswith("def")
    with pytest.raises(ValueError):
        _keep_tail("abc", -1)


def test_preview_shortens_only_long_strings():
    assert _preview("short") == "'short'"
    assert _preview("x" * 100).endswith("(100 chars in total)")
    assert _preview(7) == "7"


def test_split_test_targets_rejects_unbalanced_quotes():
    assert _split_test_targets("a b") == ["a", "b"]
    assert _split_test_targets('"abc') is None
    assert _split_test_targets("") == []


def test_count_statuses_is_sorted():
    assert _count_statuses({"a": "PASSED", "b": "FAILED", "c": "PASSED"}) == {"FAILED": 1, "PASSED": 2}


def test_aggregate_counts_files_under_each_directory():
    files = ["pkg/a.py", "pkg/sub/b.py", "top.py"]
    assert _aggregate(files, ".", 1) == ["pkg/ (2 files)", "top.py"]
    # depth=2 时每一层都留一行：目录行给总数，下一层给具体条目
    assert _aggregate(files, ".", 2) == ["pkg/ (2 files)", "pkg/a.py", "pkg/sub/ (1 files)", "top.py"]


def test_parse_counts_dedupes_the_two_grep_passes():
    stdout = "a.py\x005\nb.py\x002\na.py\x005\n"
    assert _parse_counts(stdout) == [("a.py", 5), ("b.py", 2)]


def test_parse_grep_lines_marks_matches_by_the_column_field():
    stdout = "a.py\x0010\x003\x00hit\na.py\x0011\x00ctx\n--\n"
    assert _parse_grep_lines(stdout) == [("a.py", 10, True, "hit"), ("a.py", 11, False, "ctx"), None]


def test_render_hits_keeps_at_least_one_match():
    records = [("a.py", 1, True, "x" * 40_000)]
    content, shown, cut = _render_hits(records, max_results=5, context=2)
    assert shown == 1 and not cut and "more chars in this line" in content


# ---------------------------------------------------------------- 假 env：正常路径


def test_read_file_reports_the_continuation_offset():
    env = FakeEnvironment([ok(stdout="a\nb\n", stderr="9")])
    obs = read_file(env, "f.py", offset=1, limit=2)
    assert obs.status == ToolStatus.OK
    assert "offset=3" in obs.next_actions[0] and env.exhausted


def test_apply_patch_replaces_and_shows_the_result():
    content = "line1\nold\nline3\n"
    env = FakeEnvironment([ok(stdout=base64.b64encode(content.encode()).decode()), ok()])
    obs = apply_patch(env, "f.py", "old", "new")
    assert obs.status == ToolStatus.OK
    assert "at line 2" in obs.summary and "new" in obs.content
    # 第二条命令只回传新片段，整文件绝不进命令行（决定 P5）
    assert "head -c 6" in env.commands[1] and content not in env.commands[1]


def test_run_tests_reports_only_the_failures():
    log = "FAILED tests/test_x.py::test_a\nPASSED tests/test_x.py::test_b\n"
    env = FakeEnvironment([ok(stdout=log, exit_code=1)])
    obs = run_tests(env, "tests/test_x.py",
                    log_parser=lambda _: {"tests/test_x.py::test_a": "FAILED", "tests/test_x.py::test_b": "PASSED"})
    assert obs.status == ToolStatus.OK  # 测试挂了不是工具失败（observation 决定 1、3）
    assert obs.summary.startswith("1 test(s) failing out of 2")
    assert "test_a" in obs.content and "- tests/test_x.py::test_b" not in obs.content


def test_git_diff_says_so_when_nothing_changed():
    env = FakeEnvironment([ok(stdout=""), ok(stdout="")])
    obs = git_diff(env)
    assert obs.status == ToolStatus.OK and "No changes yet" in obs.summary
    assert env.exhausted  # 没有改动就不该再跑第三条命令去取正文


def test_git_diff_separates_untracked_from_the_stat():
    env = FakeEnvironment([ok(stdout=" f.py | 2 +-\n 1 file changed\n"),
                           ok(stdout="stray.txt\0"), ok(stdout="diff --git ...")])
    obs = git_diff(env)
    assert "1 file changed, 1 untracked file(s)" in obs.summary
    assert "?? stray.txt" in obs.content
    assert any("?? " in action for action in obs.next_actions)


def test_git_diff_does_not_let_a_pipe_swallow_the_exit_code():
    """--stat 失败必须报出来：串成 `a; b` 时 a 的退出码会被 b 顶掉，静默变成「没有改动」（G2）。"""
    env = FakeEnvironment([ok(stderr="not a git repository", exit_code=128)])
    obs = git_diff(env)
    assert obs.status == ToolStatus.ERROR and obs.failure_category == FailureCategory.UNCLASSIFIED
    assert all("|" not in cmd for cmd in env.commands), "git_diff 的命令里不该有管道"


def test_git_diff_survives_an_unreadable_untracked_listing():
    env = FakeEnvironment([ok(stdout=" f.py | 2 +-\n 1 file changed\n"), ok(exit_code=128), ok(stdout="diff --git ...")])
    obs = git_diff(env)
    assert obs.status == ToolStatus.OK and "untracked" not in obs.summary


# ---------------------------------------------------------------- 假 env：错误路径

@pytest.mark.parametrize(
    ("call", "results", "category"),
    [
        (lambda env: read_file(env, "f.py", offset=0), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: read_file(env, "../etc/passwd"), [], FailureCategory.PATH_OUTSIDE_ROOT),
        (lambda env: read_file(env, "f.py"), [ok(exit_code=90)], FailureCategory.PATH_NOT_FOUND),
        (lambda env: read_file(env, "f.py"), [ok(exit_code=91)], FailureCategory.INVALID_ARGUMENT),
        (lambda env: read_file(env, "f.py"), [timed_out()], FailureCategory.TIMEOUT),
        (lambda env: read_file(env, "f.py"), [ok(exit_code=42)], FailureCategory.UNCLASSIFIED),
        (lambda env: list_files(env, "f.py"), [ok(exit_code=92)], FailureCategory.INVALID_ARGUMENT),
        (lambda env: list_files(env, ".", depth=0), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: search_code(env, ""), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: search_code(env, "a", context=99), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: search_code(env, "("), [ok(exit_code=128)], FailureCategory.INVALID_ARGUMENT),
        (lambda env: apply_patch(env, "f.py", "", "x"), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: apply_patch(env, "f.py", "a", "a"), [], FailureCategory.FILE_UNCHANGED),
        (lambda env: apply_patch(env, "f.py", "a", "b"), [ok(exit_code=93)], FailureCategory.INVALID_ARGUMENT),
        (lambda env: apply_patch(env, "f.py", "a", "b"), [ok(stdout="not base64!!")], FailureCategory.UNCLASSIFIED),
        (lambda env: run_tests(env, ""), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: run_tests(env, "x", timeout=99999), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: run_tests(env, "x"), [timed_out()], FailureCategory.TIMEOUT),
        (lambda env: run_tests(env, "x"), [ok(stdout="boom", exit_code=1)], FailureCategory.UNCLASSIFIED),
        (lambda env: git_diff(env, "/etc"), [], FailureCategory.PATH_OUTSIDE_ROOT),
    ],
)
def test_every_error_path_has_a_category_and_a_stop_condition(call, results, category):
    """验收 2：每条错误路径都要有 根因 + 重试指令 + 停止条件。"""
    obs = call(FakeEnvironment(results))
    assert obs.status == ToolStatus.ERROR
    assert obs.failure_category == category
    assert obs.next_actions, "error 必须带 next_actions（Observation.__post_init__ 也会拦）"
    assert obs.summary


def test_apply_patch_tells_the_model_when_only_whitespace_is_wrong():
    content = "def f():\n    return 1\n"
    env = FakeEnvironment([ok(stdout=base64.b64encode(content.encode()).decode())])
    obs = apply_patch(env, "f.py", "def  f():", "def g():")
    assert obs.failure_category == FailureCategory.ANCHOR_NOT_FOUND
    assert "once whitespace is ignored" in obs.content
    assert "     1\tdef f():" in obs.content  # 报的是匹配所在行，不是「最像的行」


def test_apply_patch_lists_every_occurrence_when_ambiguous():
    content = "x = 1\ny = 2\nx = 1\n"
    env = FakeEnvironment([ok(stdout=base64.b64encode(content.encode()).decode())])
    obs = apply_patch(env, "f.py", "x = 1", "x = 9")
    assert obs.failure_category == FailureCategory.ANCHOR_AMBIGUOUS
    assert "appears 2 times" in obs.summary
    assert "     1\tx = 1" in obs.content and "     3\tx = 1" in obs.content


def test_apply_patch_refuses_a_new_string_too_big_to_send():
    obs = apply_patch(FakeEnvironment([]), "f.py", "a", "b" * 200_000)
    assert obs.failure_category == FailureCategory.INVALID_ARGUMENT
    assert "too large" in obs.summary


def test_apply_patch_reports_a_failed_write_as_an_io_error():
    content = "old\n"
    env = FakeEnvironment([ok(stdout=base64.b64encode(content.encode()).decode()), ok(exit_code=94)])
    obs = apply_patch(env, "f.py", "old", "new")
    assert obs.failure_category == FailureCategory.IO_ERROR
    assert "may be truncated" in obs.next_actions[0] or "left unchanged" in obs.next_actions[0]


# ---------------------------------------------------------------- 验收 3、4

def test_large_output_is_truncated_and_says_so():
    """验收 3：超大输入不炸，且截断被明确告知。"""
    huge = "".join(f"line {i}\n" for i in range(50_000))
    env = FakeEnvironment([ok(stdout=huge, stderr="50000")])
    obs = read_file(env, "big.py", offset=1, limit=50_000)
    assert obs.status == ToolStatus.OK
    assert len(obs.content) <= 10_000
    assert "To continue" in obs.next_actions[0]


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "../../etc/passwd", "a/../../../etc/passwd"])
def test_the_path_whitelist_holds_for_every_tool(bad_path):
    """验收 4：安全边界生效 —— 四个带 path 的工具都挡在进容器之前。"""
    for call in (read_file, list_files, apply_patch, git_diff):
        env = FakeEnvironment([])
        obs = call(env, bad_path, "a", "b") if call is apply_patch else call(env, bad_path)
        assert obs.failure_category == FailureCategory.PATH_OUTSIDE_ROOT
        assert not env.commands, f"{call.__name__} 在校验前就进容器了"


def test_model_written_arguments_are_quoted_before_they_reach_the_shell():
    """验收 4：命令注入挡在工具入口 —— 路径和 target 都过 shlex.quote。"""
    env = FakeEnvironment([ok(exit_code=90)])
    read_file(env, "a.py; rm -rf /")
    assert "; rm -rf /" not in env.commands[0].replace("'a.py; rm -rf /'", "")

    # target 先 shlex.split 再逐个 quote：分号被包进单引号，成了 pytest 的一个普通参数
    env = FakeEnvironment([ok(stdout="FAILED t\n", exit_code=1)])
    run_tests(env, "t.py; rm -rf /", log_parser=lambda _: {"t": "FAILED"})
    assert "'t.py;'" in env.commands[0]
    assert "t.py; rm" not in env.commands[0]
