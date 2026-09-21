"""执行层的行为验收，可执行版。

`DESIGN-environment.md` §六末记着：09-08 那份 22 项验收是会话临时脚本，**已经不存在了**。
这份是按该文档的契约重写的，覆盖的边界不完全一样 —— 重写的代价要说出来。

分两层：不起容器的（不变量、解码、忘了 with）秒级；真容器的打 `slow` marker。
"""
import subprocess

import pytest

from agent.environment import OVERFLOW_DIR, REPO_ROOT, DockerEnvironment, ExecResult, _safe_decode
from tests.fake_env import FakeEnvironment, ok, tail_probe, timed_out

IMAGE = "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"


# ------------------------------------------------------------------ 不变量

def test_exec_result_refuses_a_timeout_that_also_has_an_exit_code():
    with pytest.raises(ValueError):
        ExecResult(stdout="", stderr="", timed_out=True, duration=1.0, exit_code=0)


def test_exec_result_refuses_a_normal_return_without_an_exit_code():
    with pytest.raises(ValueError):
        ExecResult(stdout="", stderr="", timed_out=False, duration=1.0, exit_code=None)


def test_safe_decode_handles_none_bytes_and_str():
    assert _safe_decode(None) == ""
    assert _safe_decode(b"ok") == "ok"
    assert _safe_decode("ok") == "ok"
    assert _safe_decode(b"\xff\xfe") == "��"  # 非法字节替换，不抛


# ------------------------------------------------------------------ 生命周期

def test_execute_without_with_is_a_programming_error_not_a_silent_no_op():
    env = DockerEnvironment(IMAGE)
    with pytest.raises(RuntimeError, match="did you forget"):
        env.execute("echo hi")


def test_cleanup_is_idempotent_and_never_raises():
    env = DockerEnvironment(IMAGE)
    env.cleanup()  # 没起过容器
    env.cleanup()  # 第二次
    env.container_id = "definitely-not-a-container-id"
    env.cleanup()  # docker 会拒绝，但只该打警告
    assert env.container_id is None


def test_a_missing_image_fails_with_the_reason_not_just_the_exit_code():
    with pytest.raises(RuntimeError) as excinfo:
        with DockerEnvironment("swebench/definitely-not-a-real-image:nope"):
            pass
    # str(CalledProcessError) 只有退出码，真正的原因在 stderr 里
    assert "Failed to start container" in str(excinfo.value)
    assert str(excinfo.value).strip() != "Failed to start container"


# ------------------------------------------------------------------ 真容器

# ------------------------------------------------------- execute_to_file（决定 32）

def test_execute_to_file_keeps_the_whole_output_in_the_container():
    """宿主机只拿回尾部：命令自己重定向进文件，第二条才把字节数和尾部取回来。"""
    env = FakeEnvironment([ok(), tail_probe(500_000, "the tail")])
    result = DockerEnvironment.execute_to_file(env, "python x.py", log_name="run_python.log",
                                               tail_bytes=100)

    assert result.tail == "the tail"
    assert result.total_bytes == 500_000
    assert result.truncated, "500KB 装不进 100 字节的预算"
    assert result.path == f"{OVERFLOW_DIR}/run_python.log"
    # 第一条命令负责重定向，输出一个字都不回宿主机
    assert env.commands[0].endswith(f"> {result.path} 2>&1")
    assert "tail -c 100" in env.commands[1]


def test_execute_to_file_still_reads_the_log_after_a_timeout():
    """超时那条路正是最需要看输出的时候：容器里的进程还在写，能读回多少算多少。"""
    env = FakeEnvironment([timed_out(), tail_probe(9, "partial\n")])
    result = DockerEnvironment.execute_to_file(env, "sleep 999", log_name="run_python.log",
                                               tail_bytes=100)

    assert result.timed_out and result.exit_code is None
    assert "partial" in result.tail, "超时不该把已经产生的输出一起丢掉"


def test_execute_to_file_does_not_invent_a_size_it_could_not_read():
    """`wc -c` 那一行读不出来时 total_bytes 记 0，不拿一个编出来的数去算「丢了多少」（同 C20）。"""
    env = FakeEnvironment([ok(), ok(stdout="not-a-number\nwhatever")])
    result = DockerEnvironment.execute_to_file(env, "true", log_name="x.log", tail_bytes=100)

    assert result.total_bytes == 0
    assert result.tail == "", "读不出字节数就连尾部也不敢当真"
    assert not result.truncated


def test_execute_to_file_rejects_a_log_name_that_is_not_an_identifier():
    """log_name 由我们自己传，不是模型参数 —— 但它会拼进命令，所以在这里挡住（决定 23 的边界）。"""
    env = FakeEnvironment([])
    for bad in ["../escape", "a b", "x;rm -rf /", ""]:
        with pytest.raises(ValueError):
            DockerEnvironment.execute_to_file(env, "true", log_name=bad, tail_bytes=100)


pytest_slow = pytest.mark.slow


@pytest.fixture(scope="module")
def env():
    with DockerEnvironment(IMAGE) as environment:
        yield environment


@pytest_slow
def test_the_working_directory_is_the_repo_root(env):
    assert env.execute("pwd").stdout.strip() == REPO_ROOT


@pytest_slow
def test_cd_does_not_persist_across_calls(env):
    """每次都是新进程。工具靠这条才能永远用相对仓库根的路径。"""
    env.execute("cd /tmp")
    assert env.execute("pwd").stdout.strip() == REPO_ROOT


@pytest_slow
def test_a_non_zero_exit_code_is_a_normal_return_not_an_exception(env):
    result = env.execute("exit 42")
    assert result.exit_code == 42 and not result.timed_out


@pytest_slow
def test_stdout_and_stderr_are_kept_apart(env):
    result = env.execute("echo out; echo err >&2")
    assert result.stdout.strip() == "out" and result.stderr.strip() == "err"


@pytest_slow
def test_a_timeout_reports_no_exit_code(env):
    result = env.execute("sleep 5", timeout=1)
    assert result.timed_out and result.exit_code is None and result.duration >= 1


@pytest_slow
def test_invalid_utf8_output_does_not_crash_the_instance(env):
    result = env.execute("printf '\\xff\\xfe'")
    assert result.exit_code == 0 and "�" in result.stdout


@pytest_slow
def test_the_command_runs_in_the_container_not_on_the_host(env):
    """已纠正的错误 12：传 cmd 字符串而不是 argv 列表，会在宿主机上执行。"""
    assert "testbed" in env.execute("ls /").stdout
    assert env.execute("test -f /testbed/setup.py").exit_code == 0


@pytest_slow
def test_the_container_is_gone_after_the_with_block():
    with DockerEnvironment(IMAGE) as environment:
        container_id = environment.container_id
        assert container_id
    remaining = subprocess.run(["docker", "ps", "-aq", "--filter", f"id={container_id}"],
                               capture_output=True, text=True, timeout=30)
    assert remaining.stdout.strip() == "", "容器没被回收，跑一整批会把磁盘吃光"
