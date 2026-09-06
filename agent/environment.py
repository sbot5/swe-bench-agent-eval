"""每条实例一个 Docker 容器，工具通过 docker exec 在里面执行。

为什么 Agent 代码不跑在容器里：容器里的 Python 是 3.6.13（配合被测仓库
的年代），宿主机 venv 是 3.12。mini-SWE-agent 也是这么做的。

容器事实（2026-09-06 实测 sweb.eval.x86_64.django_1776_django-11138）
--------------------------------------------------------------------
  工作目录    /testbed，仓库停在 base_commit，工作区干净
  没有 rg     用 git grep（只搜跟踪文件，自动跳过 .git 和构建产物）
  有          grep find git sed awk patch python(3.6.13)
  评分测试    不在容器里 —— test_patch 是评测时才应用的，Agent 看不到。
              这条已实测确认，评测没有被污染

要定的
--------------------------------------------------------------------
- 容器生命周期。起法可参考 mini：
      docker run -d --rm -w /testbed <image> sleep 2h
  什么时候销毁？异常退出时怎么保证也被销毁？
  跑 25 条攒一堆僵尸容器是真会发生的事。

- exec 的返回必须包含 stdout / stderr / exit_code 三样。
  只拿 stdout 会让「命令失败了但没输出」变成静默 bug。

- 单条命令超时。mini 的 swebench.yaml 用 60 秒。

- 安全边界放这一层还是工具层？
      路径白名单（只许碰 /testbed 下面）
      命令 allowlist（挡住 rm -rf 之类）
  放这里的好处：六个工具不用各写一遍。

镜像名规律：swebench/sweb.eval.x86_64.<repo>_1776_<instance 后半段>
用 docker images | grep sweb 看实际的。

验收
--------------------------------------------------------------------
起一个容器 -> exec 一条 echo -> 销毁；
再故意抛个异常，确认容器还是被清掉了。
"""
