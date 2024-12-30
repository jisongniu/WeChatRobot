from typing import List, Dict, Optional
import json
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class WelcomeConfig:
    def __init__(self):
        self.config_file = "data/welcome_messages.json"
        self.configs: Dict[str, dict] = {}
        self.load_configs()

    def load_configs(self) -> None:
        """从文件加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.configs = json.load(f)
                    # 处理所有合并转发消息，确保内容不被转义
                    for group_config in self.configs.values():
                        for msg in group_config.get("messages", []):
                            if msg.get("type") == "merged":
                                # 将转义后的字符还原
                                msg["recorditem"] = msg["recorditem"].encode().decode('unicode_escape')
        except Exception as e:
            logger.error(f"加载迎新配置失败: {e}")
            self.configs = {}

    def save_configs(self) -> None:
        """保存配置到文件"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            # 创建配置的副本，避免修改原始数据
            configs_copy = {}
            for group_id, group_config in self.configs.items():
                group_copy = group_config.copy()
                messages_copy = []
                for msg in group_config["messages"]:
                    msg_copy = msg.copy()
                    if msg["type"] == "merged":
                        # 对recorditem内容进行特殊处理，确保正确保存
                        msg_copy["recorditem"] = msg["recorditem"].replace('\\', '\\\\').replace('"', '\\"')
                    messages_copy.append(msg_copy)
                group_copy["messages"] = messages_copy
                configs_copy[group_id] = group_copy

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(configs_copy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存迎新配置失败: {e}")

    def get_welcome_messages(self, group_id: str) -> Optional[dict]:
        """获取群的迎新消息配置"""
        return self.configs.get(group_id)

    def set_welcome_messages(self, group_id: str, messages: List[dict], operator: str) -> None:
        """设置群的迎新消息"""
        self.configs[group_id] = {
            "messages": messages,
            "operator": operator,
            "update_time": datetime.now().strftime("%Y-%m-%d")
        }
        self.save_configs()

    def format_message_for_display(self, message: dict) -> str:
        """格式化消息用于显示"""
        msg_type = message.get("type")
        if msg_type == "text":
            return f"[文本] {message.get('content')}"
        elif msg_type == "image":
            return "[图片]"
        elif msg_type == "merged":
            return "[合并转发]"
        return "[未知类型消息]" 