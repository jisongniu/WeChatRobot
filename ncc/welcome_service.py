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
from queue import Queue
from threading import Lock, Thread
import lz4.block as lb
from .welcome_config import WelcomeConfig
from enum import Enum

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

class WelcomeState(Enum):
    """迎新消息管理状态"""
    IDLE = "idle"  # 空闲状态
    WAITING_CHOICE = "waiting_choice"  # 等待选择操作
    COLLECTING_MESSAGES = "collecting_messages"  # 收集新消息中

class WelcomeContext:
    """迎新消息上下文"""
    def __init__(self):
        self.state: WelcomeState = WelcomeState.IDLE
        self.group_id: Optional[str] = None
        self.messages: List[dict] = []

class WelcomeService:
    def __init__(self, wcf: Wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self.welcome_configs = {} 
        self.executor = ThreadPoolExecutor()  # 创建线程池
        self.welcome_manager = WelcomeConfig()  # 新的迎新消息管理器
        
        # 添加消息队列和处理线程
        self.welcome_queue = Queue()
        self.welcome_thread = Thread(target=self._process_welcome_queue, daemon=True)
        self.welcome_thread.start()
        
        # 用于管理操作者状态
        self.operator_contexts: Dict[str, WelcomeContext] = {}

    def handle_message(self, msg: WxMsg) -> bool:
        """处理收到的消息"""
        # 检查是否是入群消息
        if msg.type == 10000 and msg.from_group():
            is_join, member_name = self.is_join_message(msg)
            if is_join:
                return self.send_welcome(msg.roomid, member_name)

        # 获取操作者上下文
        context = self.operator_contexts.get(msg.sender)
        if not context:
            return False

        # 根据状态处理消息
        if context.state == WelcomeState.WAITING_CHOICE:
            return self._handle_choice(msg, context)
        elif context.state == WelcomeState.COLLECTING_MESSAGES:
            return self._handle_collecting(msg, context)

        return False

    def manage_welcome_messages(self, group_id: str, operator: str) -> None:
        """管理群的迎新消息"""
        # 创建操作者上下文
        context = WelcomeContext()
        context.state = WelcomeState.WAITING_CHOICE
        context.group_id = group_id
        self.operator_contexts[operator] = context
        
        # 显示菜单
        menu = (
            "迎新消息管理：\n"
            "1 👈 查看当前迎新消息\n"
            "2 👈 设置新的迎新消息\n"
            "0 👈 退出"
        )
        self.wcf.send_text(menu, operator)

    def _handle_choice(self, msg: WxMsg, context: WelcomeContext) -> bool:
        """处理选择状态的消息"""
        if msg.content == "0":
            self.wcf.send_text("已退出迎新消息管理", msg.sender)
            del self.operator_contexts[msg.sender]
            return True
            
        elif msg.content == "1":
            self._show_current_messages(context.group_id, msg.sender)
            return True
            
        elif msg.content == "2":
            context.state = WelcomeState.COLLECTING_MESSAGES
            context.messages = []
            menu = (
                "请发送要设置的迎新消息，支持：\n"
                "- 文本消息\n"
                "- 图片\n"
                "- 合并转发\n"
            )
            self.wcf.send_text(menu, msg.sender)
            return True
            
        else:
            self.wcf.send_text("无效的选择，请重新输入", msg.sender)
            return True

    def _handle_collecting(self, msg: WxMsg, context: WelcomeContext) -> bool:
        """处理收集消息状态"""
        try:
            if msg.content == "完成":
                if context.messages:
                    self.welcome_manager.set_welcome_messages(context.group_id, context.messages, msg.sender)
                    self.wcf.send_text("✅ 迎新消息设置成功！", msg.sender)
                else:
                    self.wcf.send_text("未收集到任何消息，设置取消！", msg.sender)
                del self.operator_contexts[msg.sender]
                return True
                
            elif msg.content == "取消":
                self.wcf.send_text("已取消设置！", msg.sender)
                del self.operator_contexts[msg.sender]
                return True

            # 处理不同类型的消息
            if msg.type == 0x01:  # 文本消息
                context.messages.append({"type": "text", "content": msg.content})
                self.wcf.send_text("✅ 已添加文本消息", msg.sender)
            elif msg.type == 0x03:  # 图片消息
                image_path = self.wcf.get_message_image(msg)
                if image_path:
                    context.messages.append({"type": "image", "path": image_path})
                    self.wcf.send_text("✅ 已添加图片消息", msg.sender)
                else:
                    self.wcf.send_text("❌ 图片保存失败！", msg.sender)
            elif msg.type == 0x49:  # 合并转发消息
                context.messages.append({"type": "merged", "recorditem": msg.content})
                self.wcf.send_text("✅ 已添加合并转发消息", msg.sender)
            else:
                self.wcf.send_text(f"❌ 不支持的消息类型！(type={msg.type})", msg.sender)
                return True

            status = (
                f"已收集 {len(context.messages)} 条消息\n"
                "继续发送或回复：\n"
                "完成 - 保存设置\n"
                "取消 - 取消设置"
            )
            self.wcf.send_text(status, msg.sender)
            return True
            
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
            self.wcf.send_text("❌ 处理消息时出错，请重试", msg.sender)
            return True

    def _show_current_messages(self, group_id: str, operator: str) -> None:
        """显示当前迎新消息"""
        config = self.welcome_manager.get_welcome_messages(group_id)
        if not config:
            self.wcf.send_text("当前群未设置迎新消息", operator)
            return

        # 发送所有消息
        for msg in config["messages"]:
            if msg["type"] == "text":
                self.wcf.send_text(msg["content"], operator)
            elif msg["type"] == "image":
                self.wcf.send_image(msg["path"], operator)
            elif msg["type"] == "merged":
                self._send_merged_msg(msg["recorditem"], operator)

        self.wcf.send_text(
            f"当前迎新消息由 {config['operator']} 创建于 {config['update_time']}，如果需要修改，请回复2",
            operator
        )

    def send_welcome(self, group_id: str, member_name: str, operator_id: str = None) -> bool:
        """发送迎新消息"""
        try:
            # 将迎新任务添加到队列
            self.welcome_queue.put((group_id, member_name, operator_id))
            
            # 如果有welcome_url，启动延迟发送
            welcome_url = self.welcome_configs.get(group_id)
            if welcome_url:
                self.executor.submit(self._delayed_send_welcome, group_id, welcome_url, member_name)
            
            return True
        except Exception as e:
            logger.error(f"添加迎新任务失败: {e}")
            return False

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
                title=f"🐶肥肉摇尾巴欢迎{member_name}！点开看看",
                digest=f"我是ncc团宠肥肉～\n这里是在地信息大全\n要一条一条看哦",
                url=welcome_url,
                thumburl="https://pic.imgdb.cn/item/6762f60ed0e0a243d4e62f84.png"
            )
            logger.info(f"发送欢迎消息给 {member_name}: {'成功' if result == 0 else '失败'}")
            return result == 0
        except Exception as e:
            logger.error(f"发送欢迎消息失败: {e}")
            return False

    def _send_merged_msg(self, recorditem: str, target: str) -> bool:
        """发送合并转发消息"""
        try:
            xml_msg = f"""<?xml version="1.0"?>
<msg>
    <appmsg appid="" sdkver="0">
        <title>聊天记录</title>
        <des>聊天记录</des>
        <type>19</type>
        <url>https://support.weixin.qq.com/cgi-bin/mmsupport-bin/readtemplate?t=page/favorite_record__w_unsupport</url>
        <appattach>
            <cdnthumbaeskey></cdnthumbaeskey>
            <aeskey></aeskey>
        </appattach>
        <recorditem><![CDATA[{recorditem}]]></recorditem>
        <percent>0</percent>
    </appmsg>
</msg>"""

            text_bytes = xml_msg.encode('utf-8')
            compressed_data = lb.compress(text_bytes, store_size=False)
            compressed_data_hex = compressed_data.hex()

            data = self.wcf.query_sql('MSG0.db', "SELECT * FROM MSG where type = 49 limit 1")
            if not data:
                logger.error("未找到合适的消息模板")
                return False

            self.wcf.query_sql(
                'MSG0.db',
                f"UPDATE MSG SET CompressContent = x'{compressed_data_hex}', BytesExtra=x'', type=49, SubType=19, IsSender=0, TalkerId=2 WHERE MsgSvrID={data[0]['MsgSvrID']}"
            )

            result = self.wcf.forward_msg(data[0]["MsgSvrID"], target)
            return result == 1

        except Exception as e:
            logger.error(f"发送合并消息时发生错误：{e}")
            return False

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

            # 如果群ID存在且开启了迎新推送
            if group_wxid and welcome_enabled:
                # 如果有文章链接，添加到小卡片迎新推送配置
                if welcome_url:
                    self.welcome_configs[group_wxid] = welcome_url
                    logger.debug(f"加载群 {group_name}({group_wxid}) 的迎新小卡片")
                
                # 返回群信息（只要开启了迎新推送就返回）
                return {
                    'wxid': group_wxid,
                    'name': group_name,
                }
            
            return None
            
        except Exception as e:
            logger.error(f"解析群组信息失败: {e}")
            return None

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

    def _process_welcome_queue(self):
        """处理迎新消息队列的后台线程"""
        while True:
            try:
                # 从队列获取迎新任务
                task = self.welcome_queue.get()
                if task is None:
                    continue
                    
                group_id, member_name, operator_id = task
                
                # 获取群的迎新消息配置
                welcome_config = self.welcome_manager.get_welcome_messages(group_id)
                if not welcome_config:
                    continue
                
                # 发送自定义迎新消息
                messages = welcome_config.get("messages", [])
                for msg in messages:
                    try:
                        msg_type = msg.get("type")
                        if msg_type == "text":
                            content = msg.get("content", "").replace("{member_name}", member_name)
                            self.wcf.send_text(content, group_id)
                        elif msg_type == "image":
                            self.wcf.send_image(msg.get("path"), group_id)
                        elif msg_type == "merged":
                            self._send_merged_msg(msg.get("recorditem"), group_id)
                        time.sleep(0.3)  # 消息发送间隔
                    except Exception as e:
                        logger.error(f"发送迎新消息失败: {e}")
                        
                if operator_id:
                    self.wcf.send_text("迎新消息发送完成", operator_id)
                    
            except Exception as e:
                logger.error(f"处理迎新消息队列异常: {e}")
            finally:
                self.welcome_queue.task_done()

    def is_join_message(self, msg: WxMsg) -> tuple[bool, str]:
        """
        判断是否是入群消息，并提取新成员昵称
        返回: (是否入群消息, 新成员昵称)
        """
        for pattern in self.welcome_patterns:
            if match := re.search(pattern, msg.content):
                # 去掉昵称中的引号
                member_name = match.group(1).replace('"', '')
                return True, member_name
        return False, ""