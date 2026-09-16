"""run.py 的单测：测试命令怎么抽出来、patch 怎么提取、gold 补丁怎么拆成编辑。

抽测试命令那一条要跑遍 subset + holdout 全部 75 条：它错一条，那条实例的 run_tests 就是废的，
而且「评分目标有没有漏在前缀里」是方法论问题，不能靠抽查（决定 R2）。
"""
import pytest

from agent.run import REPO_ROOT_DIR, derive_test_command, extract_patch, load_instances, target_forms, graded_test_files
from tests.fake_env import FakeEnvironment, ok, timed_out
from tests.gold_replay import parse_patch


@pytest.fixture(scope="module")
def instances():
    """subset 25 + holdout 50，全部 75 条。数据集本地有缓存，秒级。"""
    return load_instances(REPO_ROOT_DIR / "subset_ids.txt", None) + \
        load_instances(REPO_ROOT_DIR / "holdout_ids.txt", None)


def test_test_patch_files_takes_both_sides_of_a_rename():
    patch = "diff --git a/tests/py3_old.py b/tests/new.py\nsimilarity index 90%\n"
    assert graded_test_files(patch) == {"tests/py3_old.py", "tests/new.py"}


def test_target_forms_covers_the_dotted_module_spelling():
    forms = target_forms({"tests/forms_tests/field_tests/test_jsonfield.py"})
    assert "tests/forms_tests/field_tests/test_jsonfield.py" in forms
    assert "forms_tests.field_tests.test_jsonfield" in forms  # django runtests 用的写法


def test_no_graded_test_target_survives_in_any_prefix(instances):
    """最重要的一条：评分用的测试文件名不能出现在给 Agent 的命令里（决定 R2）。"""
    for instance in instances:
        prefix, _ = derive_test_command(instance)
        forms = target_forms(graded_test_files(instance["test_patch"]))
        leaked = [form for form in forms if form and form in prefix]
        assert not leaked, f"{instance['instance_id']}: 评分目标漏进前缀 {leaked}"


def test_every_instance_yields_a_runnable_prefix_and_a_hint(instances):
    shapes = set()
    for instance in instances:
        prefix, hint = derive_test_command(instance)
        assert prefix and hint
        assert "--tb=no" not in prefix, f"{instance['instance_id']}: 关掉堆栈的标志要去掉（决定 R3）"
        shapes.add(prefix)
    assert len(shapes) == 5, f"75 条应该只有 5 种运行器前缀，实际 {len(shapes)} 种：{sorted(shapes)}"


def test_extract_patch_never_raises_on_a_broken_container():
    assert extract_patch(FakeEnvironment([timed_out()])) == ""
    assert extract_patch(FakeEnvironment([ok(exit_code=128)])) == ""
    assert extract_patch(FakeEnvironment([ok(stdout="diff --git a/f b/f\n")])) == "diff --git a/f b/f\n"


def test_extract_patch_does_not_stage_anything():
    """决定 R5：只取已跟踪文件的改动，不 git add -A，否则构建产物会被卷进答案。"""
    env = FakeEnvironment([ok(stdout="")])
    extract_patch(env)
    assert "add" not in env.commands[0]


# --------------------------------------------------------- gold patch -> 编辑

def test_parse_patch_turns_a_hunk_into_one_search_replace_pair():
    patch = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,3 +1,3 @@\n ctx\n-old\n+new\n ctx2\n"
    )
    edits = parse_patch(patch)
    assert len(edits) == 1
    assert edits[0].path == "f.py"
    assert edits[0].old_string == "ctx\nold\nctx2"
    assert edits[0].new_string == "ctx\nnew\nctx2"


def test_parse_patch_skips_new_files_because_apply_patch_cannot_create_them():
    patch = (
        "diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n+a\n+b\n"
    )
    assert parse_patch(patch) == []


def test_parse_patch_ignores_the_no_newline_marker():
    patch = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n"
    )
    edits = parse_patch(patch)
    assert edits[0].old_string == "old" and edits[0].new_string == "new"


def test_every_gold_hunk_in_the_dev_subset_becomes_an_edit():
    """apply_patch 的表达力下限：25 条 gold patch 的每个 hunk 都要能变成一对 (old, new)。"""
    subset = load_instances(REPO_ROOT_DIR / "subset_ids.txt", None)
    total = 0
    for instance in subset:
        edits = parse_patch(instance["patch"])
        assert edits, f"{instance['instance_id']}: 一个 hunk 都没拆出来"
        assert all(edit.old_string.strip() for edit in edits), f"{instance['instance_id']}: 有空锚点"
        total += len(edits)
    assert total == 66, f"dev 子集应有 66 个 hunk，实际 {total}（补丁变了就更新这个数）"
