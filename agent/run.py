"""入口：读实例列表 -> 每条起一个容器跑 ReAct 循环 -> 产出 preds.json、trajectory 和 summary.json。

    PYTHONPATH=. .venv/bin/python -m agent.run --run-id s3-smoke --instances subset_ids.txt --limit 2

跑完评测（结果按 run_id + instance_id 缓存，改了 patch 想重评必须换 run_id）：

    .venv/bin/swebench eval verified -p results/inference/<run-id>/preds.json --run-id <id> -j 6

决定、实测、已纠正的错误：docs/DESIGN-run.md
"""
import argparse
import json
import re
import shlex
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, Final

from agent.environment import DockerEnvironment
from agent.loop import (
    SYSTEM_PROMPT,
    EpisodeResult,
    LoopConfig,
    ModelClient,
    StopReason,
    ToolPolicy,
    build_tool_schemas,
    run_episode,
)
from agent.tools import apply_patch, git_diff, list_files, read_file, run_python, run_tests, search_code

DATASET: Final[str] = "SWE-bench/SWE-bench_Verified"
START_TEST_OUTPUT: Final[str] = ">>>>> Start Test Output"
END_TEST_OUTPUT: Final[str] = ">>>>> End Test Output"
REPO_ROOT_DIR: Final[Path] = Path(__file__).resolve().parent.parent

_TARGET_HINTS: Final[list[tuple[str, str]]] = [
    ("runtests.py", "Name a dotted test module under tests/, e.g. 'forms_tests.field_tests.test_jsonfield' "
                    "(a dotted module path, not a file path)."),
    ("bin/test", "Name a test file, e.g. 'sympy/core/tests/test_match.py'."),
    ("tox", "Name a test file, e.g. 'tests/test_domain_py.py'."),
]
_DEFAULT_HINT: Final[str] = ("Name a test file or a single test, "
                             "e.g. 'path/to/tests/test_module.py' or 'path/to/tests/test_module.py::test_name'.")


def graded_test_files(test_patch: str) -> set[str]:
    """test_patch 里出现的测试文件路径，a/ 和 b/ 两侧都要取。

    只看 a/ 会漏掉被测试补丁改名出来的文件（astropy__astropy-7336 实测），那条的评分目标就会留在前缀里。
    """
    return {path for pair in re.findall(r"^diff --git a/(\S+) b/(\S+)", test_patch, re.M) for path in pair}


def target_forms(paths: Iterable[str]) -> set[str]:
    """一个测试文件路径在各仓库命令行里的几种写法：原路径、去后缀、点号形式、去掉 tests/ 前缀的点号形式。"""
    forms: set[str] = set()
    for path in paths:
        stem = path.removesuffix(".py")
        forms |= {path, stem, stem.replace("/", "."),
                  stem.removeprefix("tests/"), stem.removeprefix("tests/").replace("/", ".")}
    return forms


def derive_test_command(instance: dict) -> tuple[str, str]:
    """从实例自带的 eval_script 里抽出测试运行器前缀，返回 (命令前缀, 目标写法提示)。

    **把评分目标去掉**：留着等于告诉自己的 Agent grader 用哪些测试文件，而 mini baseline 没有这个信息，
    两边数字就不可比了（决定 R2）。`--tb=no` 也去掉 —— grader 不用看堆栈，Agent 要看（决定 R3）。
    """
    script = instance["eval_script"]
    if START_TEST_OUTPUT not in script or END_TEST_OUTPUT not in script:
        raise ValueError(f"{instance['instance_id']}: eval_script has no test output markers")

    body = script.split(START_TEST_OUTPUT, 1)[1].split(END_TEST_OUTPUT, 1)[0]
    # 两个标记各自在 `: '...'` 里，切完会剩下收尾的引号和下一行的 `: '`，都不是命令
    lines = [line.strip() for line in body.splitlines()
             if line.strip() and line.strip() != "'" and not line.strip().startswith(":")]
    if len(lines) != 1:
        raise ValueError(f"{instance['instance_id']}: expected one test command, got {lines}")

    tokens = shlex.split(lines[0])
    forms = target_forms(graded_test_files(instance["test_patch"]))

    cut = len(tokens)
    while cut > 0 and (tokens[cut - 1] in forms or tokens[cut - 1].split("::")[0] in forms):
        cut -= 1
    if cut == len(tokens):
        raise ValueError(f"{instance['instance_id']}: no graded target found at the end of {tokens}")

    prefix = " ".join(shlex.quote(token) for token in tokens[:cut] if token != "--tb=no")
    hint = next((hint for marker, hint in _TARGET_HINTS if marker in prefix), _DEFAULT_HINT)
    return prefix, hint


def build_log_parser(instance: dict) -> Callable[[str], dict[str, str]]:
    """把 harness 自己的 log_parser 包成单参数可调用对象。

    不自己写测试输出解析：和评测同一份代码，run_tests 报的通过/失败与 grader 的口径不会有第二种说法（决定 R4）。
    """
    from swebench.harness.log_parsers import PARSER_REGISTRY
    from swebench.harness.utils import make_test_spec

    spec = make_test_spec(instance)
    parser = PARSER_REGISTRY[spec.log_parser]
    return lambda log: parser(log, spec)


def build_tools(env: DockerEnvironment, instance: dict) -> tuple[dict[str, Callable], str]:
    """把七个工具绑到这条实例的容器和测试运行器上，返回 (工具表, 目标写法提示)。

    run_python 不按实例绑任何东西：它跑的是模型自己写的脚本，没有可泄露的实例信息（同 T8 的口径）。
    """
    test_command, hint = derive_test_command(instance)
    tools = {
        "list_files": partial(list_files, env),
        "search_code": partial(search_code, env),
        "read_file": partial(read_file, env),
        "apply_patch": partial(apply_patch, env),
        "git_diff": partial(git_diff, env),
        "run_tests": partial(run_tests, env, test_command=test_command,
                             log_parser=build_log_parser(instance), target_hint=hint),
        "run_python": partial(run_python, env),
    }
    return tools, hint


def extract_patch(env: DockerEnvironment) -> str:
    """把容器里的改动取成 unified diff，作为这条实例的答案。

    只取已跟踪文件的改动，不 `git add -A`：apply_patch 造不出新文件，而 add -A 会把构建产物一起卷进来（决定 R5）。
    这一步在循环外做，不占 Agent 步数 —— git_diff 工具是给模型自查的，两个角色不混（决定 G1）。
    """
    result = env.execute("git --no-pager --literal-pathspecs diff", timeout=120)
    if result.timed_out or result.exit_code != 0:
        return ""
    return result.stdout


def run_instance(
    instance: dict,
    *,
    client_factory: Callable[[], ModelClient],
    config: LoopConfig,
    out_dir: Path,
    system_prompt: str = SYSTEM_PROMPT,
    tool_policy: ToolPolicy | None = None,
    stage_notes: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """跑一条实例：起容器 -> 循环 -> 取 patch -> 落盘 trajectory。返回 summary 的一行。

    任何异常都收敛成一行 summary，绝不往上抛 —— 单条失败不能停整批（run.py 原规格）。
    """
    instance_id = instance["instance_id"]
    started = time.time()
    result = EpisodeResult(instance_id=instance_id, stop_reason=StopReason.API_ERROR)
    patch = ""
    messages: list[dict] = []

    try:
        with DockerEnvironment(instance["image"]) as env:
            tools, hint = build_tools(env, instance)
            result, messages = run_episode(
                instance_id=instance_id,
                problem_statement=instance["problem_statement"],
                tools=tools,
                client=client_factory(),
                tool_schemas=build_tool_schemas(hint),
                config=config,
                system_prompt=system_prompt,
                tool_policy=tool_policy,
                stage_notes=stage_notes,
            )
            patch = extract_patch(env)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        print(f"[ERROR] {instance_id}: {result.error}", file=sys.stderr)

    trajectory = {
        "instance_id": instance_id,
        "stop_reason": str(result.stop_reason),
        "finish_reason": result.finish_reason,
        "error": result.error,
        "total_cost": result.total_cost,
        "total_duration": result.total_duration,
        "api_calls": result.api_calls,
        "model_patch": patch,
        "steps": [asdict(step) for step in result.steps],
        "messages": messages,
    }
    (out_dir / f"{instance_id}.traj.json").write_text(
        json.dumps(trajectory, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    returned = sorted({step.returned_model for step in result.steps if step.returned_model})
    return {
        "instance_id": instance_id,
        "stop_reason": str(result.stop_reason),
        "steps": len(result.steps),
        "api_calls": result.api_calls,
        "cost": round(result.total_cost, 6),
        "loop_seconds": round(result.total_duration, 1),
        "wall_seconds": round(time.time() - started, 1),
        "patch_chars": len(patch),
        "tool_errors": sum(1 for step in result.steps if step.status == "error"),
        "returned_models": returned,  # 中转站给的模型名，和请求的名字对不对得上（执行计划 §八）
        "error": result.error,
    }


def load_instances(instances_file: Path, limit: int | None) -> list[dict]:
    """按 id 文件取实例，顺序照文件里的顺序，不按 dataset 的顺序。"""
    from datasets import load_dataset

    wanted = [line.strip() for line in instances_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None:
        wanted = wanted[:limit]

    by_id = {row["instance_id"]: row for row in load_dataset(DATASET, split="test")}
    missing = [instance_id for instance_id in wanted if instance_id not in by_id]
    if missing:
        raise KeyError(f"not in {DATASET}: {missing}")
    return [by_id[instance_id] for instance_id in wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scaffold over a list of SWE-bench instances.")
    parser.add_argument("--run-id", required=True, help="results/inference/<run-id>/ 下落盘")
    parser.add_argument("--instances", default="subset_ids.txt", help="一行一个 instance_id")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    parser.add_argument("--model", default=None, help="litellm 模型名，默认 agent.model.DEFAULT_MODEL")
    parser.add_argument("--workers", type=int, default=4, help="并行实例数；瓶颈是磁盘和内存，不是 CPU")
    parser.add_argument("--max-steps", type=int, default=LoopConfig.max_steps)
    parser.add_argument("--cost-limit", type=float, default=LoopConfig.cost_limit)
    parser.add_argument("--wall-clock-limit", type=float, default=LoopConfig.wall_clock_limit)
    parser.add_argument("--overwrite", action="store_true", help="重跑已经有 trajectory 的实例")
    parser.add_argument("--staged", action="store_true",
                        help="P4 分阶段 Round：骨架 system prompt + 三段指令 + 逐段工具表（agent/staged.py）")
    args = parser.parse_args(argv)

    from agent.model import DEFAULT_MODEL, LiteLLMClient

    model = args.model or DEFAULT_MODEL
    out_dir = REPO_ROOT_DIR / "results" / "inference" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    instances = load_instances(REPO_ROOT_DIR / args.instances, args.limit)
    if not args.overwrite:
        instances = [row for row in instances if not (out_dir / f"{row['instance_id']}.traj.json").exists()]
    if not instances:
        print("nothing to run (all instances already have a trajectory; pass --overwrite to redo them)")
        return 0

    config = LoopConfig(max_steps=args.max_steps, cost_limit=args.cost_limit,
                        wall_clock_limit=args.wall_clock_limit)

    # --staged 的切法是按 40 轮定死的（agent/staged.py 的常量）。max_steps 对不上就整批错位，
    # 与其跑完一批才发现段边界落在别处，不如当场炸掉（同 _validated_declaration 的理由）。
    staged_kwargs: dict[str, Any] = {}
    staged_fingerprint: dict[str, Any] | None = None
    if args.staged:
        from agent import staged

        if args.max_steps != staged.TOTAL_STEPS:
            parser.error(f"--staged 的切法按 {staged.TOTAL_STEPS} 轮定死，"
                         f"--max-steps={args.max_steps} 会让段边界错位")
        staged_kwargs = {"system_prompt": staged.SKELETON_SYSTEM_PROMPT,
                         "tool_policy": staged.tool_policy,
                         "stage_notes": staged.STAGE_NOTES}
        staged_fingerprint = staged.fingerprint()
        print(f"staged: cut={staged_fingerprint['cut']} "
              f"system_prompt_md5={staged_fingerprint['system_prompt_md5']}", flush=True)

    print(f"run-id={args.run_id} model={model} instances={len(instances)} workers={args.workers}", flush=True)

    lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    preds: dict[str, dict[str, str]] = {}
    started = time.time()

    def finish(row: dict[str, Any], patch_path: Path) -> None:
        """一条跑完就立刻落盘：整批跑几小时，中途挂掉不能把前面的结果一起丢掉（决定 R6）。"""
        with lock:
            rows.append(row)
            preds[row["instance_id"]] = {
                "instance_id": row["instance_id"],
                "model_name_or_path": model,
                "model_patch": json.loads(patch_path.read_text(encoding="utf-8"))["model_patch"],
            }
            (out_dir / "preds.json").write_text(json.dumps(preds, indent=2), encoding="utf-8")
            (out_dir / "summary.json").write_text(
                json.dumps({"run_id": args.run_id, "model": model, "config": asdict(config),
                            "staged": staged_fingerprint,
                            "elapsed_seconds": round(time.time() - started, 1),
                            "instances": sorted(rows, key=lambda item: item["instance_id"])},
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            done, total = len(rows), len(instances)
            print(f"[{done}/{total}] {row['instance_id']} {row['stop_reason']} "
                  f"steps={row['steps']} cost=${row['cost']:.4f} patch={row['patch_chars']}ch "
                  f"{row['wall_seconds']}s", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_instance, instance,
                        client_factory=lambda: LiteLLMClient(model),
                        config=config, out_dir=out_dir, **staged_kwargs): instance["instance_id"]
            for instance in instances
        }
        for future in as_completed(futures):
            instance_id = futures[future]
            finish(future.result(), out_dir / f"{instance_id}.traj.json")

    total_cost = sum(row["cost"] for row in rows)
    with_patch = sum(1 for row in rows if row["patch_chars"] > 0)
    print(f"\ndone: {len(rows)} instances, {with_patch} produced a patch, "
          f"${total_cost:.4f}, {round(time.time() - started, 1)}s")
    print(f"preds: {out_dir / 'preds.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
