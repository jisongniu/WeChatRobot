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
from .db_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WelcomeService:
    def __init__(self, wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self.db = DatabaseManager()

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
        messages = self.db.get_welcome_messages(group_id)
        if not messages:
            self.wcf.send_text("当前群未设置迎新消息，如需设置，请回复2", operator)
            return

        # 发送所有消息
        for msg in messages:
            if msg["type"] == 1:  # 文本消息
                self.wcf.send_text(msg["content"], operator)
            elif msg["type"] == 3:  # 图片消息
                if msg.get("extra"):  # 如果有图片路径
                    self.wcf.send_image(msg["extra"], operator)
            elif msg["type"] == 49:  # 合并转发消息
                if msg.get("extra"):  # 如果有recorditem
                    self._send_merged_msg(msg["extra"], operator)

        # 获取最后一次更新的时间和操作者
        with self.db.get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT operator, updated_at 
                FROM welcome_messages 
                WHERE group_wxid = ? 
                ORDER BY updated_at DESC 
                LIMIT 1
            ''', (group_id,))
            result = cur.fetchone()
            
            if result:
                operator_wxid, update_time = result
                # 从数据库获取操作者昵称
                operator_name = self.db.get_admin_name_by_wxid(operator_wxid)
                self.wcf.send_text(
                    f"当前迎新消息由 {operator_name} 创建于 {update_time}，如需修改，请回复2",
                    operator
                )
            else:
                self.wcf.send_text("以上是当前的迎新消息，如需修改，请回复2", operator)

    def save_messages(self, group_id: str, messages: List[WxMsg], operator: str) -> None:
        """保存迎新消息"""
        saved_messages = []
        for msg in messages:
            if msg.type == 1:  # 文本消息
                saved_messages.append({
                    "type": msg.type,
                    "content": msg.content,
                    "extra": None
                })
            elif msg.type == 3:  # 图片消息
                image_path = self.wcf.get_message_image(msg)
                if image_path:
                    saved_messages.append({
                        "type": msg.type,
                        "content": None,
                        "extra": image_path
                    })
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
                                saved_messages.append({
                                    "type": msg.type,
                                    "content": None,
                                    "extra": recorditem
                                })
                except Exception as e:
                    logger.error(f"处理合并转发消息失败: {e}")

        self.db.save_welcome_messages(group_id, saved_messages, operator)
        self.wcf.send_text("✅ 迎新消息设置成功！", operator)

    def is_join_message(self, msg: WxMsg) -> tuple[bool, str]:
        """判断是否是入群消息，并提取新成员昵称"""
        for pattern in self.welcome_patterns:
            if match := re.search(pattern, msg.content):
                member_name = match.group(1).replace('"', '')
                return True, member_name
        return False, ""

    def is_welcome_group(self, group_id: str) -> bool:
        """检查指定群是否为迎新群"""
        groups = self.db.get_welcome_enabled_groups()
        return any(group['wxid'] == group_id for group in groups)

    def handle_message(self, msg: WxMsg) -> None:
        """处理入群消息，触发欢迎消息发送"""
        # 检查是否是入群消息
        is_join, member_name = self.is_join_message(msg)
        if not is_join:
            return

        # 检查是否是迎新群
        if not self.is_welcome_group(msg.roomid):
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
            # 获取迎新消息
            messages = self.db.get_welcome_messages(group_id)
            
            # 获取欢迎小卡片URL
            welcome_url = self.db.get_welcome_url(group_id)
            
            # 如果有欢迎小卡片，先发送小卡片
            if welcome_url:
                # 延迟3-10秒发送小卡片
                delay = random.randint(3, 10)
                logger.info(f"在 {delay} 秒后发送小卡片给 {member_name}")
                time.sleep(delay)
                
                # 发送小卡片
                self._send_welcome_card(group_id, welcome_url, member_name)
                
            
            # 如果有其他迎新消息：
            if messages:
                # 延迟3-10秒发送消息
                delay = random.randint(3, 10)
                logger.info(f"在 {delay} 秒后发送其他消息给 {member_name}")
                time.sleep(delay)
                # 发送每条消息
                for msg in messages:

                    if msg["type"] == 1:  # 文本消息
                        # 替换消息中的 {member_name} 为实际昵称
                        content = msg["content"].replace("{member_name}", member_name)
                        self.wcf.send_text(content, group_id)
                    elif msg["type"] == 3:  # 图片消息
                        if msg.get("extra"):  # 如果有图片路径
                            self.wcf.send_image(msg["extra"], group_id)
                    elif msg["type"] == 49:  # 合并转发消息
                        if msg.get("extra"):  # 如果有recorditem
                            self._send_merged_msg(msg["extra"], group_id)
                    
                    # 每条消息之间随机延迟1-3秒
                    time.sleep(random.uniform(1, 3))

            return True

        except Exception as e:
            logger.error(f"发送迎新消息失败: {e}")
            return False

    def _send_welcome_card(self, group_id: str, welcome_url: str, member_name: str) -> bool:
        """发送欢迎小卡片"""
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
            logger.info(f"发送欢迎小卡片给 {member_name}: {'成功' if result == 0 else '失败'}")
            return result == 0
        except Exception as e:
            logger.error(f"发送欢迎小卡片失败: {e}")
            return False

    def _send_merged_msg(self, recorditem: str, to_wxid: str) -> bool:
        """发送合并转发消息"""
        try:
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
            
        except Exception as e:
            logger.error(f"发送合并转发消息失败: {e}")
            return False

    def load_groups_from_local(self) -> List[dict]:
        """从本地数据库加载群组配置"""
        return self.db.get_welcome_enabled_groups()