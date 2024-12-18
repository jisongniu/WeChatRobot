import re
import logging
from typing import Optional, List, Dict
import os
import json
from wcferry import Wcf, WxMsg

logger = logging.getLogger(__name__)

class WelcomeService:
    def __init__(self, wcf: Wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self.welcome_configs = {} 

    def load_groups_from_local(self) -> List[dict]:
        """从本地加载群组数据并解析欢迎配置"""
        try:
            groups_file = "data/notion_cache.json"
            if not os.path.exists(groups_file):
                logger.error("群组数据文件不存在")
                return []
                
            with open(groups_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            self.welcome_configs.clear()  # 清空现有缓存
            return self._parse_groups_data(data.get('groups', []))
                
        except Exception as e:
            logger.error(f"加载群组数据失败: {e}")
            return []

    def _parse_groups_data(self, results: List[dict]) -> List[dict]:
        """解析群组数据"""
        groups = []
        for item in results:
            properties = item.get('properties', {})
            group_data = self._extract_group_info(properties)
            if group_data:
                groups.append(group_data)
        return groups

    def _extract_group_info(self, properties: dict) -> Optional[dict]:
        """提取群组信息"""
        try:
            group_wxid = self._get_rich_text_value(properties.get('group_wxid', {}))
            group_name = self._get_title_value(properties.get('群名', {}))

            # 检查迎新推送开关
            welcome_enabled = properties.get('迎新推送开关', {}).get('checkbox', False)
            welcome_url = properties.get('迎新推送链接', {}).get('url')

            # 只有当 welcome_enabled 为 True 且有 welcome_url 时才会添加到配置中        
            if welcome_enabled and welcome_url and group_wxid:
                self.welcome_configs[group_wxid] = welcome_url
                logger.info(f"加载群 {group_name}({group_wxid}) 的欢迎配置")
            
            return {
                'wxid': group_wxid,
                'name': group_name,
            } if group_wxid else None
            
        except Exception as e:
            logger.error(f"解析群组信息失败: {e}")
            return None

    def is_join_message(self, msg: WxMsg) -> tuple[bool, str]:
        """
        判断是否是入群消息，并提取新成员昵称
        返回: (是否入群消息, 新成员昵称)
        """
        if msg.type != 10000:  # 系统消息类型
            return False, ""
        
        for pattern in self.welcome_patterns:
            if match := re.search(pattern, msg.content):
                return True, match.group(1)
        return False, ""

    def send_welcome(self, group_id: str, member_name: str) -> bool:
        """发送欢迎消息"""
        # 检查welcome_enabled（迎新推送开关）是否打开，url是否为空
        welcome_url = self.welcome_configs.get(group_id)

        #如果未配置欢迎url，则不发送欢迎消息
        if not welcome_url:
            return False
        
        try:
            return self._send_welcome_message(group_id, welcome_url, member_name)
        except Exception as e:
            logger.error(f"发送欢迎消息失败: {e}")
            return False 

    def _send_welcome_message(self, group_id: str, welcome_url: str, member_name: str) -> bool:
        """发送具体的欢迎消息"""
        result = self.wcf.send_rich_text(
            name="NCC社区",
            account="gh_0b00895e7394",
            title=f"{member_name}，欢迎加入NCC社区",
            digest=f"Hi {member_name}，点开看看",
            url=welcome_url,
            thumburl="",
            receiver=group_id
        )
        return result == 0 