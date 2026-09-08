"""每条实例一个 Docker 容器，工具通过 docker exec 在里面执行。

为什么 Agent 代码不跑在容器里：容器里的 Python 是 3.6.13（配合被测仓库
的年代），宿主机 venv 是 3.12。mini-SWE-agent 也是这么做的。

容器事实（2026-09-06 实测 sweb.eval.x86_64.django_1776_django-11138，
2026-09-08 于 astropy_1776_astropy-12907 复核）
--------------------------------------------------------------------
  工作目录    /testbed，仓库停在 base_commit，工作区干净
              镜像自带 WORKDIR /testbed，但本模块仍显式传 -w（见 execute）
  没有 rg     用 git grep（只搜跟踪文件，自动跳过 .git 和构建产物）
  有          grep find git sed awk patch python(3.6.13)
              sleep 是 GNU coreutils 8.32，接受 2h 这种后缀
  评分测试    不在容器里 —— test_patch 是评测时才应用的，Agent 看不到。
              这条已实测确认，评测没有被污染
  exec 开销   一次 docker exec 约 32ms（2026-09-08 实测）。
              25 条 × 40 步 ≈ 1000 次 = 32 秒，可以忽略

已定的决定（原「要定的」，2026-09-08 全部收敛）
--------------------------------------------------------------------
容器生命周期
    `docker run -d --rm --name swebench-agent-<uuid8> <image> sleep 2h`，
    生命周期绑在 with 协议上（__enter__ 起、__exit__ 销毁）。
    为什么 sleep 不是 tail -f /dev/null，见 _start_container 的 docstring。
    为什么有 --name，见下面「残留容器怎么清」。

exec 的返回
    ExecResult：stdout / stderr 分开存储 + exit_code + timed_out + duration。
    分开存是不可逆性决定 —— 分开之后工具想合随时能合，合并了就再也分不开。
    合并是 mini 的做法（stderr=subprocess.STDOUT），本项目在这里与它不同。

单条命令超时
    execute(timeout=60)，和 mini 的 swebench.yaml 一致（控制变量：
    这不是本项目的实验变量，不要动）。

安全边界放哪一层
    **这一层不做命令 allowlist，也不做路径白名单。** 三条理由：
      1. 容器本身就是沙箱，里面除了 /testbed 没别的东西，
         最坏情况是弄坏这一条实例，--rm 之后什么都不剩
      2. allowlist 会挡住合法但没想到的命令，在归因表里制造
         一类「被自己的工具挡住」的假失败，污染实验结论
      3. 六个工具是自己拼命令的，模型给的是**参数**不是整条命令
    ⚠️ 转给 tools.py 的义务：每个工具拼参数时用 shlex.quote()。
       这一层用了 bash -c，任何拼进 cmd 的模型输入都会被 shell 解释。
       危害不是安全（沙箱），是**归因污染** —— 模型不小心 rm -rf /testbed，
       实例必然失败，而归因表会写「模型能力不足」而不是「工具没引好参数」。

残留容器怎么清
    docker rm -f $(docker ps -aq --filter name=swebench-agent-)
    这条命令能写出来，就是 --name 前缀存在的全部理由。

镜像名规律：swebench/sweb.eval.x86_64.<repo>_1776_<instance 后半段>
用 docker images | grep sweb 看实际的。

验收（2026-09-08 全过，脚本见 scratchpad/test_execute.py，22/22）
--------------------------------------------------------------------
起容器 -> exec -> 销毁；with 内抛异常时容器仍被清掉；
execute("pwd") 必须返回 /testbed 而不是宿主机路径；
管道 / && 可用；非 0 退出码原样返回；超时返回可读文本且 exit_code=None。
"""
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class ExecResult:
    """容器内单条命令物理执行结果的不可变快照。

    上层（tools.py）消费这些原始事实，并将其加工成给模型看的 Observation。
    模型永远无法直接看到 ExecResult。

    契约约定：
    1. stdout 与 stderr 分离存储，保留全量原始文本，本层不做任何截断。
    2. timed_out=True 时，表示命令触发单步超时被强制终止，此时 exit_code 必须为 None。
    3. timed_out=False 时，表示进程自主退出，此时 exit_code 必为 int（0 表示成功，非 0 表示命令自身报错）。
    4. duration 记录单条命令实际占用的物理秒数（精确到浮点数），供耗时统计与超时阈值调优使用。
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
    """一个实例 = 一个容器的完整生命周期。

    必须用 with 使用：

        with DockerEnvironment(image_name) as env:
            result = env.execute("git grep -n foo")

    不用 with 直接 execute() 会抛 RuntimeError —— 因为容器是在 __enter__
    里起的，__init__ 只赋值不做事。

    决定：容器起在 __enter__，不是 __init__
    ------------------------------------------------------------------
    理由    把「对象构造」和「资源获取」分开。构造不会失败，所以不存在
            半构造状态（属性有一半、容器不知道起没起）。
    对照    mini 在 __init__ 里起容器（docker.py:59），代价是它的 cleanup
            必须写 getattr(self, "container_id", None) 来防住
            「init 中途炸了、属性还没建」（docker.py:155）。
            本类结构上不可能出现那种状态，不需要那个 hack。
    代价    多一层 with，调用方不能拿一个「已经可用」的对象到处传。
            对本项目无所谓 —— 只有 run.py 一个调用点，且它本来就是
            一条实例一个作用域。

    容器 id 的生命周期
    ------------------------------------------------------------------
        __init__   None
        __enter__  拿到 64 位十六进制 id
        cleanup    删完之后无条件复位回 None（finally 里）

    复位是为了让 cleanup 幂等 —— __exit__ 调一次，将来若加 __del__ 再调
    一次，第二次直接从头部返回，不会去删一个已经不存在的 id。
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
        """起一个后台容器，把它的 id 记在 self.container_id 上。

        只被 __enter__ 调用。容器起在 __enter__ 而不是 __init__ 里，是为了让
        「对象构造」和「资源获取」分开 —— 构造不会失败，所以不存在半构造状态。
        （对照 mini：它在 __init__ 里起容器，代价是 cleanup 必须写
        `getattr(self, "container_id", None)` 来防住「init 中途炸了、属性还没建」，
        见 minisweagent/environments/docker.py:155。这里结构上不可能出现那种状态。）

        决定：用 `sleep 2h` 保活，不用 `tail -f /dev/null`
        ------------------------------------------------------------------
        理由    泄漏的代价必须有上界。`--rm` 只在容器内主进程**退出时**才触发
                回收，而 `tail -f /dev/null` 永不退出 —— 只要有一次没走到
                cleanup（进程被 kill -9、断电、异常绕过了 except），那个容器
                就会一直 Up 到 Docker 重启。`sleep 2h` 到期自己退出，`--rm`
                接着回收，泄漏自动止损。
        否决    `tail -f /dev/null`、`sleep infinity` —— 都不会自己结束，
                和上面同一个问题。
        代价    容器有寿命上限。跑超过 2h 的实例会在 Agent 还在干活时容器消失，
                表现为 `docker exec: No such container`。
        实测    2026-09-08 于 astropy-12907 镜像：sleep 是 GNU coreutils 8.32，
                接受 `2h` 后缀；`sleep 4` + `--rm` 到期后容器自动消失；
                同镜像 `tail -f /dev/null` 起的容器 3 秒后仍是 Up。

        ⚠️ 跨文件约束：2h 必须大于单条实例的最坏耗时
        ------------------------------------------------------------------
            max_steps × execute() 的 timeout  +  max_steps × LLM 单步延迟

        按 timeout=60s / max_steps=40 / LLM 8s 估算：40×60 + 40×8 ≈ 45 分钟，
        2h 有 2.6 倍余量。**loop.py 定 max_steps 时回来核对这个不等式。**

        没做成构造参数：目前只有 run.py 一个调用点，没有第二个取值的需求。
        真出现了再提参数。

        失败路径
        ------------------------------------------------------------------
        镜像不存在 / docker 拒绝    -> RuntimeError，信息里带镜像名、退出码和
            docker 自己的 stderr。必须显式拼 e.stderr —— CalledProcessError 的
            str() 只有 "returned non-zero exit status 125"，真正的原因
            （"Unable to find image ... locally"）只在 e.stderr 里。
        docker 本身没装            -> FileNotFoundError 直接抛出，不包装。
            它的默认信息已经说清楚了，而且这属于环境问题，不是实例问题。
        docker 拉镜像太久          -> TimeoutExpired（timeout=120）直接抛出，
            同上，属于环境问题。
        返回了空 id                -> RuntimeError。防的是「退出码 0 但 stdout
            是空」这种静默失败。
        """
        cmd = [
            "docker", "run",
            "--name", 
            f"swebench-agent-{uuid.uuid4().hex[:8]}",
            "-d",
            "--rm",
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
            err_msg = (e.stderr or "").strip()
            raise RuntimeError(
                f"Failed to start container for image '{self.image_name}' (exit code {e.returncode}): {err_msg}"
            ) from e
            
        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError(f"Failed to obtain container ID for image {self.image_name}")
        self.container_id = container_id

    def cleanup(self) -> None:
        """强制删除容器。失败只打警告，绝不抛异常。

        由 __exit__ 调用，也可以手动调。幂等 —— 第二次调用直接返回。

        决定 1：失败时打警告，不抛异常
        ------------------------------------------------------------------
        理由    cleanup 是被 __exit__ 调的。如果 with 块里已经有异常在传播，
                这里再抛新异常，traceback 的**最后一行**（排查的人第一眼看到
                的那行）会变成「删容器失败」，真正的失败原因被挤到上面去。
                跑 25 条时你只会看到一堆清理错误，看不见实例为什么挂。
        原则    清理代码不应该盖过它正在清理的那个失败。
        代价    清理失败不会中断流程，所以必须靠警告让人看见 ——
                警告里带 container_id 和 `Action required: docker rm -f <id>`，
                和给模型写 next_actions 是同一个道理：根因 + 恢复指令。

        决定 2：timeout=30 阻塞等待，不学 mini 的后台化
        ------------------------------------------------------------------
        风险    docker rm -f 在 daemon 无响应 / 磁盘满 / 容器进程处于 D 状态时
                会永远不返回 -> __exit__ 不返回 -> 整个 25 条评测卡死且无输出。
        本方案  subprocess.run(timeout=30)，最坏阻塞 30 秒，但**知道结果**。
        否决    mini 的做法（docker.py:156）：
                    (timeout 60 docker stop <id> || docker rm -f <id>) >/dev/null 2>&1 &
                配 Popen 不等待。永不阻塞，但**永远不知道清理有没有成功**。
        理由    25 条 × 最坏 30 秒 = 12.5 分钟，在四周预算里可以忽略；
                而本项目只有一台机器，泄漏的容器直接吃掉下一条实例的内存，
                「知道有没有泄漏」比「绝不阻塞」更值钱。

        两个坑（都实测过，2026-09-08）
        ------------------------------------------------------------------
        1. docker rm -f 是幂等的 —— 删一个根本不存在的 id 也返回 0。
           所以 returncode != 0 是个**没有假警报**的信号。
        2. check=False 时失败**不抛异常**，只体现在 returncode 上。
           所以两条路都要走：查 returncode（命令失败）+ except（进程异常）。
           只做其中一条就是聋的。

        捕获范围收窄到 SubprocessError（TimeoutExpired 和 CalledProcessError
        的共同父类），不用裸 Exception —— 顺带保证 KeyboardInterrupt /
        SystemExit 能穿过去（它们不是 Exception 的子类）。
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
            self.container_id = None
    
    def execute(self, cmd: str, timeout: int=60) -> ExecResult:
        """在容器里跑一条命令，把跑完之后的全部事实装进 ExecResult。

        六个工具的唯一出口 —— read_file / list_files / search_code /
        apply_patch / run_tests / git_diff 全都落到这里。它错一点，六个一起错。

        非 0 退出码**不是**异常，是正常返回值（check=False）：命令失败是模型
        要看的信息，不是本层要处理的错误。本层只有两种结局 —— 跑完了
        (timed_out=False) 和被超时打断了 (timed_out=True)。

        决定 1：命令交给 bash -c，整条 cmd 作为一个参数
        ------------------------------------------------------------------
        理由    六个工具需要 shell 特性：run_tests 要 `cd ... && pytest`，
                list_files 要 `find ... | head -n 200`。
        否决    shlex.split(cmd) 直接当 argv —— 管道和 && 会被当成普通参数。
        实测    2026-09-08：`ls /testbed | head -3`、`echo A && echo B`、
                `cd /testbed && git rev-parse --short HEAD` 三条都正常。
        ⚠️ 代价 任何拼进 cmd 的模型输入都会被 shell 解释。见模块 docstring
                「安全边界放哪一层」—— 引用参数的义务转给了 tools.py。

        ⚠️ 曾经写错，值得记住：subprocess.run 收到的必须是 **exec_cmd 那个
        列表**，不是 cmd 字符串。传字符串且 shell=False 时，字符串会被当成
        **可执行文件路径**：单个词的命令（如 "pwd"）恰好能在宿主机 PATH 上
        找到，于是退出码 0、有输出、看起来完全正常，但**跑在宿主机上，容器
        从头到尾没参与**。ruff 只会报一条 F841（exec_cmd 赋了值没用）。
        → F841 几乎从不是清理建议：变量没人用，说明你用了别的东西。

        决定 2：显式传 -w /testbed
        ------------------------------------------------------------------
        理由 1  镜像自带 WORKDIR /testbed，但只在 2 个镜像上验过，
                SWE-bench 有 500 个。依赖镜像默认值是隐式契约。
        理由 2  每次 docker exec 都是**全新进程**，cd 不跨命令持久。
                实测：上一条 `cd /tmp`，下一条 `pwd` 仍是 /testbed。
        ⚠️ 转给 tools.py / system prompt 的义务：必须告诉模型 cd 不持久，
           否则它会写 `cd tests` 然后以为下一条命令在 tests/ 里。

        决定 3：encoding="utf-8" + errors="replace"
        ------------------------------------------------------------------
        理由    容器里的输出不保证是合法 UTF-8（grep 命中二进制文件、.pyc、
                latin-1 的测试固件）。不加 errors 会 UnicodeDecodeError，
                一次解码失败炸掉整条实例，而它和要研究的东西毫无关系。
        实测    printf '\\xff\\xfe\\x00hello' 不加 errors -> UnicodeDecodeError；
                加了 -> '\\ufffd\\ufffd\\x00hello'。
        同 mini docker.py:120-121。

        决定 4：超时分支必须自己 decode
        ------------------------------------------------------------------
        实测 TimeoutExpired 的属性（**即使传了 encoding/text**）：
            e.output / e.stdout : bytes（两者是同一个对象）
            e.stderr            : bytes
            returncode          : 不存在
        所以 exit_code 只能是 None —— 这正是 ExecResult 契约第 2 条的由来。
        零输出时属性是 None 而不是 b""，所以 _safe_decode 要处理三种形态。

        决定 5：计时用 time.monotonic()
        ------------------------------------------------------------------
        time.time() 是墙上时钟，会被 NTP 校时调整，极端情况下 duration 算出
        负数。测时间间隔一律 monotonic。
        实测：一次 docker exec 的固定开销约 32ms。

        决定 6：容器没起来时抛 RuntimeError，不用 assert
        ------------------------------------------------------------------
        否决 mini 的 `assert self.container_id`（docker.py:105）——
        python -O 会把 assert 整个编译掉，防线消失。
        assert 是给「不可能发生的内部不变量」用的；「忘了用 with」是调用方
        会犯的错，该是明确的异常。和 ExecResult.__post_init__ 用 ValueError
        是同一个判断。

        已知边界：超时后容器里的进程还活着
        ------------------------------------------------------------------
        subprocess.run(timeout=) 杀掉的是**宿主机上的 docker exec 客户端**，
        容器里那个进程够不着。实测：超时后 `sleep 987654` 仍在容器里跑。
        不处理，理由：容器生命周期本身就是止损（sleep 2h 到期 + cleanup 的
        rm -f，僵尸进程跟着容器一起消失），且一个容器只服务一条实例。
        mini 也没处理（它的 LocalEnvironment 用 os.killpg，Docker 版没有）。
        ⚠️ 若 S4 发现某些实例莫名越跑越慢，回来看这一条。
        """
        if not self.container_id:
            raise RuntimeError("Cannot execute command: container is not running (did you forget `with`?)")
        
        exec_cmd = [
            "docker",
            "exec",
            "-w",
            "/testbed",
            self.container_id,
            "bash",
            "-c",
            cmd,
        ]
        
        t0 = time.monotonic()
        try:
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
    """把 subprocess 异常上那些形态不定的输出统一成 str。

    存在的唯一理由：subprocess.TimeoutExpired 的 output / stdout / stderr
    **即使给 subprocess.run 传了 encoding 或 text=True，也仍然是 bytes**，
    命令一个字都没输出时还会是 None（不是 b""）。三种形态各对应一个分支：

        None   -> ""              超时前没有任何输出
        bytes  -> decode          TimeoutExpired 的正常形态
        str    -> 原样            CompletedProcess 的正常形态（本函数目前
                                  不走这条，留着是为了以后能直接复用）

    实测（2026-09-08，容器内 `echo 出来一半; sleep 30` 配 timeout=2）：
        type(e.output) : bytes -> b'\\xe5\\x87\\xba\\xe6\\x9d\\xa5\\xe4\\xb8\\x80\\xe5\\x8d\\x8a\\n'

    不 decode 直接拼进 f-string，模型看到的就是 b'\\xe5\\x87...' 这种十六进制
    —— 一次超时的观察，正是模型最需要读懂的时候。

    errors="replace" 的理由同 execute 决定 3：非 UTF-8 输出不能炸掉整条实例。

    做成模块级独立函数而不是 execute 里的内联逻辑：它可以单独测，
    且 execute 保持一个职责。同 observation.py 的 _truncate。
    """
    if raw is None:
        return ""
    elif isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    else:
        return raw