# badcase 归因表 · `s5-mine`

共 25 条实例，对照 `s5-baseline`（21 条）

| 模式 | 是什么 | 本次 | `s5-baseline` | 修法方向 |
| --- | --- | ---: | ---: | --- |
| `resolved` | 解出来了 | **12** | 21 | — |
| `M2_fail_to_pass` | 打上了但 FAIL_TO_PASS 仍失败 | **4** | 0 | 最大的一桶，逐条读 trajectory：改了个像的 bug，或三处调用只改了一处 |
| `missing` | 没有评测记录 | **9** | 0 | 这条实例没跑，或 report.json 被清掉了 |

**resolved 12/25**

## 停止原因 × 结论

| stop_reason | 结论 | 条数 |
| --- | --- | ---: |
| `finished` | `M2_fail_to_pass` | 2 |
| `finished` | `resolved` | 11 |
| `max_steps` | `M2_fail_to_pass` | 2 |
| `max_steps` | `missing` | 9 |
| `max_steps` | `resolved` | 1 |

## 逐条

| 实例 | 结论 | stop_reason | 步数 | 工具错 | $ | patch | 挂了的测试 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `astropy__astropy-14182` | `M2_fail_to_pass` | `max_steps` | 53 | 2 | 0.0000 | 720 | astropy/io/ascii/tests/test_rst.py::test_rst_with_header_rows |
| `astropy__astropy-7166` | `resolved` | `finished` | 17 | 0 | 0.0000 | 639 | — |
| `django__django-10554` | `missing` | `max_steps` | 44 | 3 | 0.0000 | 0 | — |
| `django__django-11138` | `missing` | `max_steps` | 56 | 2 | 0.0000 | 0 | — |
| `django__django-11163` | `resolved` | `finished` | 10 | 2 | 0.0000 | 570 | — |
| `django__django-11728` | `resolved` | `finished` | 15 | 0 | 0.0000 | 2136 | — |
| `django__django-12039` | `M2_fail_to_pass` | `finished` | 12 | 0 | 0.0000 | 657 | test_descending_columns_list_sql (indexes.tests.SchemaIndexesTests) |
| `django__django-12262` | `resolved` | `finished` | 7 | 0 | 0.0000 | 716 | — |
| `django__django-13512` | `M2_fail_to_pass` | `finished` | 10 | 1 | 0.0000 | 534 | test_json_display_for_field (admin_utils.tests.UtilsTests), test_label_for_field (admin_utils.tests.UtilsTests) |
| `django__django-14631` | `missing` | `max_steps` | 50 | 1 | 0.0000 | 0 | — |
| `django__django-15863` | `resolved` | `finished` | 11 | 0 | 0.0000 | 463 | — |
| `matplotlib__matplotlib-24970` | `resolved` | `finished` | 24 | 0 | 0.0000 | 982 | — |
| `pydata__xarray-4356` | `resolved` | `finished` | 37 | 1 | 0.0000 | 840 | — |
| `pylint-dev__pylint-4551` | `missing` | `max_steps` | 57 | 1 | 0.0000 | 0 | — |
| `pylint-dev__pylint-8898` | `missing` | `max_steps` | 52 | 0 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-11510` | `missing` | `max_steps` | 48 | 1 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-7889` | `resolved` | `finished` | 9 | 0 | 0.0000 | 590 | — |
| `sphinx-doc__sphinx-8638` | `missing` | `max_steps` | 53 | 1 | 0.0000 | 0 | — |
| `sphinx-doc__sphinx-9698` | `resolved` | `finished` | 9 | 0 | 0.0000 | 624 | — |
| `sphinx-doc__sphinx-9711` | `resolved` | `finished` | 41 | 2 | 0.0000 | 1294 | — |
| `sympy__sympy-13757` | `resolved` | `finished` | 45 | 1 | 0.0000 | 443 | — |
| `sympy__sympy-13852` | `M2_fail_to_pass` | `max_steps` | 46 | 3 | 0.0000 | 1116 | test_polylog_values |
| `sympy__sympy-17630` | `missing` | `max_steps` | 44 | 0 | 0.0000 | 0 | — |
| `sympy__sympy-18211` | `missing` | `max_steps` | 48 | 1 | 0.0000 | 0 | — |
| `sympy__sympy-24661` | `resolved` | `max_steps` | 50 | 1 | 0.0000 | 2060 | — |
