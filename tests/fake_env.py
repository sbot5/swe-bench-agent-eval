"""假的执行环境：按脚本回 ExecResult，不起容器。

取舍照 DESIGN-tools.md §七：**工具逻辑用假 env 测**（秒级，能把每条错误路径都触发一遍），
真容器只留一份冒烟（tests/test_container_smoke.py）确认整条链是通的。
理由：错误路径要的是特定的退出码和 stdout，真容器反而难造 —— 让 `cat` 回退出码 94 得先把环境弄坏。
"""
from collections.abc import Callable, Sequence

from agent.environment import DockerEnvironment, ExecResult


def ok(stdout: str = "", stderr: str = "", exit_code: int = 0, duration: float = 0.01) -> ExecResult:
    """造一条正常返回的执行结果。"""
    return ExecResult(stdout=stdout, stderr=stderr, timed_out=False, duration=duration, exit_code=exit_code)


def tail_probe(total_bytes: int, tail: str = "") -> ExecResult:
    """造 execute_to_file 第二条命令（`wc -c` && `tail -c`）的返回：第一行是字节数，其余是尾部。"""
    return ok(stdout=f"{total_bytes}\n{tail}")


def timed_out(duration: float = 60.0) -> ExecResult:
    """造一条超时的执行结果：exit_code 必须是 None，否则 ExecResult 自己会拒绝。"""
    return ExecResult(stdout="", stderr="", timed_out=True, duration=duration, exit_code=None)


class FakeEnvironment:
    """按顺序回预先排好的结果，并把收到的命令记在 self.commands 里。

    结果用完还被调用就抛 AssertionError —— 悄悄多跑一条命令是 bug，不该被默默吞掉。
    """

    def __init__(self, results: Sequence[ExecResult] | Callable[[str], ExecResult]) -> None:
        self._results = results
        self._index = 0
        self.commands: list[str] = []

    def execute(self, cmd: str, timeout: int = 60) -> ExecResult:
        self.commands.append(cmd)
        if callable(self._results):
            return self._results(cmd)
        assert self._index < len(self._results), f"unexpected extra command: {cmd!r}"
        result = self._results[self._index]
        self._index += 1
        return result

    # 走**真**实现，只有 execute 是假的（Y12）：命令怎么拼、`wc -c` 那一行怎么解析、
    # 超时那条路还读不读文件 —— 这些都是要测的逻辑，在假 env 里重写一遍等于不测
    execute_to_file = DockerEnvironment.execute_to_file

    @property
    def exhausted(self) -> bool:
        """脚本里排的结果是不是都用掉了。断言「该跑几条命令就跑几条」。"""
        return callable(self._results) or self._index == len(self._results)
