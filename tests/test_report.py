"""归因表的单测。

最要紧的一条是**模式 0 和模式 3 的分辨**：两者的 report.json 长得一模一样
（F2P 过、P2P 挂），但归因完全相反 —— 一个是实例本身判不了，一个是 Agent 改坏了。
区分的唯一办法是先跑 gold，所以 `classify` 里模式 0 必须排在前面。
"""
import json

import pytest

from agent.report import MODES, Row, build_rows, classify, render, undecidable_ids


def report(resolved=False, f2p_failed=(), p2p_failed=(), **flags) -> dict:
    return {
        "patch_is_None": flags.get("patch_is_None", False),
        "patch_exists": flags.get("patch_exists", True),
        "patch_successfully_applied": flags.get("patch_successfully_applied", True),
        "resolved": resolved,
        "infra_failure": flags.get("infra_failure", False),
        "tests_status": {
            "FAIL_TO_PASS": {"success": [], "failure": list(f2p_failed)},
            "PASS_TO_PASS": {"success": [], "failure": list(p2p_failed)},
        },
    }


def mode_of(rep, instance_id="x__x-1", undecidable=frozenset()):
    return classify(rep, instance_id, set(undecidable))[0]


def test_resolved_wins_over_everything():
    assert mode_of(report(resolved=True)) == "resolved"


def test_an_undecidable_instance_is_not_blamed_on_the_agent():
    """模式 0 长得和模式 3 一样，但必须先判 —— 否则归因表会把环境问题记成 Agent 引入的回归。"""
    same_shape = report(p2p_failed=["test_a"])
    assert mode_of(same_shape) == "M3_regression"
    assert mode_of(same_shape, undecidable={"x__x-1"}) == "M0_undecidable"


def test_no_patch_and_rejected_patch_are_different_buckets():
    assert mode_of(report(patch_is_None=True)) == "M1a_no_patch"
    assert mode_of(report(patch_exists=False)) == "M1a_no_patch"
    assert mode_of(report(patch_successfully_applied=False)) == "M1b_patch_rejected"


def test_fail_to_pass_beats_pass_to_pass():
    """两边都挂时算模式 2：还没修好就谈不上「引入回归」。"""
    assert mode_of(report(f2p_failed=["a"], p2p_failed=["b"])) == "M2_fail_to_pass"


def test_infra_failure_is_singled_out_before_the_agent_buckets():
    assert mode_of(report(infra_failure=True, f2p_failed=["a"])) == "E1_infra"


def test_unresolved_with_nothing_failing_is_ambiguous_not_silently_resolved():
    """既没 resolved 又挑不出挂掉的测试 —— 不能当成功，要进单独的桶让人去看。"""
    assert mode_of(report()) == "E2_ambiguous"


def test_every_mode_has_a_description_and_a_fix_direction():
    for name, (what, fix) in MODES.items():
        assert what and fix, name


def test_undecidable_ids_reads_the_gold_run(tmp_path):
    results = tmp_path / "results" / "evaluation" / "s1-gold-subset"
    results.mkdir(parents=True)
    (results / "results.json").write_text(
        json.dumps({"unresolved_ids": ["a__a-1"], "error_ids": ["b__b-2"]}), encoding="utf-8")
    assert undecidable_ids(root=tmp_path) == {"a__a-1", "b__b-2"}
    assert undecidable_ids(root=tmp_path / "nope") == set()  # 没跑过 gold 就当没有，不报错


def test_render_hides_empty_buckets_and_reports_the_gradable_denominator():
    rows = [Row("a__a-1", "resolved", stop_reason="finished"),
            Row("b__b-2", "M0_undecidable"),
            Row("c__c-3", "M2_fail_to_pass", stop_reason="max_steps", f2p_failed=["t"])]
    text = render("demo", rows)
    assert "M1a_no_patch" not in text, "没有的桶不该出现在表里"
    assert "resolved 1/3" in text and "1/2" in text, "要同时给原始分母和剔除后的分母"
    assert "停止原因 × 结论" in text


def test_build_rows_refuses_to_guess_when_the_eval_logs_are_gone(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_rows("never-ran", root=tmp_path)


def test_the_gold_replay_run_attributes_as_all_resolved():
    """回归锚点：gold 回放的 25 条必须全在 resolved 桶，一条都不许漏进失败桶。"""
    rows = build_rows("gold-replay-s25")
    assert len(rows) == 25
    assert {row.mode for row in rows} == {"resolved"}
    assert all(row.stop_reason == "finished" and row.tool_errors == 0 for row in rows)
