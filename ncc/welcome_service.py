import re
import logging
from typing import Optional, List, Dict
import os
import json
from wcferry import Wcf, WxMsg
import asyncio
from concurrent.futures import ThreadPoolExecutor
import random
import time
logging.basicConfig(level=logging.DEBUG)



logger = logging.getLogger(__name__)

class WelcomeService:
    def __init__(self, wcf: Wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self.welcome_configs = {} 
        self.executor = ThreadPoolExecutor()  # 创建线程池

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
                logger.debug(f"加载群 {group_name}({group_wxid}) 的欢迎配置")
            
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
        """发送非阻塞地发送欢迎消息"""
        # 检查welcome_enabled（迎新推送开关）是否打开，url是否为空
        welcome_url = self.welcome_configs.get(group_id)

        # 如果未配置欢迎url，则不发送欢迎消息
        if not welcome_url:
            return False

        # 在新线程中执行延迟发送
        self.executor.submit(self._delayed_send_welcome, group_id, welcome_url, member_name)
        return True

    def _delayed_send_welcome(self, group_id: str, welcome_url: str, member_name: str) -> None:
        """在单独的线程中处理延迟发送"""
        try:
            # 随机延迟30-60秒
            delay = random.randint(30, 60)
            logger.info(f"在 {delay} 秒后发送欢迎消息给 {member_name}")
            time.sleep(delay)
            self._send_welcome_message(group_id, welcome_url, member_name)
        except Exception as e:
            logger.error(f"发送欢迎消息失败: {e}")

    def _send_welcome_message(self, group_id: str, welcome_url: str, member_name: str) -> bool:
        """发送具体的欢迎消息"""
        try:
            result = self.wcf.send_rich_text(
                receiver=group_id,
                name="NCC社区",
                account="gh_0b00895e7394",
                title=f"🐶肥肉摇尾巴欢迎{member_name}！",
                digest=f"Hi {member_name}，点开看看",
                url=welcome_url,
                thumburl="https://pic.imgdb.cn/item/6762f60ed0e0a243d4e62f84.png"
            )
            logger.info(f"发送欢迎消息给 {member_name}: {'成功' if result == 0 else '失败'}")
            logger.debug(f"发送欢迎消息的URL是: {welcome_url}")
            return result == 0
        except Exception as e:
            logger.error(f"发送欢迎消息失败: {e}")
            return False

    def _get_rich_text_value(self, prop: dict) -> str:
        """从rich_text类型的属性中提取值"""
        try:
            rich_text = prop.get('rich_text', [])
            if rich_text and len(rich_text) > 0:
                return rich_text[0]['text']['content']
        except Exception as e:
            logger.error(f"提取rich_text值失败: {e}")
        return ""

    def _get_title_value(self, prop: dict) -> str:
        """从title类型的属性中提取值"""
        try:
            title = prop.get('title', [])
            if title and len(title) > 0:
                return title[0]['text']['content']
        except Exception as e:
            logger.error(f"提取title值失败: {e}")
        return ""