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

logging.basicConfig(level=logging.INFO)

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
        self.welcome_manager = WelcomeConfig()  # 新的迎新消息管理器
        
        # 添加消息队列和处理线程
        self.welcome_queue = Queue()
        self.welcome_thread = Thread(target=self._process_welcome_queue, daemon=True)
        self.welcome_thread.start()
        
        # 用于管理每个操作者的消息队列
        self.message_queues: Dict[str, Queue] = {}
        self.message_queue_lock = Lock()

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
                            self._send_merged_msg(msg.get("content"), group_id)
                        time.sleep(0.3)  # 消息发送间隔
                    except Exception as e:
                        logger.error(f"发送迎新消息失败: {e}")
                        
                if operator_id:
                    self.wcf.send_text("迎新消息发送完成", operator_id)
                    
            except Exception as e:
                logger.error(f"处理迎新消息队列异常: {e}")
            finally:
                self.welcome_queue.task_done()

    def _get_message_queue(self, operator: str) -> Queue:
        """获取或创建操作者的消息队列"""
        with self.message_queue_lock:
            if operator not in self.message_queues:
                self.message_queues[operator] = Queue()
            return self.message_queues[operator]

    def _remove_message_queue(self, operator: str) -> None:
        """移除操作者的消息队列"""
        with self.message_queue_lock:
            if operator in self.message_queues:
                del self.message_queues[operator]

    def handle_message(self, msg: WxMsg) -> bool:
        """处理收到的消息"""
        # 如果发送者有消息队列，说明正在等待消息
        queue = self.message_queues.get(msg.sender)
        if queue:
            queue.put(msg)
            return True

        # 检查是否是入群消息
        if msg.type == 10000 and msg.from_group():
            is_join, member_name = self.is_join_message(msg)
            if is_join:
                return self.send_welcome(msg.roomid, member_name)

        return False

    def _wait_for_next_message(self, operator: str, timeout: int = 60) -> Optional[WxMsg]:
        """等待下一条消息"""
        queue = self._get_message_queue(operator)
        try:
            # 等待消息，超时返回None
            msg = queue.get(timeout=timeout)
            return msg
        except:
            return None
        finally:
            # 如果队列为空，移除它
            if queue.empty():
                self._remove_message_queue(operator)

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

    def manage_welcome_messages(self, group_id: str, operator: str) -> None:
        """管理群的迎新消息"""
        try:
            # 首次显示菜单
            menu = (
                "迎新消息管理：\n"
                "1 👈 查看当前迎新消息\n"
                "2 👈 设置新的迎新消息\n"
                "0 👈 退出"
            )
            self.wcf.send_text(menu, operator)
            
            while True:
                msg = self._wait_for_next_message(operator)
                if not msg:
                    continue
                    
                if msg.content == "0":
                    self.wcf.send_text("已退出迎新消息管理", operator)
                    break
                elif msg.content == "1":
                    self._show_current_messages(group_id, operator)
                    # 显示完当前消息后，重新显示菜单
                    self.wcf.send_text(menu, operator)
                elif msg.content == "2":
                    self._set_new_messages(group_id, operator)
                    # 设置完成后退出
                    break
                else:
                    # 无效输入时重新显示菜单
                    self.wcf.send_text("无效的选择\n" + menu, operator)
        finally:
            # 清理消息队列
            self._remove_message_queue(operator)

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
                self.wcf.send_image(operator, msg["path"])
            elif msg["type"] == "merged":
                self._send_merged_msg(operator, msg["recorditem"])

        # 再发送提示信息
        self.wcf.send_text(
            f"当前迎新消息由 {config['operator']} 创建于 {config['update_time']}，如果需要修改，请回复2",
            operator
        )
        
    def _set_new_messages(self, group_id: str, operator: str) -> None:
        """设置新的迎新消息"""
        messages = []
        self.wcf.send_text(
            "请发送要设置的迎新消息，支持：文本消息、图片、合并转发信息\n"
            "支持发送多条消息，设置完成后将覆盖已有配置\n"
            "发送完成后回复“完成”保存",
            operator
        )
        
        try:
            while True:
                msg = self._wait_for_next_message(operator)
                if not msg:
                    continue
                    
                if msg.content == "完成":
                    break
                    
                if msg.type == 0x01:  # 文本消息
                    messages.append({"type": "text", "content": msg.content})
                elif msg.type == 0x03:  # 图片消息
                    image_path = self.wcf.get_message_image(msg)
                    if image_path:
                        messages.append({"type": "image", "path": image_path})
                    else:
                        self.wcf.send_text("图片保存失败！", operator)
                elif msg.type == 0x49:  # 合并转发消息
                    messages.append({"type": "merged", "recorditem": msg.content})
                else:
                    self.wcf.send_text("不支持的消息类型！", operator)
                    continue

                self.wcf.send_text(f"已收集 {len(messages)} 条消息，继续发送或回复“完成”保存", operator)

            if messages:
                self.welcome_manager.set_welcome_messages(group_id, messages, operator)
                self.wcf.send_text("迎新消息设置成功！", operator)
            else:
                self.wcf.send_text("未收集到任何消息，设置取消！", operator)
        finally:
            # 清理消息队列
            self._remove_message_queue(operator)

    def send_custom_welcome(self, group_id: str, member_name: str) -> bool:
        """发送自定义迎新消息"""
        config = self.welcome_manager.get_welcome_messages(group_id)
        if not config:
            return False

        try:
            for msg in config["messages"]:
                if msg["type"] == "text":
                    self.wcf.send_text(group_id, msg["content"].replace("{member_name}", member_name))
                elif msg["type"] == "image":
                    self.wcf.send_image(group_id, msg["path"])
                elif msg["type"] == "merged":
                    self._send_merged_msg(group_id, msg["recorditem"])
            return True
        except Exception as e:
            logger.error(f"发送自定义迎新消息失败: {e}")
            return False

    def _send_merged_msg(self, target: str, recorditem: str) -> bool:
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