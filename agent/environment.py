"""每条实例一个 Docker 容器，工具通过 docker exec 在里面执行；Agent 代码本身跑在宿主机。

这一层不做命令 allowlist / 路径白名单，拼进命令的参数由 tools.py 负责 shlex.quote（决定 23）。
容器事实、决定、实测、已纠正的错误：docs/DESIGN-environment.md
残留容器：docker rm -f $(docker ps -aq --filter name=swebench-agent-)
"""
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Final, Self

# 容器内仓库根。execute() 的 -w 和 tools.py 的路径白名单共用，同一事实一个来源
REPO_ROOT: Final = "/testbed"

@dataclass(frozen=True)
class ExecResult:
    """容器内一条命令的执行结果快照。只给 tools.py 看，由它加工成 Observation；模型看不到。

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