# badcase 归因表 · `p4-r1`

共 10 条实例

| 模式 | 是什么 | 本次 | 修法方向 |
| --- | --- | ---: | --- |
| `resolved` | 解出来了 | **4** | — |
| `M2_fail_to_pass` | 打上了但 FAIL_TO_PASS 仍失败 | **2** | 最大的一桶，逐条读 trajectory：改了个像的 bug，或三处调用只改了一处 |
| `missing` | 没有评测记录 | **4** | 这条实例没跑，或 report.json 被清掉了 |

**resolved 4/10**

## 停止原因 × 结论

| stop_reason | 结论 | 条数 |
| --- | --- | ---: |
| `finished` | `resolved` | 4 |
| `max_steps` | `M2_fail_to_pass` | 2 |
| `max_steps` | `missing` | 4 |

## 逐条

| 实例 | 结论 | stop_reason | 步数 | 工具错 | $ | patch | 挂了的测试 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `django__django-10554` | `missing` | `max_steps` | 53 | 0 | 0.0000 | 0 | — |
| `django__django-11138` | `missing` | `max_steps` | 53 | 2 | 0.0000 | 0 | — |
| `django__django-14631` | `resolved` | `finished` | 39 | 0 | 0.0000 | 4126 | — |
| `pylint-dev__pylint-4551` | `missing` | `max_steps` | 57 | 4 | 0.0000 | 0 | — |
| `pylint-dev__pylint-8898` | `M2_fail_to_pass` | `max_steps` | 57 | 1 | 0.0000 | 2700 | tests/config/test_config.py::test_csv_regex_error |
| `sphinx-doc__sphinx-11510` | `M2_fail_to_pass` | `max_steps` | 50 | 1 | 0.0000 | 2134 | tests/test_directive_other.py::test_include_source_read_event |
| `sphinx-doc__sphinx-8638` | `missing` | `max_steps` | 53 | 1 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-9711` | `resolved` | `finished` | 46 | 0 | 0.0000 | 2229 | — |
| `sympy__sympy-17630` | `resolved` | `finished` | 53 | 0 | 0.0000 | 621 | — |
| `sympy__sympy-18211` | `resolved` | `finished` | 43 | 3 | 0.0000 | 824 | — |
