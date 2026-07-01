"""Local first-pass Chinese gloss translation helpers.

This is intentionally conservative: the project does not currently have a
licensed Chinese dictionary source or an authenticated MT provider configured,
so these translations are machine-generated from JMdict English glosses and must
remain visibly sourced as a review target.
"""

from __future__ import annotations

import gzip
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TRANSLATION_SOURCE = "规则初译（JMdict，待复核）"
DICTIONARY_TRANSLATION_SOURCE = "词典转译（CC-CEDICT，待复核）"
LLM_REPAIR_QUEUE_SOURCE = "待LLM修补"

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
PAREN_RE = re.compile(r"\s*\([^)]*\)")
CEDICT_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[[^\]]+\]\s+/(.+)/$")
BASIC_CJK_ONLY_RE = re.compile(r"^[\u4e00-\u9fff·]+$")
CEDICT_DENYLIST = {
    "㛂",
    "仡",
    "偬",
    "咇",
    "拟",
    "冒",
    "迎",
}


@dataclass(frozen=True)
class TranslationResult:
    text: str
    confidence: float
    method: str
    needs_llm: bool = False


EXACT_TRANSLATIONS = {
    "(not) at all": "完全不；一点也不",
    "ability": "能力",
    "absurd": "荒唐；不合理",
    "acceptance": "接受；承认",
    "accident": "事故；意外",
    "account": "账户；说明；叙述",
    "achievement": "成就；成绩",
    "act": "行为；行动",
    "action": "行动；作用",
    "activity": "活动",
    "addition": "追加；加法",
    "administration": "管理；行政",
    "advantage": "优势；有利条件",
    "advice": "建议；忠告",
    "agreement": "协议；一致",
    "all": "全部；所有",
    "amount": "数量；金额",
    "appearance": "外观；样子；出现",
    "application": "申请；应用",
    "approval": "批准；认可",
    "area": "地区；范围；面积",
    "arrangement": "安排；整理",
    "association": "协会；关联",
    "assistance": "帮助；援助",
    "attention": "注意；关注",
    "attitude": "态度",
    "authority": "权威；权限；机关",
    "base": "基础；底部；据点",
    "basis": "基础；根据",
    "beautiful": "美丽；漂亮",
    "beginning": "开始；开头",
    "behaviour": "行为；举止",
    "benefit": "利益；好处",
    "big": "大",
    "birth": "出生；诞生",
    "bright": "明亮；聪明",
    "business": "事务；商业；业务",
    "call": "呼叫；称呼；电话",
    "calm": "平静；冷静",
    "capability": "能力；性能",
    "care": "照顾；注意",
    "case": "情况；案件；盒",
    "cause": "原因；引起",
    "center": "中心",
    "central": "中央；中心的",
    "chance": "机会；可能性",
    "change": "变化；改变",
    "character": "性格；字符；人物",
    "charge": "费用；负责；充电",
    "chief": "首席；主要",
    "choice": "选择",
    "clear": "清楚；明确",
    "close": "接近；亲密",
    "combination": "组合；结合",
    "common": "普通；常见",
    "company": "公司；陪伴",
    "competition": "竞争；比赛",
    "complaint": "抱怨；投诉",
    "condition": "条件；状态",
    "connection": "连接；关系",
    "consideration": "考虑；体谅",
    "construction": "建设；构造",
    "content": "内容",
    "control": "控制；管理",
    "convenience": "方便；便利",
    "conversation": "会话；谈话",
    "cost": "费用；成本",
    "country": "国家；乡村",
    "creation": "创造；创作",
    "current": "当前；潮流",
    "decision": "决定；决策",
    "degree": "程度；度数；学位",
    "delivery": "交付；配送",
    "description": "说明；描述",
    "design": "设计",
    "development": "发展；开发",
    "difference": "差异；不同",
    "detailed": "详细",
    "difficulty": "困难",
    "direction": "方向；指示",
    "discipline": "纪律；训练；学科",
    "discussion": "讨论",
    "disposition": "性格；倾向；处置",
    "distinction": "区别；差别",
    "duty": "义务；职责",
    "easy": "容易；简单",
    "effect": "效果；影响",
    "effort": "努力",
    "end": "结束；末端",
    "environment": "环境",
    "error": "错误",
    "establishment": "设立；建立",
    "event": "事件；活动",
    "excellent": "优秀；卓越",
    "exchange": "交换；兑换",
    "expert": "专家",
    "extremely": "非常；极其",
    "fact": "事实",
    "fall": "下降；跌落；秋天",
    "fault": "错误；缺点；责任",
    "favor": "好意；支持",
    "feeling": "感觉；心情",
    "field": "领域；田地",
    "figure": "数字；图形；人物",
    "final": "最终",
    "fine": "好；细；晴朗",
    "firm": "坚固；坚定；公司",
    "first": "第一；首先",
    "form": "形式；表格",
    "formal": "正式",
    "foundation": "基础；基金会",
    "frank": "坦率",
    "friendship": "友谊",
    "front": "前面；正面",
    "full": "满；完整",
    "function": "功能；函数",
    "gap": "间隙；差距",
    "general": "一般；总体",
    "gift": "礼物；赠品",
    "good": "好；良好",
    "grand": "宏大；盛大",
    "grave": "严重；坟墓",
    "great": "伟大；很大",
    "group": "群组；集团",
    "growth": "成长；增长",
    "half": "一半",
    "head": "头；首位；负责人",
    "height": "高度",
    "help": "帮助",
    "honest": "诚实",
    "idea": "想法；主意",
    "immediately": "立即；马上",
    "important": "重要",
    "improvement": "改善；提高",
    "influence": "影响",
    "information": "信息；资料",
    "injury": "伤害；损伤",
    "inside": "内部；里面",
    "intention": "意图；打算",
    "introduction": "介绍；引进",
    "issue": "问题；发行",
    "judgement": "判断；判决",
    "judgment": "判断；判决",
    "labor": "劳动；劳力",
    "leader": "领导者；首领",
    "left": "左；剩余",
    "level": "水平；等级",
    "life": "生活；生命",
    "light": "光；轻",
    "lineage": "血统；谱系",
    "living": "生活；生计",
    "loss": "损失；丧失",
    "management": "管理；经营",
    "manager": "经理；管理者",
    "mark": "标记；记号",
    "master": "高手；主人；掌握",
    "material": "材料；资料",
    "matter": "事情；问题；物质",
    "meaning": "意义；意思",
    "measure": "措施；测量；尺度",
    "meeting": "会议；会面",
    "method": "方法",
    "mistake": "错误",
    "model": "模型；样本",
    "mood": "心情；气氛",
    "name": "名称；名字",
    "nature": "性质；自然",
    "new": "新的",
    "note": "笔记；注释；注意",
    "notice": "通知；注意",
    "now": "现在",
    "number": "数字；数量",
    "object": "对象；物体；目的",
    "omission": "省略；遗漏",
    "one": "一个；一",
    "opening": "开口；开始；空缺",
    "operation": "操作；经营；手术",
    "opinion": "意见；看法",
    "opportunity": "机会",
    "order": "顺序；命令；订单",
    "ordinary": "普通；平常",
    "organization": "组织；机构",
    "origin": "起源；来源",
    "outline": "概要；轮廓",
    "part": "部分；零件",
    "performance": "表现；性能；演出",
    "person": "人",
    "place": "地方；场所",
    "plain": "朴素；清楚；平原",
    "plan": "计划；方案",
    "point": "点；要点；分数",
    "policy": "政策；方针",
    "poor": "贫乏；差；可怜",
    "position": "位置；立场；职位",
    "power": "力量；权力；电力",
    "practice": "实践；练习",
    "preparation": "准备",
    "problem": "问题",
    "production": "生产；制作",
    "profit": "利润；利益",
    "promotion": "促进；晋升；宣传",
    "proper": "适当；正式",
    "pure": "纯粹；纯净",
    "quality": "质量；品质",
    "quick": "迅速；快",
    "rash": "轻率；皮疹",
    "reason": "理由；原因",
    "regular": "定期；正规",
    "relation": "关系",
    "report": "报告",
    "request": "请求；要求",
    "residence": "住所；居住",
    "rest": "休息；剩余",
    "restoration": "恢复；修复",
    "return": "返回；归还；回报",
    "right": "右；正确；权利",
    "rough": "粗糙；粗略",
    "rule": "规则",
    "selection": "选择；选拔",
    "serious": "严重；认真",
    "shape": "形状；样子",
    "sign": "标志；迹象；签名",
    "simple": "简单；朴素",
    "situation": "情况；形势",
    "skill": "技能；技巧",
    "small": "小",
    "sound": "声音；健全",
    "source": "来源；源头",
    "spirit": "精神；灵魂",
    "standard": "标准",
    "start": "开始；出发",
    "state": "状态；国家；说明",
    "strange": "奇怪；陌生",
    "strong": "强；强壮",
    "style": "风格；样式",
    "summary": "摘要；概要",
    "support": "支持；支援",
    "talk": "谈话；讲话",
    "time": "时间；次数",
    "tip": "提示；尖端；小费",
    "training": "训练；培训",
    "trouble": "麻烦；故障",
    "tough": "坚韧；困难",
    "understanding": "理解",
    "unexpected": "意外",
    "union": "联合；工会",
    "unreasonable": "不合理",
    "vague": "模糊",
    "very": "非常",
    "way": "方法；道路；方面",
    "weak": "弱；虚弱",
    "work": "工作；作品",
}


PHRASE_TRANSLATIONS = {
    "ad hoc": "临时",
    "amount of": "数量",
    "at all": "完全",
    "based on": "基于",
    "bring into being": "使产生；创造",
    "by means of": "通过",
    "case of": "情况",
    "common": "普通",
    "company": "公司",
    "condition": "条件",
    "degree of": "程度",
    "e.g.": "例如",
    "especially": "尤其",
    "etc.": "等",
    "for example": "例如",
    "form of": "形式",
    "good at": "擅长",
    "in order to": "为了",
    "in relation to": "关于",
    "kind of": "一种",
    "lack of": "缺乏",
    "made of": "由……制成",
    "method of": "方法",
    "not": "不",
    "one's": "某人的",
    "part of": "部分",
    "person who": "……的人",
    "related to": "相关",
    "state of": "状态",
    "such as": "例如",
    "the act of": "行为",
    "the state of": "状态",
    "to be": "成为；是",
    "to become": "变成",
    "to do": "做；进行",
    "to get": "得到；获得",
    "to give": "给予",
    "to go": "去；前往",
    "to have": "有；拥有",
    "to make": "制作；使",
    "to put": "放置",
    "to take": "拿取；采取",
    "type of": "类型",
    "used for": "用于",
    "with respect to": "关于",
}


EXACT_TRANSLATIONS.update(
    {
        "abandon": "放弃；抛弃",
        "address": "地址；致辞；处理",
        "advance": "前进；进展；预付",
        "aid": "帮助；援助",
        "aim": "目标；目的",
        "always": "总是；一直",
        "answer": "回答；答案",
        "anxiety": "焦虑；担心",
        "appeal": "吸引力；呼吁；上诉",
        "argument": "争论；论点",
        "article": "文章；物品；冠词",
        "aspiration": "愿望；抱负；吸气",
        "average": "平均；普通",
        "azure": "蔚蓝色",
        "backing": "支持；后援",
        "balance": "平衡；余额",
        "barrier": "障碍；屏障",
        "behavior": "行为；举止",
        "best": "最好；最佳",
        "bill": "账单；票据；法案",
        "black": "黑色",
        "blue": "蓝色",
        "bluish-white": "青白色",
        "blunder": "失误；大错",
        "boss": "老板；上司",
        "boy": "男孩",
        "break": "破裂；休息；中断",
        "brown": "棕色；褐色",
        "careful": "仔细；谨慎",
        "careless": "粗心；不小心",
        "charm": "魅力；吸引力",
        "charming": "迷人；有魅力",
        "check": "检查；核对",
        "cheerful": "开朗；愉快",
        "coarse": "粗糙；粗俗",
        "cold": "寒冷；冷淡",
        "collapse": "崩塌；瓦解",
        "comfortable": "舒适",
        "companion": "同伴；伙伴",
        "complete": "完整；完成",
        "completely": "完全",
        "conclusion": "结论；结束",
        "confusion": "混乱；困惑",
        "cooperation": "合作",
        "course": "课程；路线；进程",
        "crude": "粗糙；粗鲁；原始",
        "cruel": "残酷；残忍",
        "cut": "切断；剪裁；削减",
        "dark": "黑暗；深色",
        "death": "死亡",
        "deep": "深；深刻",
        "desire": "欲望；愿望",
        "dignity": "尊严；庄重",
        "disorder": "混乱；障碍",
        "division": "分割；部门",
        "draft": "草稿；草案",
        "drawing": "图画；绘制；抽签",
        "dress": "服装；连衣裙",
        "dull": "迟钝；暗淡；无聊",
        "elegance": "优雅；雅致",
        "emergency": "紧急情况",
        "encouragement": "鼓励",
        "entirely": "完全；全部",
        "essential": "本质；必需",
        "examination": "考试；检查",
        "example": "例子",
        "extraordinary": "异常；非凡",
        "extreme": "极端；极度",
        "failure": "失败；故障",
        "favour": "好意；支持",
        "fortune": "运气；财富",
        "fresh": "新鲜；清新",
        "friend": "朋友",
        "gathering": "聚会；收集",
        "gentle": "温和；轻柔",
        "ghost": "幽灵；幻影",
        "gist": "要点；主旨",
        "gloomy": "阴郁；暗淡",
        "gray": "灰色",
        "green": "绿色",
        "grey": "灰色",
        "grief": "悲痛",
        "hard": "硬；困难；努力",
        "harmony": "和谐；协调",
        "heart": "心；内心",
        "hindrance": "妨碍；障碍",
        "history": "历史",
        "hollow": "空洞；凹陷",
        "honor": "荣誉；尊敬",
        "honour": "荣誉；尊敬",
        "inquiry": "询问；调查",
        "inspection": "检查；视察",
        "interest": "兴趣；利益；利息",
        "interval": "间隔；间距",
        "joint": "共同；接合处",
        "just": "正好；只是；公正",
        "kind": "种类；亲切",
        "labour": "劳动；劳力",
        "law": "法律；法则",
        "leading": "领先；主要",
        "letter": "信；字母",
        "limit": "限制；限度",
        "loan": "贷款；借出",
        "looks": "外貌；样子",
        "love": "爱；喜爱",
        "magnificent": "宏伟；华丽",
        "means": "手段；方法",
        "me": "我",
        "melancholy": "忧郁",
        "merit": "优点；功绩",
        "mind": "心；想法；理智",
        "misfortune": "不幸",
        "modest": "谦虚；适度",
        "moment": "瞬间；时刻",
        "naturally": "自然地；当然",
        "neighborhood": "邻近地区",
        "neighbourhood": "邻近地区",
        "normal": "正常；普通",
        "objection": "反对；异议",
        "obstacle": "障碍",
        "obvious": "明显",
        "odd": "奇怪；零散",
        "official": "正式；官方",
        "orange": "橙色；橙子",
        "outcome": "结果",
        "outside": "外部；外面",
        "pale": "苍白；淡色",
        "pallid": "苍白",
        "party": "聚会；政党；一方",
        "pattern": "模式；样式",
        "people": "人们；人民",
        "period": "期间；时期；句号",
        "pink": "粉红色",
        "pitiful": "可怜；凄惨",
        "plot": "情节；阴谋；地块",
        "post": "邮政；职位；柱",
        "present": "现在；出席；礼物",
        "presence": "存在；出席",
        "presentation": "发表；展示",
        "principal": "主要；校长；本金",
        "progress": "进步；进展",
        "protection": "保护",
        "purple": "紫色",
        "question": "问题；疑问",
        "quiet": "安静；平稳",
        "rare": "稀少；罕见",
        "rear": "后部；背面",
        "reality": "现实；实际",
        "really": "真的；确实",
        "reception": "接待；接收",
        "recovery": "恢复；康复",
        "red": "红色",
        "reduction": "减少；削减",
        "regulation": "规定；调节",
        "relative": "亲属；相对",
        "relief": "缓解；救济",
        "replacement": "替换；代替品",
        "resolution": "解决；决议；分辨率",
        "response": "回应；回答",
        "result": "结果",
        "reward": "报酬；奖励",
        "revision": "修订；修改",
        "scheme": "方案；计划",
        "scene": "场景；现场",
        "section": "部分；区段",
        "separation": "分离；分开",
        "service": "服务",
        "settlement": "解决；定居；结算",
        "severe": "严厉；严重",
        "side": "侧面；方面",
        "sincerity": "真诚",
        "solid": "坚固；固体",
        "soon": "很快；不久",
        "sorrow": "悲伤",
        "speech": "讲话；演讲；言语",
        "still": "仍然；静止",
        "study": "学习；研究",
        "stupid": "愚蠢",
        "stylish": "时髦；有格调",
        "subject": "主题；科目；主体",
        "suitable": "合适",
        "supplement": "补充；附录",
        "system": "系统；制度",
        "taste": "味道；品味",
        "tendency": "倾向；趋势",
        "thought": "想法；思考",
        "thoughtless": "欠考虑；轻率",
        "title": "标题；称号",
        "top": "顶部；最高",
        "transfer": "转移；调动",
        "transformation": "变化；转换",
        "trend": "趋势；潮流",
        "trial": "审判；试验",
        "trick": "诡计；技巧",
        "truth": "真相；真实",
        "type": "类型",
        "usual": "通常；平常",
        "variation": "变化；变体",
        "various": "各种",
        "vulgar": "粗俗；通俗",
        "waste": "浪费；废物",
        "well": "好；井",
        "white": "白色",
        "wild": "野生；狂野",
        "wish": "愿望；希望",
        "worry": "担心；烦恼",
        "yellow": "黄色",
        "you": "你；你们",
        "youth": "青年；青春",
    }
)


WORD_TRANSLATIONS = {
    "able": "能够",
    "about": "关于",
    "above": "上方",
    "accept": "接受",
    "according": "根据",
    "act": "行为",
    "add": "添加",
    "after": "之后",
    "again": "再次",
    "against": "反对；对抗",
    "age": "年龄；时代",
    "air": "空气",
    "all": "全部",
    "also": "也",
    "amount": "数量",
    "and": "和",
    "animal": "动物",
    "another": "另一个",
    "area": "地区",
    "around": "周围",
    "as": "作为",
    "ask": "询问；请求",
    "at": "在",
    "back": "后面；返回",
    "bad": "坏；差",
    "be": "是；成为",
    "because": "因为",
    "become": "成为",
    "before": "之前",
    "being": "存在；人",
    "between": "之间",
    "body": "身体",
    "book": "书",
    "bring": "带来",
    "business": "业务",
    "by": "由；通过",
    "call": "称呼；呼叫",
    "can": "能够",
    "cause": "原因；导致",
    "change": "变化",
    "child": "孩子",
    "city": "城市",
    "come": "来",
    "condition": "状态",
    "container": "容器",
    "day": "日；天",
    "do": "做",
    "down": "下",
    "each": "各自",
    "end": "结束",
    "even": "甚至",
    "event": "事件",
    "face": "脸；表面",
    "family": "家庭",
    "feel": "感觉",
    "feeling": "感觉",
    "female": "女性",
    "few": "少数",
    "field": "领域",
    "first": "第一",
    "food": "食物",
    "for": "为了；给",
    "from": "从",
    "get": "得到",
    "give": "给予",
    "go": "去",
    "good": "好",
    "great": "大；伟大",
    "group": "群体",
    "hand": "手",
    "have": "有",
    "high": "高",
    "hold": "持有；拿着",
    "house": "房屋",
    "human": "人类",
    "in": "在……中",
    "include": "包括",
    "inside": "内部",
    "into": "进入",
    "it": "它",
    "japanese": "日本的；日语",
    "keep": "保持",
    "large": "大",
    "leave": "离开；留下",
    "like": "像；喜欢",
    "little": "小；少量",
    "long": "长",
    "look": "看；样子",
    "make": "制作；使",
    "male": "男性",
    "many": "许多",
    "matter": "事情",
    "mean": "意思是",
    "money": "金钱",
    "more": "更多",
    "move": "移动",
    "much": "很多",
    "name": "名称",
    "new": "新的",
    "no": "没有；不",
    "not": "不",
    "of": "的",
    "off": "离开；关闭",
    "old": "旧；老",
    "on": "在……上",
    "one": "一个",
    "only": "仅",
    "or": "或",
    "other": "其他",
    "out": "外出；外部",
    "over": "超过；上方",
    "own": "自己的",
    "part": "部分",
    "person": "人",
    "place": "地方",
    "plant": "植物",
    "point": "点",
    "put": "放置",
    "rather": "相当",
    "receive": "收到",
    "relating": "相关",
    "same": "相同",
    "say": "说",
    "see": "看见",
    "send": "发送",
    "set": "设置；组",
    "small": "小",
    "something": "某物",
    "state": "状态",
    "take": "拿取；采取",
    "thing": "东西；事情",
    "time": "时间",
    "to": "去；向",
    "together": "一起",
    "up": "上",
    "use": "使用",
    "used": "使用的",
    "very": "非常",
    "way": "方式",
    "when": "当……时",
    "where": "在哪里",
    "which": "哪一个",
    "with": "与；带有",
    "without": "没有",
    "woman": "女人",
    "word": "词；话",
    "work": "工作",
    "year": "年",
}


EXACT_TRANSLATIONS.update(
    {
        "absolutely": "绝对；完全",
        "acquaintance": "熟人；相识",
        "active": "积极；活跃",
        "affection": "感情；喜爱",
        "alteration": "变更；改变",
        "announcement": "通知；公告",
        "anticipation": "预期；期待",
        "appropriate": "适当；合适",
        "ardent": "热情；热烈",
        "art": "艺术；技艺",
        "assignment": "分配；任务",
        "assumption": "假定；设想",
        "at once": "立刻；马上",
        "audience": "听众；观众",
        "background": "背景",
        "battle": "战斗；斗争",
        "belief": "信念；相信",
        "bond": "联系；纽带；债券",
        "brazen": "厚颜无耻；蛮横",
        "cancellation": "取消；撤销",
        "certainly": "确实；一定",
        "chairman": "主席；会长",
        "circle": "圆；圈子",
        "circumstances": "情况；环境",
        "clean": "干净；清洁",
        "clue": "线索",
        "collaboration": "合作；协作",
        "commission": "委托；委员会；佣金",
        "communication": "交流；通信",
        "community": "共同体；社区",
        "completion": "完成；结束",
        "composition": "构成；作文；作品",
        "concern": "关心；担忧；相关事项",
        "consent": "同意；许可",
        "considerate": "体贴；周到",
        "consultation": "咨询；商议",
        "contest": "比赛；竞争",
        "continuation": "继续；延续",
        "contribution": "贡献；投稿；捐款",
        "convention": "惯例；会议；公约",
        "coordination": "协调；配合",
        "cordial": "热诚；亲切",
        "core": "核心；中心",
        "correction": "修正；订正",
        "cultivation": "栽培；培养；修养",
        "custom": "习惯；风俗",
        "damage": "损害；损伤",
        "danger": "危险",
        "dangerous": "危险",
        "dealing with": "处理；应对",
        "declaration": "声明；宣言",
        "decline": "下降；衰退；谢绝",
        "defect": "缺点；缺陷",
        "defence": "防御；辩护",
        "defense": "防御；辩护",
        "demonstration": "示范；演示；示威",
        "destruction": "破坏；毁灭",
        "determination": "决心；决定",
        "device": "装置；设备；办法",
        "difficult": "困难",
        "director": "负责人；导演；董事",
        "dispute": "争论；纠纷",
        "display": "展示；显示",
        "district": "地区；区域",
        "doctor": "医生；博士",
        "document": "文件；文书",
        "donation": "捐赠；捐款",
        "doubt": "怀疑；疑问",
        "dubious": "可疑；不确定",
        "earnest": "认真；诚恳",
        "easily": "容易地",
        "edge": "边缘；优势",
        "energy": "能量；精力",
        "enormous": "巨大；庞大",
        "enthusiasm": "热情",
        "entry": "条目；进入；报名",
        "enquiry": "询问；调查",
        "escape": "逃脱；逃避",
        "estimation": "估计；评价",
        "everything": "一切；全部",
        "exactly": "正好；确切地",
        "exceptional": "例外；异常；优秀",
        "excitement": "兴奋；刺激",
        "excuse": "借口；理由",
        "exhibition": "展览；展示",
        "expansion": "扩大；扩张",
        "expectation": "期待；预期",
        "experience": "经验；经历；体验",
        "extension": "延长；扩展",
        "extent": "程度；范围",
        "extravagant": "奢侈；过度",
        "facing imminent danger": "面临迫近的危险",
        "fight": "战斗；争吵",
        "flavor": "味道；风味",
        "flavour": "味道；风味",
        "force": "力量；强制",
        "formation": "形成；编成",
        "game": "游戏；比赛",
        "generally": "一般；通常",
        "giving up": "放弃",
        "greatly": "大大地；非常",
        "hazardous": "危险",
        "healthy": "健康",
        "heavy": "重；沉重；严重",
        "hope": "希望",
        "hot": "热；烫；热门",
        "how": "如何；怎样",
        "huge": "巨大",
        "bring forth": "产生；生出",
        "having no way to express": "无法表达",
        "hectic": "忙乱；匆忙",
        "hurried": "匆忙；仓促",
        "immoderate": "过度；无节制",
        "impassioned": "热情；激昂",
        "impudent": "厚颜无耻；无礼",
        "in danger": "处于危险中",
        "in jeopardy": "处于危险中",
        "increase": "增加；增长",
        "indefinite": "不确定",
        "individual": "个人；个别",
        "inevitable": "不可避免",
        "inferior": "劣等；较差",
        "innocence": "无辜；天真",
        "insipid": "无味；乏味",
        "integration": "整合；一体化",
        "interior": "内部；内侧",
        "invitation": "邀请",
        "invent": "发明；创造",
        "item": "项目；条目；物品",
        "jeopardy": "危险",
        "joining": "加入；连接",
        "learning": "学习；学问",
        "line": "线；行；路线",
        "location": "位置；场所",
        "loud": "响亮；大声",
        "maintenance": "维护；保养；维持",
        "manage to find": "设法找到",
        "mechanism": "机制；装置",
        "medicine": "药；医学",
        "middle": "中间；中央",
        "mild": "温和；轻微",
        "motion": "运动；动作",
        "movement": "运动；移动；活动",
        "natural": "自然",
        "noise": "噪音；响声",
        "notification": "通知",
        "novel": "新奇；新颖；小说",
        "occasion": "场合；机会",
        "oneself": "自己",
        "opposite": "相反；对面",
        "original": "原本；独创",
        "pace": "步调；速度",
        "passionate": "热情；激烈",
        "payment": "支付；付款",
        "peace": "和平；平静",
        "penalty": "惩罚；罚金",
        "perfect": "完美；完全",
        "perilous": "危险",
        "personal": "个人；私人的",
        "personality": "性格；人格",
        "picture": "图画；照片；画面",
        "point of view": "观点；角度",
        "popular": "受欢迎；大众的",
        "powerful": "强大；有力",
        "precious": "珍贵",
        "precarious": "危险；不稳定",
        "prediction": "预测；预言",
        "pressing": "紧急；迫切",
        "previously": "以前；先前",
        "principle": "原则；原理",
        "private": "私人的；私下的",
        "professional": "专业；职业",
        "program": "节目；计划；程序",
        "programme": "节目；计划",
        "proposal": "提案；建议",
        "provision": "提供；规定；准备",
        "public": "公共；公开",
        "publication": "出版；发表",
        "punishment": "惩罚",
        "purpose": "目的；用途",
        "questionable": "可疑；有问题",
        "quickly": "迅速；很快",
        "reasonable": "合理",
        "recently": "最近",
        "record": "记录；成绩",
        "region": "地区；区域",
        "regret": "后悔；遗憾",
        "rehabilitation": "康复；恢复",
        "rejection": "拒绝；驳回",
        "repair": "修理；修复",
        "reply": "回复；回答",
        "repayment": "偿还；还款",
        "resignation": "辞职；放弃",
        "restraint": "抑制；约束",
        "reverse": "相反；反面；倒转",
        "rapid": "迅速；快速",
        "ridiculous": "荒唐；可笑",
        "right away": "立刻；马上",
        "risky": "有风险；危险",
        "room": "房间；空间",
        "root": "根；根源",
        "rough-mannered": "粗鲁",
        "route": "路线；途径",
        "rude": "粗鲁；无礼",
        "sales": "销售；营业额",
        "schedule": "日程；计划",
        "scholarship": "奖学金；学问",
        "scrape together": "勉强凑集",
        "security": "安全；保障",
        "senior": "年长；上级；高级",
        "sense": "感觉；意义；判断力",
        "sentence": "句子；判决",
        "shallow": "浅；肤浅",
        "shameless": "无耻；厚颜",
        "shop": "商店",
        "sight": "视野；景象；视力",
        "skillful": "熟练；巧妙",
        "slight": "轻微；少量",
        "slow": "慢；缓慢",
        "society": "社会",
        "space": "空间；空地",
        "special": "特别；特殊",
        "square": "正方形；广场；平方",
        "statement": "声明；陈述",
        "step": "步骤；步伐",
        "store": "商店；储存",
        "street": "街道",
        "stress": "压力；强调",
        "structure": "结构",
        "sudden": "突然",
        "suddenly": "突然",
        "sugary": "甜；含糖",
        "suggestion": "建议；暗示",
        "sultry": "闷热",
        "superficial": "表面；肤浅",
        "sufficient": "足够；充分",
        "surplus": "剩余；过剩",
        "suspension": "暂停；悬挂；停职",
        "suspicious": "可疑；怀疑",
        "sweet": "甜；温柔；悦耳",
        "sweet-tasting": "甜味",
        "sympathy": "同情；共感",
        "teacher": "教师；老师",
        "technique": "技术；技巧",
        "terrible": "可怕；严重；糟糕",
        "thick": "厚；浓；密",
        "to approach": "接近；靠近",
        "to bear": "承受；承担；生育",
        "to bring forth": "产生；生出",
        "to carry out": "实行；执行",
        "to collect": "收集；征收",
        "to create": "创造；创作",
        "to devise": "设计；想出",
        "to die": "死；死亡",
        "to follow": "跟随；遵循",
        "to gather": "聚集；收集",
        "to hang": "挂；悬挂",
        "to invent": "发明；创造",
        "to manage": "管理；设法完成",
        "to manage to find": "设法找到",
        "to produce": "生产；产生",
        "to raise": "举起；提高；养育",
        "to rise": "上升；起来",
        "to sense": "感觉到；察觉",
        "to shake": "摇动；震动",
        "to shine": "发光；照耀",
        "to show": "显示；展示",
        "to scrape together": "勉强凑集",
        "to spread": "扩散；展开",
        "to start knitting": "开始编织",
        "to stop": "停止；阻止",
        "to tell": "告诉；讲述",
        "to think out": "想出；仔细考虑出",
        "to think up": "想出；构思出",
        "to think up and bring into being": "构思并创造；想出并使之成形",
        "to turn over": "翻转；移交",
        "to work out": "想出；制定；解决",
        "trade": "贸易；交易",
        "treatment": "处理；治疗；待遇",
        "truly": "真正；确实",
        "tune": "曲调；调子；调谐",
        "unavoidable": "不可避免",
        "unusual": "异常；不寻常",
        "unsure": "不确定；没把握",
        "value": "价值；数值",
        "view": "看法；视野；景色",
        "violent": "暴力；激烈；猛烈",
        "vision": "视力；远见；构想",
        "volume": "体积；音量；卷",
        "warm": "温暖；热情",
        "warning": "警告；提醒",
        "weather": "天气",
        "wearisome": "令人厌烦；乏味",
        "well-lit": "明亮",
        "wonderful": "极好；精彩",
        "admirable": "令人钦佩；出色",
        "bad": "坏；不好；差",
        "brave": "勇敢；英勇",
        "busy": "忙；忙碌",
        "communist": "共产主义",
        "crimson": "深红；绯红",
        "doubtful": "可疑；不确定",
        "fragrant": "芳香；芬芳",
        "gallant": "英勇；勇敢",
        "graceful": "优雅；从容",
        "gracious": "宽厚；得体",
        "grateful": "感激；感谢",
        "honourable": "光荣；体面",
        "impossible": "不可能",
        "indescribable": "无法形容",
        "naughty": "淘气；顽皮",
        "occupied": "被占用；有人使用",
        "out of the question": "不可能；不容考虑",
        "restless": "不安；坐立不安",
        "scarlet": "鲜红；猩红",
        "stirring": "激动人心；振奋",
        "thankful": "感谢；感激",
        "unbelievable": "难以置信",
        "unthinkable": "不可想象",
        "valiant": "英勇；勇敢",
        "vigorous": "有力；精力充沛",
        "welcome": "受欢迎；可喜",
        "wrong": "错误；不对",
        "enough": "足够",
        "goes without saying": "不言而喻",
        "must not": "不可以；禁止",
        "needless to say": "不用说；不必说",
        "should not": "不应该",
        "(not) in the least": "一点也不",
        "a variety of": "各种；多种",
        "abandonment": "放弃；遗弃",
        "absence": "缺席；不存在",
        "absolute truth": "绝对真理",
        "admiration": "钦佩；赞赏",
        "admission": "承认；准入；入场",
        "aggravation": "恶化；加重",
        "all right": "没问题；可以",
        "arousal": "唤醒；激发",
        "as hard as one can": "尽全力",
        "as yet": "尚未；还没有",
        "attendance": "出席；到场",
        "bath": "浴室；洗澡",
        "batting": "击球",
        "beating": "击打；打败",
        "bewilderment": "困惑；迷惑",
        "boredom": "无聊；厌倦",
        "buddhist priest": "僧侣；和尚",
        "buying": "购买",
        "bygone days": "往日；过去",
        "cannot be helped": "没办法；无可奈何",
        "carrying": "搬运；携带",
        "carrying out": "实行；执行",
        "caution": "注意；警告",
        "centimetre": "厘米",
        "chic": "别致；时髦",
        "cleaning": "清扫；清洁",
        "close contest": "势均力敌的比赛",
        "closing": "关闭；结束",
        "coldness": "寒冷；冷淡",
        "collecting": "收集；征收",
        "colouring": "着色；色彩",
        "comeback": "复出；恢复",
        "coming and going": "来来往往",
        "company employee": "公司职员",
        "composure": "镇静；沉着",
        "computation": "计算",
        "confronting": "面对；对抗",
        "continuance": "继续；延续",
        "copying": "复制；抄写",
        "co-op": "合作社；合作",
        "craft": "手艺；工艺",
        "crumbling": "崩塌；碎裂",
        "curriculum": "课程",
        "curtailment": "缩短；削减",
        "decisive action": "果断行动",
        "decisively": "果断地；决定性地",
        "declining": "下降；衰退",
        "deferment": "延期；推迟",
        "deluxe": "豪华；高级",
        "denial": "否认；拒绝",
        "descent": "下降；血统",
        "desertion": "遗弃；逃跑",
        "discontinuance": "中止；停止",
        "discovery": "发现",
        "dissatisfaction": "不满",
        "drawing up": "起草；制定",
        "eagerness": "热心；渴望",
        "eradication": "根除；消灭",
        "exhibiting": "展示；展出",
        "extermination": "消灭；灭绝",
        "facility": "设施；能力",
        "farewell": "告别；送别",
        "favourite": "最喜欢；偏爱",
        "feeling sick": "恶心；身体不适",
        "field trip": "实地考察；校外学习",
        "fine weather": "晴天；好天气",
        "firing": "解雇；发射；烧制",
        "founding": "创立；建立",
        "front and back": "前后；正反",
        "general public": "大众；公众",
        "good offices": "斡旋；调解",
        "grown-up": "成熟；成人",
        "grumbling": "抱怨；牢骚",
        "handicap": "不利条件；障碍",
        "handing over": "交付；移交",
        "having": "拥有；具有",
        "he": "他",
        "here and there": "到处；各处",
        "high school": "高中",
        "holding": "持有；保持",
        "in what way": "以什么方式；怎样",
        "inconsistency": "不一致；矛盾",
        "innumerable": "无数；不可胜数",
        "irregularity": "不规则；异常",
        "isolation": "隔离；孤立",
        "just as one thought": "果然；正如所想",
        "keenly": "强烈地；敏锐地",
        "large number": "大量；许多",
        "leaving": "离开；留下",
        "licence": "许可；执照",
        "like a man": "像男人一样；有男子气概",
        "mainly": "主要",
        "manly": "有男子气概；阳刚",
        "masculine": "男性的；阳刚",
        "materialization": "实现；具体化",
        "materials": "材料；资料",
        "mature": "成熟",
        "mending": "修补；修理",
        "misappropriation": "挪用；侵占",
        "monitoring": "监视；监测",
        "mutual aid": "互助",
        "nervously": "紧张地",
        "night duty": "夜班；值夜",
        "offence": "冒犯；违法行为",
        "one line": "一行；一条线",
        "one portion": "一份；一部分",
        "one round": "一圈；一轮",
        "one's home": "自己家；家里",
        "opposite side": "对面；相反一侧",
        "opposition": "反对；对立",
        "organisation": "组织；机构",
        "other party": "对方；另一方",
        "other side": "另一边；对方",
        "participation": "参加；参与",
        "permanence": "永久；持久",
        "perpetuity": "永久；永恒",
        "personal history": "履历；个人经历",
        "postponement": "延期；推迟",
        "preferable": "更好；更可取",
        "primarily": "主要；首先",
        "procurement": "采购；取得",
        "prosecution": "起诉；追诉",
        "pursuit": "追求；追赶",
        "raising": "提高；养育；筹集",
        "readiness": "准备就绪；愿意",
        "receiving": "接收；领取",
        "rearing": "养育；培育",
        "reconciliation": "和解；调和",
        "reconsideration": "重新考虑",
        "recuperation": "恢复；休养",
        "reliance": "依赖；信赖",
        "relocation": "迁移；搬迁",
        "remembrance": "记忆；纪念",
        "remodeling": "改造；翻新",
        "remodelling": "改造；翻新",
        "renewal": "更新；续订",
        "reorganisation": "重组；改组",
        "reorganization": "重组；改组",
        "restlessly": "不安地",
        "resuscitation": "复苏；抢救",
        "retirement": "退休；退职",
        "reverberation": "回响；反响",
        "rivalry": "竞争；对抗",
        "rumour": "传闻；谣言",
        "scattering": "散布；分散",
        "scoring": "得分；评分",
        "seizure": "扣押；夺取；发作",
        "selling": "销售；出售",
        "senior citizen": "老年人",
        "setting up": "设立；设置",
        "sharing": "分享；分担",
        "sharp rise": "急剧上升",
        "shooting": "射击；拍摄",
        "shortstop": "游击手",
        "showing": "显示；展示",
        "shaking": "摇动；震动",
        "singing": "唱歌；歌唱",
        "sinking": "下沉；沉没",
        "skilful": "熟练；巧妙",
        "some time ago": "前些时候；不久前",
        "sorting": "分类；整理",
        "speeding up": "加速",
        "stepping down": "辞职；退下",
        "stiffening": "变硬；僵硬",
        "still more": "更加；甚至更多",
        "stupidity": "愚蠢",
        "substantiation": "证实；具体化",
        "supposition": "假定；推测",
        "surprisingly": "惊人地；出乎意料地",
        "sweets": "甜食；点心",
        "swinging": "摇摆；挥动",
        "that sort of": "那种；那类",
        "theatre": "剧场；戏剧",
        "there's no (other) way": "没有别的办法；无可奈何",
        "thickheaded": "迟钝；愚笨",
        "think out": "想出；仔细考虑出",
        "think up": "想出；构思出",
        "threat": "威胁",
        "tiresome": "令人厌烦；麻烦",
        "to begin with": "首先；原本",
        "to be broken": "坏掉；破损",
        "to be crowded": "拥挤",
        "to be dejected": "沮丧；泄气",
        "to be different": "不同；有差异",
        "to be incorrect": "不正确",
        "to be smashed": "被打碎；粉碎",
        "to be wrong": "错误；不对",
        "to become weak": "变弱",
        "to go past": "经过；过去",
        "to go under": "沉没；失败",
        "to heap up": "堆积",
        "to result from": "起因于；由……造成",
        "to sympathise with": "同情；赞同",
        "to take lessons in": "学习；上课",
        "to the best of one's ability": "尽力",
        "unconditionally": "无条件地",
        "unskillful": "不熟练；笨拙",
        "venture": "冒险；风险企业",
        "vigour": "活力；精力",
        "watching": "观看；监视",
        "worst": "最坏；最差",
    }
)


CONTEXT_EXACT_TRANSLATIONS = {
    "一类形容词": {
        "bad": "坏；不好；差",
        "bright": "明亮；开朗；聪明",
        "communist": "共产主义",
        "deep": "深；深厚",
        "fine": "好；优良；晴朗",
        "good": "好；良好；合适",
        "heavy": "重；沉重；严重",
        "kind": "亲切；和善",
        "light": "明亮；浅色；轻",
        "novel": "新颖；新奇",
        "proper": "适当；合乎规矩",
        "quiet": "安静；平静",
        "rough": "粗糙；粗暴；粗略",
        "sound": "健全；可靠",
        "wild": "狂野；粗暴；野生",
    },
    "二类形容词": {
        "bright": "明亮；开朗；聪明",
        "fine": "好；优良；晴朗",
        "good": "好；良好；合适",
        "kind": "亲切；和善",
        "light": "明亮；浅色；轻",
        "proper": "适当；合乎规矩",
        "quiet": "安静；平静",
    },
}


def unique(seq: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in seq:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_key(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def strip_parenthetical(text: str) -> str:
    return PAREN_RE.sub("", text).strip()


def normalize_cedict_definition(text: str) -> str:
    text = strip_parenthetical(text)
    text = text.replace("sb", "somebody").replace("sth", "something")
    text = re.sub(r"\bfig\.\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\blit\.\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCL:.*", "", text)
    text = text.strip(" .;:,")
    return normalize_key(text)


def useful_cedict_candidate(text: str) -> bool:
    if not text or text in CEDICT_DENYLIST:
        return False
    if len(text) < 2:
        return False
    if any(part in CEDICT_DENYLIST for part in text):
        return False
    return bool(BASIC_CJK_ONLY_RE.match(text))


class CedictIndex:
    """Tiny English-definition -> simplified Chinese reverse index."""

    def __init__(self, by_definition: dict[str, list[str]]) -> None:
        self.by_definition = by_definition

    @classmethod
    def from_gzip(cls, path: Path) -> "CedictIndex":
        raw_index: dict[str, list[str]] = defaultdict(list)
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = CEDICT_LINE_RE.match(line)
                if not match:
                    continue
                _traditional, simplified, definitions = match.groups()
                if len(simplified) > 8 or not useful_cedict_candidate(simplified):
                    continue
                for definition in definitions.split("/"):
                    definition = definition.strip()
                    if not definition:
                        continue
                    if re.match(
                        r"^(abbr\.|also written|archaic|classifier|erhua|old variant|surname|variant of|see |see also)",
                        definition,
                        flags=re.IGNORECASE,
                    ):
                        continue
                    chunks = re.split(r"\s*;\s*|\s*,\s*(?=to |a |an |the |one |someone |something |[a-z-]+$)", definition)
                    for chunk in chunks:
                        key = normalize_cedict_definition(chunk)
                        if not key or has_cjk(key):
                            continue
                        if len(key.split()) > 5:
                            continue
                        raw_index[key].append(simplified)
                        if key.startswith("to "):
                            raw_index[key[3:]].append(simplified)
        by_definition = {key: unique(values)[:5] for key, values in raw_index.items()}
        return cls(by_definition)

    def lookup(self, text: str, limit: int = 3) -> list[str]:
        keys = unique(
            [
                normalize_key(text),
                normalize_key(strip_parenthetical(text)),
                normalize_cedict_definition(text),
            ]
        )
        candidates: list[str] = []
        for key in keys:
            if not key:
                continue
            candidates.extend(self.by_definition.get(key, []))
            if key.startswith("to "):
                candidates.extend(self.by_definition.get(key[3:], []))
        return [item for item in unique(candidates) if useful_cedict_candidate(item)][:limit]


def load_cedict_index(path: Path | None) -> CedictIndex | None:
    if not path or not path.exists():
        return None
    return CedictIndex.from_gzip(path)


def context_exact_translation(key: str, major_pos: str) -> str:
    return CONTEXT_EXACT_TRANSLATIONS.get(major_pos, {}).get(key, "")


def phrase_replace(text: str) -> str:
    out = text
    for source, target in sorted(PHRASE_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        out = re.sub(rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])", target, out, flags=re.IGNORECASE)
    return out


def word_replace(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return WORD_TRANSLATIONS.get(token.lower(), token)

    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", repl, text)


def cleanup_machine_text(text: str) -> str:
    text = text.replace("；；", "；")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ,", "，").replace(", ", "，")
    text = text.replace(" :", "：").replace(": ", "：")
    text = text.replace(" ;", "；").replace("; ", "；")
    return text


def latin_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z-]*(?:'[A-Za-z]+)?", text)
        if token.lower() not in {"e", "g", "eg", "etc"}
    ]


def adjust_for_pos(text: str, major_pos: str = "") -> str:
    if major_pos not in {"一类形容词", "二类形容词"}:
        return text
    adjusted = []
    for part in re.split(r"([；、])", text):
        if part in {"；", "、"}:
            adjusted.append(part)
            continue
        value = part.strip()
        if not value or value.startswith(("待译", "专名/原文")):
            adjusted.append(part)
            continue
        if value.endswith(("的", "地", "性")):
            adjusted.append(value)
            continue
        if len(value) <= 8 and not re.search(r"[：/]", value):
            adjusted.append(f"{value}的")
        else:
            adjusted.append(value)
    return "".join(adjusted)


def result(text: str, confidence: float, method: str, major_pos: str = "", needs_llm: bool = False) -> TranslationResult:
    text = cleanup_machine_text(text).replace("；；", "；").strip("；、 ")
    return TranslationResult(adjust_for_pos(text, major_pos), confidence, method, needs_llm)


def translate_template(key: str, major_pos: str = "", cedict: CedictIndex | None = None) -> TranslationResult | None:
    template_specs = [
        (r"^the act of (.+)$", "{inner}的行为", 0.72, "template-act"),
        (r"^act of (.+)$", "{inner}的行为", 0.72, "template-act"),
        (r"^the state of (.+)$", "{inner}的状态", 0.72, "template-state"),
        (r"^state of (.+)$", "{inner}的状态", 0.72, "template-state"),
        (r"^method of (.+)$", "{inner}的方法", 0.70, "template-method"),
        (r"^way of (.+)$", "{inner}的方法", 0.68, "template-method"),
        (r"^person who (.+)$", "{inner}的人", 0.62, "template-person"),
        (r"^one who (.+)$", "{inner}的人", 0.62, "template-person"),
        (r"^someone who (.+)$", "{inner}的人", 0.62, "template-person"),
        (r"^used for (.+)$", "用于{inner}", 0.70, "template-used-for"),
        (r"^used to (.+)$", "用于{inner}", 0.68, "template-used-to"),
        (r"^without (.+)$", "没有{inner}", 0.64, "template-without"),
        (r"^not (.+)$", "不{inner}", 0.62, "template-not"),
    ]
    for pattern, template, confidence, method in template_specs:
        match = re.match(pattern, key)
        if not match:
            continue
        inner = translate_gloss_detailed(match.group(1), cedict=cedict)
        if inner.confidence < 0.45 or not has_cjk(inner.text):
            return None
        return result(template.format(inner=inner.text), min(confidence, inner.confidence), method, major_pos, inner.needs_llm)

    if key.startswith("to "):
        inner = translate_gloss_detailed(key[3:], cedict=cedict)
        if inner.confidence >= 0.55 and has_cjk(inner.text):
            return result(inner.text, min(0.76, inner.confidence), "template-to", major_pos, inner.needs_llm)

    return None


def translate_gloss_detailed(
    gloss: str,
    major_pos: str = "",
    subpos: str = "",
    cedict: CedictIndex | None = None,
) -> TranslationResult:
    original = gloss.strip()
    if not original:
        return TranslationResult("", 0.0, "empty", False)

    key = normalize_key(original)
    context_value = context_exact_translation(key, major_pos)
    if context_value:
        return result(context_value, 0.98, "context-exact", major_pos)

    if key in EXACT_TRANSLATIONS:
        return result(EXACT_TRANSLATIONS[key], 0.98, "exact", major_pos)

    no_parenthetical = normalize_key(strip_parenthetical(original))
    context_value = context_exact_translation(no_parenthetical, major_pos)
    if context_value:
        return result(context_value, 0.94, "context-exact-no-parenthetical", major_pos)

    if no_parenthetical in EXACT_TRANSLATIONS:
        return result(EXACT_TRANSLATIONS[no_parenthetical], 0.94, "exact-no-parenthetical", major_pos)

    if key.startswith("to "):
        verb_key = key[3:]
        if verb_key in EXACT_TRANSLATIONS:
            return result(EXACT_TRANSLATIONS[verb_key], 0.90, "exact-verb-core", major_pos)

    if cedict:
        candidates = cedict.lookup(original)
        if candidates:
            confidence = 0.68 if len(candidates) <= 2 else 0.62
            return result(
                "；".join(candidates[:2]),
                confidence,
                "cc-cedict",
                major_pos,
                needs_llm=False,
            )

    templated = translate_template(key, major_pos=major_pos, cedict=cedict)
    if templated:
        return templated

    rough = phrase_replace(original)
    rough = word_replace(rough)
    rough = cleanup_machine_text(rough)

    if has_cjk(rough):
        remaining = latin_tokens(rough)
        if not remaining:
            return result(rough, 0.72, "phrase-word", major_pos)
        if len(remaining) <= 1:
            return TranslationResult("待译", 0.30, "phrase-word-partial", True)
        return TranslationResult("待译", 0.20, "phrase-word-low", True)

    if original[:1].isupper() and len(original.split()) <= 4:
        return TranslationResult(f"专名/原文：{original}", 0.40, "proper-original", True)
    return TranslationResult("待译", 0.10, "untranslated", True)


def translate_gloss(gloss: str, major_pos: str = "", subpos: str = "", cedict: CedictIndex | None = None) -> str:
    return translate_gloss_detailed(gloss, major_pos=major_pos, subpos=subpos, cedict=cedict).text


def translate_glosses_detailed(
    glosses: Iterable[str],
    limit: int = 5,
    major_pos: str = "",
    subpos: str = "",
    cedict: CedictIndex | None = None,
) -> list[TranslationResult]:
    results = [
        translate_gloss_detailed(gloss, major_pos=major_pos, subpos=subpos, cedict=cedict)
        for gloss in glosses
        if gloss
    ]
    unique_results: list[TranslationResult] = []
    seen = set()
    for item in results:
        normalized = item.text.replace("；", "、")
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_results.append(TranslationResult(normalized, item.confidence, item.method, item.needs_llm))
    return unique_results[:limit]


def translate_glosses(
    glosses: Iterable[str],
    limit: int = 5,
    major_pos: str = "",
    subpos: str = "",
    cedict: CedictIndex | None = None,
) -> list[str]:
    return [item.text for item in translate_glosses_detailed(glosses, limit, major_pos, subpos, cedict)]
