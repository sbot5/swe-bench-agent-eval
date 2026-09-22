# badcase 归因表 · `p4-r2`

共 10 条实例

| 模式 | 是什么 | 本次 | 修法方向 |
| --- | --- | ---: | --- |
| `resolved` | 解出来了 | **3** | — |
| `M2_fail_to_pass` | 打上了但 FAIL_TO_PASS 仍失败 | **1** | 最大的一桶，逐条读 trajectory：改了个像的 bug，或三处调用只改了一处 |
| `missing` | 没有评测记录 | **6** | 这条实例没跑，或 report.json 被清掉了 |

**resolved 3/10**

## 停止原因 × 结论

| stop_reason | 结论 | 条数 |
| --- | --- | ---: |
| `finished` | `resolved` | 2 |
| `max_steps` | `M2_fail_to_pass` | 1 |
| `max_steps` | `missing` | 6 |
| `max_steps` | `resolved` | 1 |

## 逐条

| 实例 | 结论 | stop_reason | 步数 | 工具错 | $ | patch | 挂了的测试 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `django__django-10554` | `missing` | `max_steps` | 49 | 0 | 0.0000 | 0 | — |
| `django__django-11138` | `missing` | `max_steps` | 54 | 2 | 0.0000 | 0 | — |
| `django__django-14631` | `missing` | `max_steps` | 52 | 1 | 0.0000 | 0 | — |
| `pylint-dev__pylint-4551` | `M2_fail_to_pass` | `max_steps` | 53 | 3 | 0.0000 | 2742 | tests/unittest_pyreverse_writer.py::test_dot_files[packages_No_Name.dot], tests/unittest_pyreverse_writer.py::test_dot_files[classes_No_Name.dot] |
| `pylint-dev__pylint-8898` | `missing` | `max_steps` | 46 | 0 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-11510` | `missing` | `max_steps` | 50 | 2 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-8638` | `missing` | `max_steps` | 55 | 0 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-9711` | `resolved` | `finished` | 27 | 0 | 0.0000 | 1787 | — |
| `sympy__sympy-17630` | `resolved` | `max_steps` | 44 | 0 | 0.0000 | 702 | — |
| `sympy__sympy-18211` | `resolved` | `finished` | 33 | 0 | 0.0000 | 824 | — |
