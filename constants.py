from enum import IntEnum, unique
from enum import Enum

@unique
class ChatType(IntEnum):
    UnKnown = 0  # 未知, 即未设置
    TIGER_BOT = 1  # TigerBot
    CHATGPT = 2  # ChatGPT
    XINGHUO_WEB = 3  # 讯飞星火
    CHATGLM = 4  # ChatGLM
    BardAssistant = 5  # Google Bard
    ZhiPu = 6  # ZhiPu
    FASTGPT = 7  # FastGPT

    @staticmethod
    def is_in_chat_types(chat_type: int) -> bool:
        if chat_type in [ChatType.TIGER_BOT.value, ChatType.CHATGPT.value,
                         ChatType.XINGHUO_WEB.value, ChatType.CHATGLM.value,
                         ChatType.BardAssistant.value, ChatType.ZhiPu.value,
                         ChatType.FASTGPT.value]:
            return True
        return False

    @staticmethod
    def help_hint() -> str:
        return str({member.value: member.name for member in ChatType}).replace('{', '').replace('}', '')
    


# 好友请求自动通过相关常量
MIN_ACCEPT_DELAY = 30  # 最小延迟时间(秒)
MAX_ACCEPT_DELAY = 90  # 最大延迟时间(秒)
FRIEND_WELCOME_MSG = "hey，我是肥肉，是ncc的团宠，欢迎加入ncc大家庭，后续我会在这里接入入群功能，请期待。\n我的知识库现在还在更新中，相当于3个月时候的肥肉，请期待。"