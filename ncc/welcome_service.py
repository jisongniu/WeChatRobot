import re
import logging
from typing import Optional, List, Dict
import os
import json
import sqlite3
from wcferry import Wcf, WxMsg
import random
import time
import lz4.block as lb
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WelcomeService:
    def __init__(self, wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        db_path = os.path.join(os.path.dirname(__file__), "welcome_messages.db")
        self.db_path = db_path
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            # 创建消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT,
                    path TEXT,
                    recorditem TEXT,
                    operator TEXT NOT NULL,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 创建欢迎小卡片URL表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_urls (
                    group_id TEXT PRIMARY KEY,
                    welcome_url TEXT NOT NULL,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_welcome_messages(self, group_id: str) -> Optional[Dict]:
        """从数据库获取群的迎新消息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT message_type, content, path, recorditem, operator, update_time 
                    FROM welcome_messages 
                    WHERE group_id = ? 
                    ORDER BY id ASC
                """, (group_id,))
                rows = cursor.fetchall()
                
                if not rows:
                    return None
                    
                messages = []
                for row in rows:
                    msg_type, content, path, recorditem, operator, update_time = row
                    if msg_type == "text":
                        messages.append({"type": "text", "content": content})
                    elif msg_type == "image":
                        messages.append({"type": "image", "path": path})
                    elif msg_type == "merged":
                        messages.append({"type": "merged", "recorditem": recorditem})
                
                return {
                    "messages": messages,
                    "operator": operator,
                    "update_time": update_time
                }
                
        except Exception as e:
            logger.error(f"获取迎新消息失败: {e}")
            return None

    def set_welcome_messages(self, group_id: str, messages: List[Dict], operator: str) -> bool:
        """设置群的迎新消息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 先删除旧的消息
                cursor.execute("DELETE FROM welcome_messages WHERE group_id = ?", (group_id,))
                
                # 插入新的消息
                for msg in messages:
                    msg_type = msg["type"]
                    content = msg.get("content")
                    path = msg.get("path")
                    recorditem = msg.get("recorditem")
                    
                    cursor.execute("""
                        INSERT INTO welcome_messages 
                        (group_id, message_type, content, path, recorditem, operator) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (group_id, msg_type, content, path, recorditem, operator))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"设置迎新消息失败: {e}")
            return False

    def show_menu(self, operator: str) -> None:
        """显示迎新消息管理菜单"""
        menu = (
            "迎新消息管理：\n"
            "1 👈 查看当前迎新消息\n"
            "2 👈 设置新的迎新消息\n"
            "0 👈 退出"
        )
        self.wcf.send_text(menu, operator)

    def show_current_messages(self, group_id: str, operator: str) -> None:
        """显示当前迎新消息"""
        config = self.get_welcome_messages(group_id)
        if not config:
            self.wcf.send_text("当前群未设置迎新消息，如需设置，请回复2", operator)
            return

        # 发送所有消息
        for msg in config["messages"]:
            if msg["type"] == "text":
                self.wcf.send_text(msg["content"], operator)
            elif msg["type"] == "image":
                self.wcf.send_image(msg["path"], operator)
            elif msg["type"] == "merged":
                self._send_merged_msg(msg["recorditem"], operator)

        # 获取创建者的昵称
        creator_info = self.wcf.query_sql(
            "MicroMsg.db",
            f"SELECT NickName FROM Contact WHERE UserName='{config['operator']}';"
        )
        creator_name = creator_info[0]["NickName"] if creator_info else config['operator']

        self.wcf.send_text(
            f"当前迎新消息由 {creator_name} 创建于 {config['update_time']}，如果需要修改，请回复2",
            operator
        )

    def save_messages(self, group_id: str, messages: List[WxMsg], operator: str) -> None:
        """保存迎新消息"""
        saved_messages = []
        for msg in messages:
            if msg.type == 1:  # 文本消息
                saved_messages.append({"type": "text", "content": msg.content})
            elif msg.type == 3:  # 图片消息
                image_path = self.wcf.get_message_image(msg)
                if image_path:
                    saved_messages.append({"type": "image", "path": image_path})
            elif msg.type == 49:  # 合并转发消息
                try:
                    # 直接使用字符串查找方式提取recorditem内容
                    start = msg.content.find("<recorditem><![CDATA[")
                    if start != -1:
                        start += len("<recorditem><![CDATA[")
                        end = msg.content.find("]]></recorditem>", start)
                        if end != -1:
                            recorditem = msg.content[start:end]
                            if recorditem:
                                saved_messages.append({"type": "merged", "recorditem": recorditem})
                except Exception as e:
                    logger.error(f"处理合并转发消息失败: {e}")

        self.set_welcome_messages(group_id, saved_messages, operator)
        self.wcf.send_text("✅ 迎新消息设置成功！", operator)

    def is_join_message(self, msg: WxMsg) -> tuple[bool, str]:
        """判断是否是入群消息，并提取新成员昵称
        
        Args:
            msg: 微信消息对象
            
        Returns:
            tuple[bool, str]: (是否为入群消息, 新成员昵称)
        """
        for pattern in self.welcome_patterns:
            if match := re.search(pattern, msg.content):
                member_name = match.group(1).replace('"', '')
                return True, member_name
        return False, ""

    def is_welcome_group(self, group_id: str, groups: List[dict]) -> bool:
        """检查指定群是否为迎新群
        
        Args:
            group_id: 群ID
            groups: 群组配置列表
            
        Returns:
            bool: 是否为迎新群
        """
        # 使用any替代显式循环，提高代码简洁性
        return any(
            group.get('wxid') == group_id and group.get('welcome_enabled', False)
            for group in groups
        )

    def handle_message(self, msg: WxMsg) -> None:
        """处理入群消息，触发欢迎消息发送
        
        Args:
            msg: 微信消息对象
        """
        # 检查是否是入群消息
        is_join, member_name = self.is_join_message(msg)
        if not is_join:
            return

        # 检查是否是迎新群
        groups = self.load_groups_from_local()
        if not self.is_welcome_group(msg.roomid, groups):
            return

        # 在新线程中发送欢迎消息
        from threading import Thread
        Thread(
            target=self.send_welcome,
            args=(msg.roomid, member_name),
            name=f"WelcomeThread-{member_name}",
            daemon=True
        ).start()
        logger.info(f"已启动欢迎消息发送线程: {member_name}")

    def send_welcome(self, group_id: str, member_name: str) -> bool:
        """发送迎新消息"""
        try:
            # 先延迟3-10秒发送小卡片
            delay = random.randint(3, 10)
            logger.info(f"在 {delay} 秒后发送小卡片给 {member_name}")
            time.sleep(delay)

            # 如果有welcome_url，先发送小卡片
            welcome_url = self.get_welcome_url(group_id)
            if welcome_url:
                self._send_welcome_message(group_id, welcome_url, member_name)

            # 再延迟3-20秒发送自定义消息
            delay = random.randint(3, 20)
            logger.info(f"在 {delay} 秒后发送自定义消息给 {member_name}")
            time.sleep(delay)

            # 获取群的迎新消息配置
            welcome_config = self.get_welcome_messages(group_id)
            if welcome_config:
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
                        time.sleep(random.uniform(1, 5))  # 消息发送间隔1到5s
                    except Exception as e:
                        logger.error(f"发送迎新消息失败: {e}")

            return True
        except Exception as e:
            logger.error(f"发送迎新消息失败: {e}")
            return False

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

    def _send_merged_msg(self, recorditem: str, to_wxid: str) -> bool:
        """发送合并转发消息"""
        xml = f"""<?xml version="1.0"?>
<msg>
    <appmsg appid="" sdkver="0">
        <title>群聊的聊天记录</title>
        <des>聊天记录</des>
        <action>view</action>
        <type>19</type>
        <showtype>0</showtype>
        <url>https://support.weixin.qq.com/cgi-bin/mmsupport-bin/readtemplate?t=page/favorite_record__w_unsupport</url>
        <recorditem><![CDATA[{recorditem}]]></recorditem>
        <appattach>
            <cdnthumbaeskey></cdnthumbaeskey>
            <aeskey></aeskey>
        </appattach>
    </appmsg>
</msg>"""
        # 压缩XML消息
        text_bytes = xml.encode('utf-8')
        compressed_data = lb.compress(text_bytes, store_size=False)
        compressed_data_hex = compressed_data.hex()
        
        # 查询消息模板
        data = self.wcf.query_sql('MSG0.db', "SELECT * FROM MSG where type = 49 limit 1")
        if not data:
            logger.error("未找到合适的消息模板")
            return False
        
        # 更新数据库
        sql = f"UPDATE MSG SET CompressContent = x'{compressed_data_hex}', BytesExtra=x'', type=49, SubType=19, IsSender=0, TalkerId=2 WHERE MsgSvrID={data[0]['MsgSvrID']}"
        self.wcf.query_sql('MSG0.db', sql)
        
        # 发送消息
        result = self.wcf.forward_msg(data[0]["MsgSvrID"], to_wxid)
        return result == 1

    def load_groups_from_local(self) -> List[dict]:
        """从本地加载群组数据并解析欢迎配置"""
        try:
            groups_file = "data/notion_cache.json"
            if not os.path.exists(groups_file):
                logger.error("群组数据文件不存在")
                return []
                
            with open(groups_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
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
                # 如果有文章链接，保存到数据库
                if welcome_url:
                    self.set_welcome_url(group_wxid, welcome_url)
                    logger.debug(f"加载群 {group_name}({group_wxid}) 的迎新小卡片")
                
                # 返回群信息（只要开启了迎新推送就返回）
                return {
                    'wxid': group_wxid,
                    'name': group_name,
                    'welcome_enabled': welcome_enabled
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

    def get_welcome_url(self, group_id: str) -> Optional[str]:
        """从数据库获取群的欢迎小卡片URL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT welcome_url FROM welcome_urls WHERE group_id = ?",
                    (group_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"获取欢迎小卡片URL失败: {e}")
            return None

    def set_welcome_url(self, group_id: str, welcome_url: str) -> bool:
        """设置群的欢迎小卡片URL到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO welcome_urls (group_id, welcome_url)
                    VALUES (?, ?)
                """, (group_id, welcome_url))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"设置欢迎小卡片URL失败: {e}")
            return False