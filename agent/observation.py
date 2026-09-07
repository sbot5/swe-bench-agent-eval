"""所有工具的统一返回形状。

第一个写这个文件，因为剩下六个工具都复制它的骨架。
先跑通格式，再跑通功能。

要定的四个字段：
    status        ok | error
    summary       一行说清发生了什么。模型只读这一行也该知道个大概
    content       正文，可能被截断
    next_actions  下一步能做什么。error 时这一条是必填

三条硬要求
--------------------------------------------------------------------
1. 截断必须可见。content 被截断时要在里面明确写出
   「还有 N 行，用 offset=X 继续读」。
   悄悄截断会让模型基于残缺信息改代码 -> 失败模式 2，
   而且你在 trajectory 里看不出来。

2. 错误契约三件套：根因提示 / 安全重试指令 / 明确的停止条件。
   停止条件最容易漏 —— 没有它，模型会在同一个错误上循环到
   烧光 step_limit，trajectory 里全是重复内容，归因时读不出东西。
   这就是面经里「reflection 失败 3 次怎么处理」的答案所在：
   它在工具的错误契约里，不在 loop 里。

3. 要有一个机器可读的失败类别字段 —— 这是归因表的数据来源。
   「六个有类型的工具而不是一个 bash」的全部理由就在这里。

还要定
--------------------------------------------------------------------
- 怎么序列化成给模型看的文本？工具返回的东西最终要变成一段字符串
- 失败类别怎么枚举？至少要能区分 apply_patch 的
  「old_string 没找到」和「old_string 不唯一」——
  这两种在归因表里是不同的行

验收
--------------------------------------------------------------------
随便造一个 error 观察，打印出来自己读一遍。
不看代码就知道下一步该干嘛，格式就对了。

已纠正的错误
--------------------------------------------------------------------
1. 原定「用显式字符串值，不要用 auto()」—— 这条对普通 Enum 成立
   （auto() 给整数，写进 trajectory JSON 三个月后读不懂），对 StrEnum
   不成立：StrEnum + auto() 给的是成员名的小写，正好就是想要的可读值，
   而且不可能写重。换成 StrEnum 之后原来的理由消失了，决定跟着改。
   值仍然可 grep：`grep -i anchor_ambiguous` 直接命中定义处。

2. 第一版把所有成员的值都写成了 ""。Enum 里值相同的成员会变成别名 ——
   8 个成员塌成 1 个，Counter 把三种不同失败全记到 ANCHOR_AMBIGUOUS
   头上。不报错，只是全错。@unique 就是让这件事在类定义那一刻就炸。

3. is_env_error 第一版写成 `True if IO_ERROR or TIMEOUT else False`，
   对所有成员恒返回 True（or 是取值运算不是比较，且方法体没用到 self）。
   归因表会说「全是环境问题」—— 同样不报错，同样全错。
   检查项：Enum 方法体里没有出现 self，这个方法一定写错了。
"""
from enum import StrEnum, auto, unique

class ToolStatus(StrEnum):
    """工具有没有完成它的活。不是「好消息 / 坏消息」。

    决定：两档 ok | error。
    理由：状态的唯一用途是让消费者分支，而两个消费者都不需要第三档 ——
          · loop 只问「这次失败了没有」，二分就够；三档会逼出
            `if status != ERROR` 这种别扭写法。
          · 归因脚本看 FailureCategory，根本不读 status。
          没有消费者的档位，唯一效果是逼我在每个工具里做一次
          「这算不算 warning」的主观判断 —— 我会答得不一致，
          被污染的是我自己的归因数据。
    否决：· ok | warning | error（通用 harness 模板的默认写法）
          · 三档 + 另设 truncated 字段 —— 同一个事实两个来源，迟早对不上。
    代价：模型可能漏看截断提示。这个在渲染层解决（截断说明放显眼位置，
          next_actions 给出继续读的具体调用），不在 status 里解决 ——
          截断是 content 的属性，不是结果的属性。

    命名同样是决定：
        ToolStatus 不叫 Status  —— Tool 提醒它描述的是工具，不是任务。
        OK 不叫 SUCCESS         —— SUCCESS 带「好消息」暗示，三周后我会
                                   本能地用它表示「测试通过了」，然后
                                   run_tests 挂 3 条时标成 ERROR，
                                   归因表当场污染。

    自测（必须是这三个答案）：
        run_tests 跑完，3 条挂了   -> OK      工具完成了活，坏消息 != 故障
        search_code 一条没搜到     -> OK      搜索本身成功，0 结果是有效答案
        read_file 路径不存在       -> ERROR   工具没能完成
    """

    OK = auto()
    ERROR = auto()

@unique
class FailureCategory(StrEnum):
    ANCHOR_AMBIGUOUS = auto()
    ANCHOR_NOT_FOUND = auto()
    PATH_NOT_FOUND = auto()
    PATH_OUTSIDE_ROOT = auto()
    FILE_UNCHANGED = auto()
    IO_ERROR = auto()
    TIMEOUT = auto()
    UNCLASSIFIED = auto()

    def is_env_error(self) -> bool:
        return self in { FailureCategory.IO_ERROR, FailureCategory.TIMEOUT }
