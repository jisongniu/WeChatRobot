import logging
import requests
from typing import Optional
from wcferry import Wcf

logger = logging.getLogger("FeishuBot")

class FeishuBot:
    """飞书机器人服务"""
    def __init__(self, webhook_url: str, wcf: Wcf, notion_manager=None, ncc_manager=None):
        """初始化飞书机器人
        
        Args:
            webhook_url: 飞书机器人的webhook地址
            wcf: Wcf实例，用于获取微信相关信息
            notion_manager: NotionManager实例，用于检查管理员权限
            ncc_manager: NCCManager实例，用于检查转发状态
        """
        self.webhook_url = webhook_url
        self.wcf = wcf
        self.notion_manager = notion_manager
        self.ncc_manager = ncc_manager
        
    def send_message(self, content: str) -> bool:
        """发送消息到飞书
        
        Args:
            content: 消息内容
            
        Returns:
            bool: 是否发送成功
        """
        try:
            data = {
                "msg_type": "text",
                "content": {
                    "text": content
                }
            }
            response = requests.post(self.webhook_url, json=data)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logger.info(f"飞书消息发送成功: {content}")
                    return True
                else:
                    logger.error(f"飞书消息发送失败: {result}")
            else:
                logger.error(f"飞书消息发送失败，状态码: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"飞书消息发送异常: {e}")
            return False

    def should_notify(self, sender_wxid: str) -> bool:
        """判断是否应该发送飞书通知
        
        Args:
            sender_wxid: 发送者的wxid
            
        Returns:
            bool: 是否应该发送通知
        """
        if not self.webhook_url:
            return False
            
        # 检查是否为管理员
        if self.notion_manager:
            admin_wxids = self.notion_manager.admins
            if sender_wxid in admin_wxids:
                return False
            
        # 检查是否在转发状态
        if self.ncc_manager:
            operator_state = self.ncc_manager.operator_states.get(sender_wxid)
            if operator_state and operator_state.state == "WAITING_CHOICE":
                return False
                
        return True

    def notify(self, msg: str, receiver: str = None, sender_msg: str = "", sender_wxid: str = "", is_group: bool = False) -> None:
        """发送飞书通知
        
        Args:
            msg: 机器人的回复消息
            receiver: 接收者ID，可选
            sender_msg: 发送者的原始消息
            sender_wxid: 发送者的wxid
            is_group: 是否是群消息
        """
        try:
            if not self.should_notify(sender_wxid):
                return
                
            # 获取接收者和发送者信息
            if is_group and receiver:
                # 从 notion_manager 获取群名映射
                groups_info = self.notion_manager.get_groups_info() if self.notion_manager else {}
                # 反转映射，找到群ID对应的群名
                group_name = receiver
                for name, wxid in groups_info.items():
                    if wxid == receiver:
                        group_name = name
                        break
                        
                sender_name = self.wcf.get_alias_in_chatroom(sender_wxid, receiver) if sender_wxid else "未知用户"
                notify_msg = f"「{group_name}」「{sender_name}」发送：{sender_msg}\n机器人：{msg}"
            else:
                # 查询数据库获取好友昵称
                if receiver:
                    contacts = self.wcf.query_sql(
                        "MicroMsg.db", 
                        f"SELECT NickName FROM Contact WHERE UserName='{receiver}';"
                    )
                    user_name = contacts[0]["NickName"] if contacts and len(contacts) > 0 else receiver
                    notify_msg = f"「{user_name}」发送：{sender_msg}\n机器人：{msg}"
                else:
                    notify_msg = f"机器人：{msg}"
            
            # 发送通知
            self.send_message(notify_msg)
        except Exception as e:
            logger.error(f"发送飞书通知失败: {e}") 