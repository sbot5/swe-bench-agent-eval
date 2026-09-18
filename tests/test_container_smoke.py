"""真容器冒烟：七个工具在一条真实例上各跑一次，确认整条链是通的。

    .venv/bin/python -m pytest tests/test_container_smoke.py -v -m slow

假 env 的单测覆盖的是工具**逻辑**；这里覆盖的是假 env 假不出来的东西 ——
`git grep` 的真输出格式、`head -c`/`tail -c` 切片有没有改坏文件、conda 环境里测试跑不跑得起来。
一条实例够了：这是冒烟，不是回归（取舍见 DESIGN-tools.md §七）。
"""
import textwrap

import pytest

from agent.environment import DockerEnvironment
from agent.observation import FailureCategory, ToolStatus
from agent.tools import apply_patch, git_diff, list_files, read_file, run_python, run_tests, search_code

IMAGE = "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def env():
    with DockerEnvironment(IMAGE) as environment:
        yield environment


def test_read_file_reads_real_lines(env):
    obs = read_file(env, "astropy/table/operations.py", offset=1, limit=5)
    assert obs.status == ToolStatus.OK
    assert obs.content.startswith("     1\t")


def test_list_files_sees_the_repo(env):
    obs = list_files(env, ".", depth=1)
    assert obs.status == ToolStatus.OK and "astropy/" in obs.content


def test_search_code_finds_a_definition(env):
    obs = search_code(env, r"def _join\(", path="astropy/table")
    assert obs.status == ToolStatus.OK and "operations.py" in obs.content


def test_search_code_reports_no_match_as_ok(env):
    obs = search_code(env, "zzz_not_in_this_repo_zzz")
    assert obs.status == ToolStatus.OK and "No matches" in obs.summary


def test_apply_patch_edits_the_file_and_keeps_its_mode(env):
    before = env.execute("stat -c %a astropy/table/operations.py").stdout.strip()

    obs = apply_patch(env, "astropy/table/operations.py", "def _join(", "def _join_smoke(")
    assert obs.status == ToolStatus.OK

    after = env.execute("stat -c %a astropy/table/operations.py").stdout.strip()
    assert after == before, "cat 回原文件是为了保住权限位，别退回 mv"

    diff = git_diff(env)
    assert "def _join_smoke(" in diff.content and "1 file changed" in diff.summary

    # 改回去，后面的测试才跑得动；顺带验证一次「反向编辑」
    assert apply_patch(env, "astropy/table/operations.py", "def _join_smoke(", "def _join(").status == ToolStatus.OK
    assert "No changes yet" in git_diff(env).summary


def test_apply_patch_refuses_an_ambiguous_anchor_without_touching_the_file(env):
    obs = apply_patch(env, "astropy/table/operations.py", "    return", "XXX")
    assert obs.failure_category == FailureCategory.ANCHOR_AMBIGUOUS
    assert "No changes yet" in git_diff(env).summary


def test_the_path_whitelist_holds_against_a_real_container(env):
    for call in (read_file, list_files, git_diff):
        assert call(env, "../../etc/passwd").failure_category == FailureCategory.PATH_OUTSIDE_ROOT
    assert env.execute("test -f /etc/passwd").exit_code == 0, "文件确实存在，挡住它的是工具不是环境"


def test_run_tests_runs_a_real_suite(env):
    from swebench.harness.log_parsers import PARSER_REGISTRY
    from swebench.harness.utils import make_test_spec

    from agent.run import load_instances, REPO_ROOT_DIR

    instance = next(row for row in load_instances(REPO_ROOT_DIR / "subset_ids.txt", None)
                    if row["repo"] == "astropy/astropy")
    spec = make_test_spec(instance)
    parser = PARSER_REGISTRY[spec.log_parser]

    obs = run_tests(env, "astropy/utils/tests/test_misc.py", test_command="python -m pytest -rA",
                    timeout=300, log_parser=lambda log: parser(log, spec))
    assert obs.status == ToolStatus.OK
    assert "passed" in obs.summary


def test_run_python_runs_a_real_script_and_can_import_the_repository(env):
    obs = run_python(env, "import astropy; print('VERSION', astropy.__version__)")
    assert obs.status == ToolStatus.OK
    assert obs.summary.startswith("Script finished with exit code 0")
    assert "VERSION" in obs.content


def test_run_python_gives_back_a_traceback_with_the_line_number(env):
    """写成文件而不是 python -c 的理由（Y1）：traceback 要指到模型自己写的那一行。"""
    obs = run_python(env, "x = 1\ny = 2\nraise ValueError('boom')\n")
    assert obs.status == ToolStatus.OK  # 脚本挂了仍是工具完成了它的活
    assert obs.summary.startswith("Script exited with code 1")
    assert "line 3" in obs.content and "ValueError: boom" in obs.content


def test_the_container_really_has_no_network(env):
    """Y2 的验收。断网必须是真的 —— run_python 一旦有网，就是 P1 抓到的那条
    「下载上游 PR 的 .patch 再 git apply」的路（docs/EVAL-S5-baseline-nonet.md）。"""
    obs = run_python(env, textwrap.dedent("""
        import socket
        try:
            socket.create_connection(("github.com", 443), timeout=5)
            print("REACHED THE NETWORK")
        except OSError as exc:
            print("BLOCKED", type(exc).__name__)
    """), timeout=30)
    assert "REACHED THE NETWORK" not in obs.content
    assert "BLOCKED" in obs.content


def test_cutting_the_network_leaves_loopback_alone(env):
    """断网不能误伤要起本地端口的测试。P1 在 mini 那边实测过，这里在我方容器上再验一次。"""
    obs = run_python(env, textwrap.dedent("""
        import socket
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        socket.create_connection(("127.0.0.1", server.getsockname()[1]), timeout=5)
        print("LOOPBACK OK")
    """), timeout=30)
    assert "LOOPBACK OK" in obs.content


def test_the_script_does_not_show_up_as_a_repository_change(env):
    """Y9：脚本落 /tmp，git_diff 看不见它。"""
    run_python(env, "open('/tmp/marker.txt', 'w').write('x')")
    obs = git_diff(env)
    assert "agent_run_python" not in obs.content
