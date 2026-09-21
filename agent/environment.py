"""每条实例一个 Docker 容器，工具通过 docker exec 在里面执行；Agent 代码本身跑在宿主机。

这一层不做命令 allowlist / 路径白名单，拼进命令的参数由 tools 包 负责 shlex.quote（决定 23）。
容器事实、决定、实测、已纠正的错误：docs/DESIGN-environment.md
残留容器：docker rm -f $(docker ps -aq --filter name=swebench-agent-)
"""
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Final, Self

# 容器内仓库根。execute() 的 -w 和 tools 包 的路径白名单共用，同一事实一个来源
REPO_ROOT: Final = "/testbed"

# 工具的完整输出溢写到这里（决定 32）。**在 REPO_ROOT 之外**，理由同 Y9：放仓库里的话
# git_diff 会把它列成未跟踪文件（git_diff.py:47-54 会列 untracked），污染模型的自查视图。
# 代价是 read_file 的路径白名单要为它开一个窄口子（_common._validate_legal_path 的 allow_overflow）。
OVERFLOW_DIR: Final = "/tmp/agent-overflow"

@dataclass(frozen=True)
class ExecResult:
    """容器内一条命令的执行结果快照。只给 tools 包 看，由它加工成 Observation；模型看不到。

    stdout / stderr 分开存、不截断；duration 单位秒（决定 1–7）。
    超时则 timed_out=True 且 exit_code 为 None，否则 exit_code 必为 int（__post_init__ 强制）。
    """
    stdout: str
    stderr: str
    timed_out: bool
    duration: float
    exit_code: int | None = None
    
    def __post_init__(self):
        if self.timed_out:
            if self.exit_code is not None:
                raise ValueError("Exit code must be None if timed out")
        else:
            if self.exit_code is None:
                raise ValueError("Exit code must be existed as int if time not out")

@dataclass(frozen=True)
class TailResult:
    """完整输出留在容器里、只把尾部带回宿主机的执行结果（决定 32）。

    与 ExecResult 的区别只有一条：tail **不是**完整输出，是 tail_bytes 预算内的尾部。
    total_bytes 是容器里那份的真实大小，path 是它的容器内路径 —— 模型能用 read_file 读回去。
    stderr 没有单独一列：execute_to_file 把两条流并进同一个文件（顺序才是对的，同 T3）。
    """
    tail: str
    total_bytes: int
    path: str
    timed_out: bool
    duration: float
    exit_code: int | None = None

    @property
    def truncated(self) -> bool:
        """尾部没装下全部输出。按**字节**比，因为截断是容器里的 tail -c 做的。"""
        return self.total_bytes > len(self.tail.encode())

class DockerEnvironment:
    """一条实例一个容器的完整生命周期。必须用 with：

        with DockerEnvironment(image_name) as env:
            result = env.execute("git grep -n foo")

    容器在 __enter__ 起、__exit__ 删，__init__ 只赋值；不用 with 直接 execute() 会抛 RuntimeError（决定 8）。
    """
    
    def __init__(self, image_name: str) -> None:
        self.image_name: str = image_name
        self.container_id: str | None = None
        
    def __enter__(self) -> Self:
        self._start_container()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def _start_container(self):
        """起一个后台容器（sleep 2h 保活，到期由 --rm 回收），id 记在 self.container_id。

        docker 拒绝 / 拿到空 id -> RuntimeError；docker 没装、拉镜像超 120 秒 -> 原异常直接抛（决定 9–16、31）。
        """
        # ⚠️ 2h 必须大于单条实例的最坏耗时：loop.py 定 max_steps 时回来核对（DESIGN-environment §七）
        cmd = [
            "docker", "run",
            "--name", 
            f"swebench-agent-{uuid.uuid4().hex[:8]}",
            "-d",
            "--rm",
            # ⚠️ run_python 让模型能执行任意 Python，`import socket` 在语言层拦不住（tools 决定 Y2）。
            # 沙箱边界只能放在容器层：没有网卡，urllib / curl / git clone 一律失败，loopback 仍通，
            # 所以要起本地端口的测试不受影响（P1 断网重跑实测，docs/EVAL-S5-baseline-nonet.md）。
            "--network=none",
            self.image_name,
            "sleep", "2h"
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            # str(e) 只有退出码，真正的原因（如 Unable to find image）只在 e.stderr 里
            err_msg = (e.stderr or "").strip()
            raise RuntimeError(
                f"Failed to start container for image '{self.image_name}' (exit code {e.returncode}): {err_msg}"
            ) from e
            
        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError(f"Failed to obtain container ID for image {self.image_name}")
        self.container_id = container_id

    def cleanup(self) -> None:
        """强制删除容器，最多阻塞 30 秒。幂等：第二次调用直接返回。

        失败只打警告（带恢复命令），绝不抛异常 —— 不能盖住 with 块里正在传播的那个异常（决定 18–21）。
        """
        if self.container_id is None: return
        
        cid = self.container_id
        
        cmd = [
            "docker", "rm",
            "-f",
            self.container_id
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,  # 退出码非 0 绝不主动抛出 CalledProcessError
            )
            
            # 两条路都要查：命令失败只体现在 returncode，进程异常走下面的 except
            if result.returncode != 0:
                err_msg = (result.stderr or "").strip()
                print(
                    f"[WARNING] Failed to remove container {cid} (exit {result.returncode}): {err_msg}\n"
                    f"Action required: docker rm -f {cid}",
                    file=sys.stderr,
                )
        except subprocess.SubprocessError as e:
            # 捕获 TimeoutExpired 等子进程异常，打警告记录，不抛出
            print(
                f"[WARNING] Exception during cleanup for container {cid}: {e}\n"
                f"Action required: docker rm -f {cid}",
                file=sys.stderr,
            )
        finally:
            self.container_id = None  # 无条件复位，保证幂等
    
    def execute(self, cmd: str, timeout: int=60) -> ExecResult:
        """在容器里用 bash -c 跑一条命令，返回 ExecResult。非 0 退出码是正常返回，不是异常。

        工作目录固定为 REPO_ROOT；每次都是新进程，cd 不跨调用持久。容器没起来 -> RuntimeError（决定 22–29）。
        超时只杀宿主机上的 docker exec 客户端，容器里的进程还活着（DESIGN-environment §七）。
        """
        if not self.container_id:
            raise RuntimeError("Cannot execute command: container is not running (did you forget `with`?)")
        
        # 传给 subprocess 的必须是这个列表；传 cmd 字符串会在宿主机上执行（已纠正的错误 12）
        exec_cmd = [
            "docker",
            "exec",
            "-w",
            REPO_ROOT,
            self.container_id,
            "bash",
            "-c",
            cmd,
        ]
        
        t0 = time.monotonic()  # 不用 time.time()：墙上时钟会被 NTP 调整
        try:
            # 容器输出不保证是合法 UTF-8，解码失败不能炸掉整条实例
            result = subprocess.run(
                exec_cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            duration = time.monotonic() - t0
            return ExecResult(
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
                duration=duration,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            # 这里的输出是 bytes 或 None（传了 encoding 也一样），且没有 returncode
            duration = time.monotonic() - t0
            out_str = _safe_decode(e.output)
            err_str = _safe_decode(e.stderr)
            
            return ExecResult(
                stdout=out_str,
                stderr=err_str,
                timed_out=True,
                duration=duration,
                exit_code=None,
            )

    def execute_to_file(self, cmd: str, *, log_name: str, tail_bytes: int,
                        timeout: int = 60) -> TailResult:
        """跑一条命令，**完整输出留在容器内的文件里**，宿主机只取尾部（决定 32）。

        为什么不用 execute()：它是 capture_output=True，整份 stdout 先进宿主机内存
        （P1 实测 mini 单条 trajectory 到 204MB）。这里让容器自己重定向到文件，
        宿主机只 `tail -c` 取预算内的那一段，峰值内存因此有上界 —— 这是真的上界，
        不是「少复制一份」：_keep_tail 截断的时候，那一份早就在内存里了。

        超时也照样去读那个文件：超时只杀宿主机上的 docker exec 客户端，容器里的进程还在写，
        能读回多少算多少（比 TimeoutExpired 那份 partial output 完整，DESIGN-environment §七）。

        log_name 必须是纯标识符。这一层仍然不做 allowlist（决定 23）—— cmd 里的模型参数由
        tools 包 quote 好再传进来；这里 quote 的只有我们自己的常量路径。
        """
        if not log_name or not log_name.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError(f"log_name must be a plain identifier, got: {log_name!r}")

        path = f"{OVERFLOW_DIR}/{log_name}"
        quoted_path = shlex.quote(path)

        # 大括号里要用 `;` 收尾，否则 `{ cmd }` 是语法错；退出码仍是 cmd 自己的
        run_result = self.execute(
            f"mkdir -p {shlex.quote(OVERFLOW_DIR)} && {{ {cmd} ; }} > {quoted_path} 2>&1",
            timeout=timeout,
        )

        # 无论成败都去读：超时那条路正是最需要看输出的时候
        probe = self.execute(f"wc -c < {quoted_path} && tail -c {tail_bytes} {quoted_path}", timeout=60)

        total_bytes, tail = 0, ""
        if not probe.timed_out and probe.exit_code == 0:
            # 第一行是 wc -c 的字节数，其余是尾部本身（尾部可能以空行开头，partition 只吃第一个 \n）
            counted, _, rest = probe.stdout.partition("\n")
            try:
                total_bytes = int(counted.strip())
            except ValueError:
                total_bytes = 0  # 读不出就当没读到，不拿一个编出来的数去算「丢了多少」
            else:
                tail = rest

        return TailResult(
            tail=tail,
            total_bytes=total_bytes,
            path=path,
            timed_out=run_result.timed_out,
            duration=run_result.duration,
            exit_code=run_result.exit_code,
        )

def _safe_decode(raw: str | bytes | None) -> str:
    """把 None / bytes / str 统一成 str：None -> ""，bytes 按 UTF-8 解码、非法字节替换（决定 26）。

    给 TimeoutExpired 的输出用 —— 它即使传了 encoding 也是 bytes，零输出时是 None。
    """
    if raw is None:
        return ""
    elif isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    else:
        return raw