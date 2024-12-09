from dataclasses import dataclass
from typing import List, Dict
from enum import Enum, auto

@dataclass
class Group:
    name: str
    wxid: str = None

@dataclass
class ForwardList:
    list_id: int
    list_name: str
    groups: List[Dict[str, str]]

class NCCState(Enum):
    IDLE = auto()           # 空闲状态
    WAITING_MESSAGE = auto() # 等待收集转发消息
    WAITING_CHOICE = auto()  # 等待选择转发列表 