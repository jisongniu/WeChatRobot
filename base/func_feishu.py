import logging
import requests
from typing import Optional

logger = logging.getLogger("FeishuBot")

class FeishuBot:
    """飞书机器人服务"""
    def __init__(self, webhook_url: str):
        """初始化飞书机器人
        
        Args:
            webhook_url: 飞书机器人的webhook地址
        """
        self.webhook_url = webhook_url
        
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