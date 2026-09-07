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

4. Observation 的 __post_init__ 连踩三次同一片区域，三次都不报错也不警告，
   只是条件恒真或恒假：
       `True if A or B else False`  —— or 是取值运算，不是「或者等于」
       `x is [] or None`            —— is 比身份不比值；且 or 不会把左边的比较分配过去
       `x is not []`                —— `not X` 和 `X is not Y` 是两个不同的 not
   规矩：is 只用于 None 和单例（Enum 成员）；跟字面量比较一律用 ==；
   判空直接判真假值（not [] / not None / not "" 都是 True）。
"""
from enum import StrEnum, auto, unique
from dataclasses import dataclass, field
from typing import Self

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

@dataclass(frozen=True)
class Observation:
    """所有工具的统一返回形状。

    模型对这个世界的全部认知，就是这东西渲染出来的字符串的累加 —— 它看不见
    文件系统、看不见容器、看不见 Python 对象，只看得见 messages。所以这不是
    一个数据结构文件，是我和模型之间唯一的那根管子。

    五个字段分属两个读者，判据不同：
        summary / content / next_actions   渲染成文本给模型 ——
                                           标准：只读这一段能不能定下一步
        status / failure_category          序列化进 trajectory 给我 ——
                                           标准：三周后不看代码能不能读出为什么失败

    决定一：dataclass，不用 Pydantic
    理由：判据是信任边界。Pydantic 的运行时校验防的是外部输入 —— AgentConfig
          用它，是因为 .venv/.../minisweagent/agents/default.py:41 那行的 kwargs
          来自 YAML 配置文件。Observation 是
          我的代码造、我的代码消费，不跨边界。防我自己写错的是类型检查器 +
          __post_init__，不是运行时校验。
    否决：· Pydantic —— 一次运行造几千个，为用不上的能力付运行时开销
          · 裸 dict（mini 循环里的写法）—— 强制不了下面那两条不变量。
            mini 的目标是「极简」，我的目标是「归因数据可信」。
    代价：没有 model_dump_json。实测不成立 —— asdict() + json.dumps() 两行，
          StrEnum 本身就是 str，直接出可读 JSON。

    决定二：frozen=True
    理由：没有任何一处需要在创建之后修改它 —— 工具造好就交出去，loop 只读它
          渲染，归因脚本只读它统计。而它是 trajectory 的数据源，数据源被中途
          改写是最难查的一类 bug。
    否决：可变 dataclass —— 省下的是 dataclasses.replace() 那一行，换来的是
          「谁在什么时候改过它」这个永远查不清的问题。
    代价：__post_init__ 里只能检查并 raise，不能顺手规范化字段值。

    决定三：只有 failure_category 带 | None
    理由：| None 不是「可选参数」的写法，是一句语义声明 —— 它多加一个「不存在」
          状态，那就必须答得出谁会对这个状态分支。
              failure_category   None = 没失败，归因脚本和不变量都分支 -> 留
              summary / content  None 和 "" 没区别，没人分支           -> 必填
              next_actions       None 和 [] 没区别，没人分支            -> 默认空列表
    否决：四个字段全 | None（第一版的写法）—— 等于允许某个工具返回一个模型
          读不懂的观察。

    决定四：不变量在构造时炸，不在使用时检查
    理由：给模型的那三个字段写砸了有实时反馈（模型下一轮就走偏，当场看得见）；
          给我的那两个没有 —— 要等 25 条跑完、打开归因表、发现一半是空的才
          知道，那时候钱和时间都花完了。
              error -> failure_category 必须有（否则归因表少一行）
              error -> next_actions 必须非空（否则模型收到「失败了，没了」，
                       在原地空转到烧光 step_limit）
    """

    status: ToolStatus
    """工具有没有完成它的活。loop 就靠它二分。"""

    summary: str
    """一行说清发生了什么。模型只读这一行也该知道个大概。"""

    content: str
    """正文，可能被截断。截断说明必须写在这里面 —— 不设 truncated 字段。"""

    next_actions: list[str] = field(default_factory=list)
    """下一步能做什么。error 时必须非空 —— 错误契约三件套的落点。"""

    failure_category: FailureCategory | None = None
    """归因表的行标签。成功时为 None，error 时必填。"""

    def __post_init__(self):
        if self.status == ToolStatus.ERROR:
            if not self.next_actions:
                raise ValueError("Next action is empty")
            if self.failure_category is None:
                raise ValueError("Failure category is empty")

    @classmethod
    def ok(cls, next_actions: list[str] | None = None, *, summary: str, content: str) -> Self:
        """造一个「工具正常完成」的观察。

        不收 status（函数名就是 status），更关键的是不收 failure_category ——
        后者是这个构造器存在的全部理由。__post_init__ 的两条不变量只管
        status == ERROR 那个分支，所以 Observation(status=OK, failure_category=IO_ERROR)
        在那里完全合法，会静静进归因表。签名里没有这个参数，它就造不出来。

        next_actions 可选但保留：成功也可能有下一步 —— read_file 读了 40 行、
        截断了，观察是 OK，但要告诉模型「还有 60 行，用 offset=450 继续读」。

        默认值走哨兵（None -> 函数体里换成新的空列表），不能直接写 `= []`：
        普通函数的默认值只在 def 那一行求值一次，之后所有调用共用同一个 list。
        dataclass 字段会拒绝这种写法（ValueError），普通函数和 classmethod 不会。

        summary / content 在裸 * 后面，强制关键字传参。理由：两个都是 str，
        位置写反了 Python 不报错、Pylance 不报错、运行时也不报错 —— 模型收到
        一行 60 字的「摘要」和 6 个字的「正文」。
        判据：能位置传的参数，类型必须互不混淆。
        """
        next_actions = next_actions or []
        return cls(status=ToolStatus.OK, summary=summary, content=content, next_actions=next_actions)

    @classmethod
    def error(cls, failure_category: FailureCategory, next_actions: list[str], *, summary: str, content: str) -> Self:
        """造一个「工具没能完成」的观察。

        一个默认值都没有 —— 这是它和 ok() 最大的区别。「必填」在 Python 里只有
        一种实现：不给默认值。少传就是 TypeError，Pylance 在敲代码时就画红线。
        目的就是把 __post_init__ 的运行时检查提前到编辑期。

        两层防线不重复，各管一段：
            签名（无默认值 + *）   传没传、有没有传错位置    TypeError    敲代码时
            __post_init__         传的内容对不对（非空）    ValueError   运行时
        error(cat, [], ...) 会通过签名检查 —— Python 没有「非空列表」这个类型。
        所以类 docstring 决定四那条不变量，签名替代不了，必须留着。

        failure_category 排在 next_actions 之前：读一个调用点时最先要知道的是
        「出了什么问题」，类别是这个错误的身份，next_actions 是对策。
        summary / content 关键字传参，理由同 ok()。
        """
        return cls(status=ToolStatus.ERROR, failure_category=failure_category, next_actions=next_actions, summary=summary, content=content)
