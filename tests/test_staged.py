"""P4 分阶段配置的单测（`agent/staged.py`）。

测的是**配置本身自洽**，不是「分阶段有没有用」—— 后者要真跑，判据在 `docs/EVAL-P4-staged.md`。
这里钉死的是三件跑前必须成立的事：段边界与指令表对得上、每段工具集合法、指纹随内容变。
"""
from agent import staged
from agent.loop import FINISH_TOOL, _validated_declaration, build_tool_schemas


def test_every_stage_lists_its_tools_in_the_canonical_schema_order():
    """落盘的 `tools_declared` 用的是这里的顺序，真正发出去的工具表用的是 schema 原顺序。

    两边不一致，记录就与事实对不上 —— 后面按 `tools_declared` 重建每轮工具表的分析
    （C24 的 `scripts/cache_sim.py`）会拿到一个从未发生过的顺序。
    """
    canonical = [schema["function"]["name"] for schema in build_tool_schemas()]
    for stage, names in staged.STAGE_TOOLS.items():
        expected = [name for name in canonical if name in names]
        assert list(names) == expected, f"{stage} 段的工具顺序与 build_tool_schemas 不一致"


def test_every_step_in_the_budget_belongs_to_exactly_one_stage():
    stages = [staged.stage_of(index) for index in range(1, staged.TOTAL_STEPS + 1)]
    assert stages.count("COLLECT") == staged.COLLECT_END
    assert stages.count("IMPLEMENT") == staged.IMPLEMENT_END - staged.COLLECT_END
    assert stages.count("VERIFY") == staged.TOTAL_STEPS - staged.IMPLEMENT_END
    assert set(stages) == set(staged.STAGE_TOOLS), "段名必须与工具表的键一一对应"


def test_a_round_note_fires_on_the_first_step_of_each_stage():
    """指令要在段的第一步就到，晚一步模型就用旧指令多走一轮（决定 C25）。"""
    firsts = [1, staged.COLLECT_END + 1, staged.IMPLEMENT_END + 1]
    assert sorted(staged.STAGE_NOTES) == firsts
    for step in firsts:
        assert staged.stage_of(step) != staged.stage_of(step - 1) or step == 1


def test_each_round_note_names_the_stage_it_opens():
    for step, note in staged.STAGE_NOTES.items():
        assert f'name="{staged.stage_of(step)}"' in note


def test_every_stage_declares_a_legal_tool_set():
    """摘掉 finish 就等于只能跑到 max_steps 为止 —— 那是配置错误，`_validated_declaration` 会当场炸。"""
    wired = {name: object() for name in
             ("list_files", "search_code", "read_file", "apply_patch", "run_tests", "run_python", "git_diff")}
    for stage, names in staged.STAGE_TOOLS.items():
        assert FINISH_TOOL in names, f"{stage} 段摘掉了 finish"
        assert _validated_declaration(list(names), wired) == list(names)


def test_read_file_survives_every_stage():
    """摘掉读就会打爆 apply_patch 的锚点匹配（gold 回放 66/66 那条性质靠它）。"""
    for names in staged.STAGE_TOOLS.values():
        assert "read_file" in names


def test_the_collect_stage_cannot_edit_and_the_later_stages_can():
    """成分③ 的强制力就在这一条：Collect 段拿不到 apply_patch，不是靠指令劝住的。"""
    assert "apply_patch" not in staged.STAGE_TOOLS["COLLECT"]
    assert "apply_patch" in staged.STAGE_TOOLS["IMPLEMENT"]
    assert "apply_patch" in staged.STAGE_TOOLS["VERIFY"]


def test_the_archaeology_tools_are_gone_after_the_collect_stage():
    """H2「转身去找上游标准答案」是已知卡点，搜索与列目录两条向量在 Collect 之后就收掉。"""
    for stage in ("IMPLEMENT", "VERIFY"):
        assert "search_code" not in staged.STAGE_TOOLS[stage]
        assert "list_files" not in staged.STAGE_TOOLS[stage]


def test_the_tool_policy_returns_the_set_of_the_stage_that_step_is_in():
    for index in (1, staged.COLLECT_END, staged.COLLECT_END + 1,
                  staged.IMPLEMENT_END, staged.IMPLEMENT_END + 1, staged.TOTAL_STEPS):
        assert staged.tool_policy(index, None) == staged.STAGE_TOOLS[staged.stage_of(index)]


def test_the_skeleton_prompt_dropped_the_six_step_recipe_but_kept_the_grading_rules():
    """六步不删就会与段指令并存、互相矛盾（P3 ⒜ 那个教训的同型）。"""
    assert "How to work:" not in staged.SKELETON_SYSTEM_PROMPT
    assert "Rules that matter for how your work is graded:" in staged.SKELETON_SYSTEM_PROMPT
    assert "an empty diff scores zero" in staged.SKELETON_SYSTEM_PROMPT
    assert "three rounds" in staged.SKELETON_SYSTEM_PROMPT


def test_the_fingerprint_changes_when_the_instruction_the_loop_actually_gets_changes():
    """改的必须是 `STAGE_NOTES`，不是 `ROUND_*` 常量 —— 循环收到的是前者。

    头一版这条测试改的是常量，于是「直接改 STAGE_NOTES 的文本」能换掉发给模型的指令
    而指纹纹丝不动，测试却照样绿（Codex 09-22 MINOR-1）。
    """
    before = staged.fingerprint()
    original = dict(staged.STAGE_NOTES)
    try:
        staged.STAGE_NOTES[1] = original[1] + "one more line\n"
        assert staged.fingerprint()["stage_notes_md5"]["1"] != before["stage_notes_md5"]["1"]
    finally:
        staged.STAGE_NOTES.clear()
        staged.STAGE_NOTES.update(original)
    assert staged.fingerprint() == before


def test_the_fingerprint_changes_when_a_tool_description_changes():
    """请求里发的是完整 schema，不是工具名。描述或参数改了，`stage_tools` 那张名字表看不出来。"""
    from agent import loop

    before = staged.fingerprint()
    original = loop._TOOL_SCHEMAS[0]["description"]
    try:
        loop._TOOL_SCHEMAS[0]["description"] = original + " (reworded)"
        assert staged.fingerprint()["tool_schema_template_md5"] != before["tool_schema_template_md5"]
    finally:
        loop._TOOL_SCHEMAS[0]["description"] = original
    assert staged.fingerprint() == before
