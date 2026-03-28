#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 评估数据集模块，覆盖事实题、多跳推理题、否定性查询、口语化查询四种题型。
"""
import json
import logging
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = str(
    Path(__file__).parent / 'data' / 'eval_dataset.json'
)


class QuestionType(Enum):
    FACTUAL = "factual"
    MULTI_HOP = "multi_hop"
    NEGATIVE = "negative"
    COLLOQUIAL = "colloquial"


@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: QuestionType
    difficulty: str
    topic: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d['question_type'] = self.question_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'EvalSample':
        d = dict(d)
        d['question_type'] = QuestionType(d['question_type'])
        return cls(**d)


def load_eval_dataset(path: Optional[str] = None) -> List[EvalSample]:
    """从 JSON 文件加载评估数据集。默认路径不存在时回退到内置数据集。"""
    if path is None:
        path = DEFAULT_DATASET_PATH

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.info(f"评估数据集文件不存在: {path}，使用默认数据集")
        return create_default_eval_dataset()

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and 'samples' in data:
        items = data['samples']
    else:
        raise ValueError(f"不支持的评估数据集格式: {path}")

    return [EvalSample.from_dict(item) for item in items]


def save_eval_dataset(samples: List[EvalSample], path: Optional[str] = None) -> None:
    """将评估数据集保存为 JSON 文件。"""
    if path is None:
        path = DEFAULT_DATASET_PATH

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    data = {
        'samples': [s.to_dict() for s in samples],
        'total': len(samples),
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"评估数据集已保存: {path} ({len(samples)} 条)")


def create_default_eval_dataset() -> List[EvalSample]:
    """创建默认评估数据集（30 条，覆盖四种题型）。"""
    return [
        EvalSample(
            id="f001",
            question="健康保险的等待期有什么规定？",
            ground_truth="既往症人群的等待期不应与健康人群有过大差距。在对既往症严重程度进行区分时，相关定义需明确。",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["等待期", "既往症", "健康人群"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="健康保险",
        ),
        EvalSample(
            id="f002",
            question="分红型保险的死亡保险金额有什么要求？",
            ground_truth="对于投保时被保险人年龄满18周岁的个人分红终身寿险和个人分红两全保险，死亡保险金额不得低于已交保费的120%。",
            evidence_docs=["07_分红型人身保险.md"],
            evidence_keywords=["分红型", "死亡保险金额", "120%"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="分红型保险",
        ),
        EvalSample(
            id="f003",
            question="普通型人身保险的佣金有什么规定？",
            ground_truth="付佣金的，佣金占年度保费的比例以所售产品定价时的附加费用率为上限。",
            evidence_docs=["06_普通型人身保险.md"],
            evidence_keywords=["佣金", "附加费用率", "普通型"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="普通型保险",
        ),
        EvalSample(
            id="f004",
            question="短期健康保险的保证续保有什么规定？",
            ground_truth='短期健康保险产品不得包含保证续保条款，严禁使用"自动续保""承诺续保""终身限额"等易与长期健康保险混淆的词句。',
            evidence_docs=["08_短期健康保险.md"],
            evidence_keywords=["短期健康保险", "保证续保", "自动续保"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="短期健康保险",
        ),
        EvalSample(
            id="f005",
            question="意外伤害保险的定价原则是什么？",
            ground_truth="意外伤害保险应当回归保障本源，科学合理定价，保费应当根据风险程度合理厘定，不得低于成本价销售。",
            evidence_docs=["09_意外伤害保险.md"],
            evidence_keywords=["意外伤害保险", "定价", "保障本源"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="f006",
            question="互联网保险业务的定义是什么？",
            ground_truth="互联网保险业务是指保险机构依托互联网和移动通信等技术，通过自营网络平台、第三方网络平台等订立保险合同、提供保险服务的业务。",
            evidence_docs=["10_互联网保险产品.md"],
            evidence_keywords=["互联网保险", "自营网络平台", "保险合同"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="互联网保险",
        ),
        EvalSample(
            id="f007",
            question="万能型人身保险的最低保证利率有什么规定？",
            ground_truth="万能型人身保险的最低保证利率由保险公司根据自身情况自主确定，但应满足监管规定的准备金评估利率上限要求。",
            evidence_docs=["12_万能型人身保险.md"],
            evidence_keywords=["万能型", "最低保证利率", "准备金评估利率"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="万能型保险",
        ),
        EvalSample(
            id="f008",
            question="税优健康险的投保人范围包括哪些人？",
            ground_truth="税优健康险的投保范围已扩大，投保人为本人、配偶、子女和父母。符合条件的纳税人可以享受个人所得税优惠政策。",
            evidence_docs=["11_税优健康险.md"],
            evidence_keywords=["税优健康险", "投保人", "配偶", "子女", "父母"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="税优健康险",
        ),
        EvalSample(
            id="f009",
            question="保险公司信息披露的基本原则是什么？",
            ground_truth="保险公司信息披露应当遵循真实性、准确性、完整性和及时性原则，不得有虚假记载、误导性陈述或者重大遗漏。",
            evidence_docs=["04_信息披露规则.md"],
            evidence_keywords=["信息披露", "真实性", "准确性", "完整性", "及时性"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="信息披露",
        ),
        EvalSample(
            id="f010",
            question="保险条款和费率的审批备案程序是什么？",
            ground_truth="人身保险公司开发的保险条款和保险费率应当依法报经金融监督管理部门审批或者备案。审批和备案的具体要求按照相关规定执行。",
            evidence_docs=["03_条款费率管理办法.md"],
            evidence_keywords=["条款", "费率", "审批", "备案"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="条款费率管理",
        ),
        EvalSample(
            id="f011",
            question="负面清单中关于已停售产品有什么规定？",
            ground_truth="保险公司不得变相销售已停售产品，不得对已停售产品进行宣传、推介或者以其他方式引导投保人购买已停售产品。",
            evidence_docs=["02_负面清单.md"],
            evidence_keywords=["负面清单", "停售产品", "变相销售"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="负面清单",
        ),
        EvalSample(
            id="f012",
            question="健康保险产品包括哪些类型？",
            ground_truth="健康保险是指以因健康原因导致损失为给付保险金条件的保险，包括医疗保险、疾病保险、失能收入损失保险、护理保险以及医疗意外保险。",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["健康保险", "医疗保险", "疾病保险", "失能收入损失保险", "护理保险"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="健康保险",
        ),

        EvalSample(
            id="m001",
            question="买了两份意外险，发生意外后都能赔吗？",
            ground_truth="意外伤害保险属于定额给付型保险，被保险人从多份意外伤害保险中获得的保险金总和可以超过实际损失，各保险公司应按各自合同约定给付。但需注意是否存在特别约定的限额条款。",
            evidence_docs=["09_意外伤害保险.md", "01_保险法相关监管规定.md"],
            evidence_keywords=["意外伤害保险", "定额给付", "保险金", "多份"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="m002",
            question="万能险和分红险在收益方式上有什么区别？",
            ground_truth="万能险提供最低保证利率和结算利率，账户价值透明可查，投保人可以灵活追加保费。分红险的分红水平不确定，根据公司实际经营状况确定，分红方式包括现金分红和增额红利。万能险的收益体现在账户价值增长，分红险的收益体现在红利分配。",
            evidence_docs=["12_万能型人身保险.md", "07_分红型人身保险.md"],
            evidence_keywords=["万能险", "分红险", "最低保证利率", "结算利率", "红利"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="保险产品对比",
        ),
        EvalSample(
            id="m003",
            question="短期健康险和长期健康险在续保方面有什么不同？",
            ground_truth='短期健康保险产品不得包含保证续保条款，保险期间届满后需重新投保并经过核保。长期健康保险可以包含保证续保条款，在保证续保期间内保险公司不得因被保险人健康状况变化而拒绝续保或调整费率。短期健康险严禁使用"自动续保"等易与长期健康保险混淆的表述。',
            evidence_docs=["08_短期健康保险.md", "05_健康保险产品开发.md"],
            evidence_keywords=["短期健康保险", "长期健康保险", "保证续保", "自动续保", "核保"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="健康保险",
        ),
        EvalSample(
            id="m004",
            question="互联网销售保险产品需要满足哪些额外条件？",
            ground_truth="互联网销售保险产品除了满足一般保险产品要求外，还需满足：具备符合条件的自营网络平台或第三方网络平台、满足网络安全等级保护要求、实现全流程在线服务（核保、缴费、保全、理赔等）、做好消费者权益保护（犹豫期、退保等）。",
            evidence_docs=["10_互联网保险产品.md", "04_信息披露规则.md"],
            evidence_keywords=["互联网", "网络平台", "网络安全", "全流程在线", "消费者权益"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="互联网保险",
        ),
        EvalSample(
            id="m005",
            question="税优健康险和普通健康险在既往症处理上有什么区别？",
            ground_truth="税优健康险规定保险公司不得因既往症拒保，对于医疗费用型税优健康险不得设置免赔额。普通健康险可以针对既往症设置等待期、免责期或提高保费等条件，但需在条款中明确说明。",
            evidence_docs=["11_税优健康险.md", "05_健康保险产品开发.md"],
            evidence_keywords=["税优健康险", "既往症", "免赔额", "拒保", "等待期"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="健康保险",
        ),
        EvalSample(
            id="m006",
            question="保险公司如何同时遵守负面清单和条款费率管理办法？",
            ground_truth="保险公司开发产品时需同时满足两方面要求：条款费率管理办法要求依法审批备案、规范条款设计；负面清单明确禁止的行为（如变相销售停售产品、不合理的免责条款、误导性条款等）。两者相互补充，共同约束产品开发行为。",
            evidence_docs=["02_负面清单.md", "03_条款费率管理办法.md"],
            evidence_keywords=["负面清单", "条款费率", "审批备案", "禁止行为", "产品开发"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="综合监管",
        ),
        EvalSample(
            id="m007",
            question="年金保险在信息披露和佣金管理上有什么特殊要求？",
            ground_truth="年金保险在信息披露方面需明确说明年金领取方式、领取年龄、保证领取期限等关键信息。在佣金管理上，普通型年金保险可享受1.15倍的评估利率优惠，但需遵守附加费用率上限规定。",
            evidence_docs=["04_信息披露规则.md", "06_普通型人身保险.md"],
            evidence_keywords=["年金保险", "信息披露", "佣金", "评估利率", "附加费用率"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="年金保险",
        ),
        EvalSample(
            id="m008",
            question="两全保险的保险期间有什么限制？",
            ground_truth="两全保险属于普通型人身保险的一种，保险期间不得通过调整保单现金价值或其他条款变相缩短实际保险期间。同时需满足资本和偿付能力要求，防止通过短期两全产品规避监管。",
            evidence_docs=["13_其他险种产品.md", "06_普通型人身保险.md"],
            evidence_keywords=["两全保险", "保险期间", "现金价值", "偿付能力"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="两全保险",
        ),

        EvalSample(
            id="n001",
            question="保险公司可以销售已停售的产品吗？",
            ground_truth="保险公司不得变相销售已停售产品。不得对已停售产品进行宣传、推介或者以其他方式引导投保人购买已停售产品。违反规定的将按照负面清单要求进行监管处理。",
            evidence_docs=["02_负面清单.md"],
            evidence_keywords=["停售产品", "变相销售", "不得"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="负面清单",
        ),
        EvalSample(
            id="n002",
            question="短期健康险可以承诺保证续保吗？",
            ground_truth='短期健康保险产品不得包含保证续保条款，严禁使用"自动续保""承诺续保""终身限额"等易与长期健康保险混淆的词句。',
            evidence_docs=["08_短期健康保险.md"],
            evidence_keywords=["短期健康保险", "不得", "保证续保", "自动续保"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="短期健康保险",
        ),
        EvalSample(
            id="n003",
            question="保险条款可以使用含糊不清的免责条款吗？",
            ground_truth="保险条款中不得使用含糊不清的免责条款。责任免除条款应当使用通俗易懂的语言，在保单中以显著方式提示投保人阅读，并在投保单上作出足以引起投保人注意的提示。",
            evidence_docs=["02_负面清单.md", "04_信息披露规则.md"],
            evidence_keywords=["免责条款", "含糊不清", "不得", "显著方式"],
            question_type=QuestionType.NEGATIVE,
            difficulty="medium",
            topic="条款规范",
        ),
        EvalSample(
            id="n004",
            question="保险公司可以把佣金比例定得无限高吗？",
            ground_truth="保险公司佣金占年度保费的比例以所售产品定价时的附加费用率为上限，不能无限定高。佣金应当合理，不得通过高额佣金进行不正当竞争。",
            evidence_docs=["06_普通型人身保险.md", "14_综合监管规定.md"],
            evidence_keywords=["佣金", "附加费用率", "上限", "不得"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="佣金管理",
        ),
        EvalSample(
            id="n005",
            question="税优健康险可以因为既往症拒保吗？",
            ground_truth="税优健康险不得因被保险人既往病史拒保，这是税优健康险的重要特点之一。医疗费用型税优健康险不得设置免赔额或等待期。",
            evidence_docs=["11_税优健康险.md"],
            evidence_keywords=["税优健康险", "既往病史", "不得拒保", "免赔额"],
            question_type=QuestionType.NEGATIVE,
            difficulty="medium",
            topic="税优健康险",
        ),
        EvalSample(
            id="n006",
            question="保险公司可以不披露产品风险信息吗？",
            ground_truth="保险公司不得隐瞒产品风险信息。信息披露应当遵循真实性、准确性、完整性原则，必须向投保人充分披露保险责任、责任免除、费用扣除、退保损失等关键信息。",
            evidence_docs=["04_信息披露规则.md", "02_负面清单.md"],
            evidence_keywords=["信息披露", "不得隐瞒", "风险信息", "真实性"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="信息披露",
        ),

        EvalSample(
            id="c001",
            question="孩子在学校摔了能报不？",
            ground_truth="孩子在学校发生意外伤害属于意外伤害保险的保障范围。意外伤害是指外来的、突发的、非本意的、非疾病的客观事件导致身体受到的伤害。需要查看具体保险合同的保障范围和免责条款。",
            evidence_docs=["09_意外伤害保险.md"],
            evidence_keywords=["意外伤害", "外来", "突发", "非本意", "学校"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="c002",
            question="买完保险后悔了能退钱吗？",
            ground_truth="投保人在犹豫期内可以无条件解除保险合同，保险公司应在扣除工本费后退还全部保费。犹豫期后解除合同的，保险公司按照合同约定退还保单现金价值，可能产生较大损失。",
            evidence_docs=["01_保险法相关监管规定.md", "04_信息披露规则.md"],
            evidence_keywords=["犹豫期", "解除合同", "退保", "现金价值", "保费"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="easy",
            topic="退保",
        ),
        EvalSample(
            id="c003",
            question="这个保险能保一辈子不？",
            ground_truth='保险期间分为定期和终身两种。终身保险提供终身保障，保险期间为被保险人终身。定期保险的保险期间有限，到期后需要续保或重新投保。短期健康险不得使用"终身限额"等误导性表述。',
            evidence_docs=["01_保险法相关监管规定.md", "08_短期健康保险.md"],
            evidence_keywords=["保险期间", "终身", "定期", "保障"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="easy",
            topic="保险期间",
        ),
        EvalSample(
            id="c004",
            question="我看病花了一万块保险能全报吗？",
            ground_truth="能否全报取决于保险合同的具体约定。医疗保险通常有免赔额、赔付比例和年度赔付限额等限制。税优医疗费用型健康险不得设置免赔额，但其他医疗保险可能有免赔额和自付比例规定。",
            evidence_docs=["05_健康保险产品开发.md", "11_税优健康险.md"],
            evidence_keywords=["医疗保险", "免赔额", "赔付比例", "限额", "报销"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="医疗保险",
        ),
    ]
