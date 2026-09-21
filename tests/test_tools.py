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

from agent.environment import OVERFLOW_DIR
from agent.observation import FailureCategory, Observation, ToolStatus
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
    _validate_legal_path,
    apply_patch,
    git_diff,
    list_files,
    read_file,
    run_python,
    run_tests,
    search_code,
)
from tests.fake_env import FakeEnvironment, ok, tail_probe, timed_out

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


def test_keep_tail_counts_the_dropped_half_without_copying_it():
    """丢掉的那半只数换行、不物化（Y6）：run_python 能 print 出任意大的输出，
    原来的 text[:n].splitlines() 会把它整份复制再切成列表，直接打在宿主机内存上。"""
    text = "a\n" * 1000 + "tail"
    out = _keep_tail(text, 4)
    assert out.endswith("tail")
    assert "dropped the first 2000 chars / 1000 lines" in out


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
    assert obs.summary.startswith("1 test(s) not passing out of 2")
    assert "test_a" in obs.content and "- tests/test_x.py::test_b" not in obs.content


def test_run_tests_counts_skipped_and_xfail_as_passing():
    """白名单里的三个状态都算过了：只有 PASSED/SKIPPED/XFAIL 不进「没过」名单（T10）。"""
    env = FakeEnvironment([ok(stdout="...\n", exit_code=0)])
    obs = run_tests(env, "tests/test_x.py",
                    log_parser=lambda _: {"a": "PASSED", "b": "SKIPPED", "c": "XFAIL"})
    assert obs.status == ToolStatus.OK
    assert obs.summary.startswith("All 3 test(s) passed")


def test_run_tests_does_not_trust_a_status_it_does_not_know():
    """黑名单认不出带冒号的 `ERROR:`，白名单必须认出来（T10，S4 astropy-7166）。"""
    env = FakeEnvironment([ok(stdout="ERROR: -o/--override-ini expects option=value style.\n", exit_code=4)])
    obs = run_tests(env, "astropy/utils/tests/test_misc.py::test_inherit_docstrings",
                    log_parser=lambda _: {"-o/--override-ini": "ERROR:"})
    assert "passed" not in obs.summary
    assert obs.summary.startswith("1 test(s) not passing out of 1")
    assert "- -o/--override-ini" in obs.content


def test_run_tests_rejects_a_clean_parse_when_the_command_itself_failed():
    """第二道防线：全是 PASSED 但退出码非零 -> 这一跑不算数，报 error（T11）。"""
    env = FakeEnvironment([ok(stdout="PASSED a\n", exit_code=2)])
    obs = run_tests(env, "tests/test_x.py", log_parser=lambda _: {"a": "PASSED"})
    assert obs.status == ToolStatus.ERROR and obs.failure_category == FailureCategory.UNCLASSIFIED
    assert "exited with code 2" in obs.summary


def test_run_tests_replays_the_s4_astropy_false_pass_through_the_real_parser():
    """S4 的原样回放：真 parser + 容器里实际打出的那一行，端到端不许再报 passed（T10）。

    黑名单版在这里会报 `All 1 test(s) passed (1 error:)` 并且 status=ok —— 就是 09-17 那条假信号。
    日志、退出码 4、parser（astropy 走 parse_log_astropy）都取自 09-17 的容器实测，见 DESIGN-tools.md §五。
    """
    from swebench.harness.log_parsers.python import parse_log_astropy

    log = "ERROR: -o/--override-ini expects option=value style.\n"
    env = FakeEnvironment([ok(stdout=log, exit_code=4)])
    obs = run_tests(env, "astropy/utils/tests/test_misc.py::test_inherit_docstrings",
                    log_parser=lambda text: parse_log_astropy(text, None))
    assert "passed" not in obs.summary, "运行器自己报错退出，不许报成通过"
    assert obs.summary.startswith("1 test(s) not passing out of 1")


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
        (lambda env: run_tests(env, "x", log_parser=lambda _: {"a": "PASSED"}),
         [ok(stdout="PASSED a", exit_code=2)], FailureCategory.UNCLASSIFIED),
        (lambda env: run_python(env, ""), [], FailureCategory.INVALID_ARGUMENT),
        (lambda env: run_python(env, "print(1)", timeout=99999), [], FailureCategory.INVALID_ARGUMENT),
        # 超时后还有第三条命令：容器里的文件照读，能拿回多少算多少（Y12）
        (lambda env: run_python(env, "print(1)"), [ok(), timed_out(), tail_probe(0)], FailureCategory.TIMEOUT),
        (lambda env: run_python(env, "print(1)"), [ok(exit_code=1)], FailureCategory.UNCLASSIFIED),
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


def test_run_python_reports_the_exit_code_it_actually_got():
    out = "value is 3\n"
    env = FakeEnvironment([ok(), ok(exit_code=0), tail_probe(len(out.encode()), out)])
    obs = run_python(env, "print('value is', 3)")
    assert obs.status == ToolStatus.OK
    assert obs.summary.startswith("Script finished with exit code 0")
    assert "value is 3" in obs.content
    assert env.exhausted  # 三条命令：写脚本、跑脚本（输出重定向进容器里的文件）、取字节数和尾部


def test_run_python_is_ok_when_the_script_itself_raises():
    """脚本挂了是工具完成了它的活，不是工具失败（Y4，同 T6）。"""
    out = "Traceback:\nValueError: boom\n"
    env = FakeEnvironment([ok(), ok(exit_code=1), tail_probe(len(out.encode()), out)])
    obs = run_python(env, "raise ValueError('boom')")
    assert obs.status == ToolStatus.OK
    assert obs.summary.startswith("Script exited with code 1")
    assert "finished with exit code 0" not in obs.summary, "非零退出不许说成完成"
    assert "ValueError: boom" in obs.content


def test_run_python_does_not_mistake_the_scripts_own_exit_code_for_a_write_failure():
    """Y5：写和跑分两条命令，所以脚本自己 sys.exit(94) 不会被当成「文件没写进去」。

    单条命令加 `|| exit 94`（apply_patch 的写法）在这里就会误判 —— 那边 94 之后不再跑用户代码。
    """
    env = FakeEnvironment([ok(), ok(exit_code=94), tail_probe(0)])
    obs = run_python(env, "import sys; sys.exit(94)")
    assert obs.status == ToolStatus.OK
    assert obs.summary.startswith("Script exited with code 94")


def test_run_python_stops_before_running_when_the_script_cannot_be_written():
    env = FakeEnvironment([ok(stderr="No space left on device", exit_code=1)])
    obs = run_python(env, "print(1)")
    assert obs.status == ToolStatus.ERROR and obs.failure_category == FailureCategory.UNCLASSIFIED
    assert env.exhausted, "写不进去就不该再跑第二条命令"


def test_run_python_never_puts_the_script_on_the_command_line():
    """code 是模型写的，只能 base64 送进去（Y1，同 P5）。"""
    code = "print('a'); import os; os.system('rm -rf /')"
    env = FakeEnvironment([ok(), ok(), tail_probe(2, "a\n")])
    run_python(env, code)
    assert code not in env.commands[0]
    assert "rm -rf /" not in env.commands[0]
    assert base64.b64encode(code.encode()).decode() in env.commands[0]
    # 第二条命令只提脚本路径，代码一个字都不在里面
    assert code not in env.commands[1]
    assert "/tmp/agent_run_python.py" in env.commands[1]


def test_run_python_writes_outside_the_repo_so_git_diff_stays_clean():
    """脚本和溢写日志都落在 /tmp，不落 /testbed —— 否则 git_diff 会把它们列成未跟踪文件（Y9、Y12）。"""
    env = FakeEnvironment([ok(), ok(), tail_probe(0)])
    run_python(env, "print(1)")
    assert "/tmp/agent_run_python.py" in env.commands[0]
    assert "/testbed" not in env.commands[0]
    # 重定向和取尾部这两条也不许把文件落进仓库，否则 Y9 的理由在 Y12 上重新破一次
    assert "/tmp/agent-overflow/run_python.log" in env.commands[1]
    assert "/testbed" not in env.commands[1]
    assert "/testbed" not in env.commands[2]


def test_run_python_says_so_when_the_script_printed_nothing():
    env = FakeEnvironment([ok(), ok(), tail_probe(0)])
    obs = run_python(env, "pass")
    assert obs.status == ToolStatus.OK
    assert "no output" in obs.content


def test_run_python_truncates_a_huge_output_in_the_container():
    """Y12：截断在**容器里**做 —— 宿主机只拿回尾部，整份输出从来没进过宿主机内存。

    原来（Y6）截断在工具层：execute 的 capture_output 先把 500KB 读进宿主机，_keep_tail 才切。
    现在假 env 回的就是 `tail -c` 已经切好的那一段，整份输出只存在于容器里那个文件。
    """
    kept = "x" * 9_000 + "THE END"
    env = FakeEnvironment([ok(), ok(), tail_probe(500_007, kept)])
    obs = run_python(env, "print('x' * 500_000)")

    assert len(obs.content) < 100_000
    assert "THE END" in obs.content, "留的是尾部，失败和统计都印在最后"
    assert "500007 bytes" in obs.summary, "summary 报的是**完整**输出的大小，不是拿回来那点"
    # 丢掉的那段不是没了：告诉模型它在哪，并给一条可执行的取回路径
    assert "/tmp/agent-overflow/run_python.log" in obs.content
    assert any("read_file" in action for action in obs.next_actions)
    assert obs.content.endswith("THE END")
    assert "TRUNCATED" in obs.content


def test_the_overflow_exception_is_narrow():
    """Y12 给 read_file 开的口子只放行一个目录，且只对带开关的调用方生效。

    这条是安全边界的测试，不是功能测试：溢写日志在 REPO_ROOT 之外（理由见 OVERFLOW_DIR），
    白名单因此必须退让一步 —— 退让多少，由这条钉死。
    """
    log = f"{OVERFLOW_DIR}/run_python.log"

    # read_file 那条路：放行，拿到归一化后的绝对路径
    assert _validate_legal_path(log, "ctx", allow_overflow=True) == log

    # 默认不带开关 —— 其余 5 个工具照旧拒绝，尤其 apply_patch 读得到也改不了那份输出
    denied = _validate_legal_path(log, "ctx")
    assert isinstance(denied, Observation)
    assert denied.failure_category == FailureCategory.PATH_OUTSIDE_ROOT

    # 开关不等于「放行整个 /tmp」：邻居目录、前缀相同的目录、目录本身、穿越，全都不行
    for outside in [
        "/tmp/agent_run_python.py",          # run_python 的脚本，不是它的输出
        "/tmp/passwd",
        f"{OVERFLOW_DIR}-evil/x",            # 前缀相同但不是同一个目录
        OVERFLOW_DIR,                        # 目录本身不是文件
        f"{OVERFLOW_DIR}/../../etc/passwd",  # normpath 之后就不在里面了
    ]:
        result = _validate_legal_path(outside, "ctx", allow_overflow=True)
        assert isinstance(result, Observation), f"should have been denied: {outside}"
        assert result.failure_category == FailureCategory.PATH_OUTSIDE_ROOT, outside
