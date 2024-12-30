import re
import logging
from typing import Optional, List, Dict
import os
import json
from wcferry import Wcf, WxMsg
import random
import time
import lz4.block as lb
from .welcome_config import WelcomeConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WelcomeService:
    def __init__(self, wcf):
        self.wcf = wcf
        self.welcome_patterns = [
            r"邀请(.+)加入了群聊",
            r"(.+)通过扫描二维码加入群聊",
        ]
        self.welcome_configs = {}
        self.welcome_manager = WelcomeConfig()

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
        config = self.welcome_manager.get_welcome_messages(group_id)
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

        self.welcome_manager.set_welcome_messages(group_id, saved_messages, operator)
        self.wcf.send_text("✅ 迎新消息设置成功！", operator)

    def is_join_message(self, msg: WxMsg) -> tuple[bool, str]:
        """判断是否是入群消息，并提取新成员昵称"""
        for pattern in self.welcome_patterns:
            if match := re.search(pattern, msg.content):
                member_name = match.group(1).replace('"', '')
                return True, member_name
        return False, ""

    def handle_message(self, msg: WxMsg) -> None:
        """处理入群消息，触发欢迎消息发送"""
        # 检查是否是入群消息
        is_join, member_name = self.is_join_message(msg)
        if is_join:
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
            welcome_url = self.welcome_configs.get(group_id)
            if welcome_url:
                self._send_welcome_message(group_id, welcome_url, member_name)

            # 再延迟3-20秒发送自定义消息
            delay = random.randint(3, 20)
            logger.info(f"在 {delay} 秒后发送自定义消息给 {member_name}")
            time.sleep(delay)

            # 获取群的迎新消息配置
            welcome_config = self.welcome_manager.get_welcome_messages(group_id)
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

    def _send_merged_msg(self, recorditem: str, target: str) -> bool:
        """发送合并转发消息"""
        try:
            xml_msg = f"""<?xml version="1.0"?>
<msg>
    <appmsg appid="" sdkver="0">
        <title>群聊的聊天记录</title>
        <des>聊天记录</des>
        <action>view</action>
        <type>19</type>
        <showtype>0</showtype>
        <content></content>
        <url>https://support.weixin.qq.com/cgi-bin/mmsupport-bin/readtemplate?t=page/favorite_record__w_unsupport</url>
        <dataurl></dataurl>
        <lowurl></lowurl>
        <lowdataurl></lowdataurl>
        <recorditem><![CDATA[{recorditem}]]></recorditem>
        <thumburl></thumburl>
        <messageaction></messageaction>
        <extinfo></extinfo>
        <sourceusername></sourceusername>
        <sourcedisplayname></sourcedisplayname>
        <commenturl></commenturl>
        <appattach>
            <totallen>0</totallen>
            <attachid></attachid>
            <emoticonmd5></emoticonmd5>
            <fileext></fileext>
            <cdnthumburl></cdnthumburl>
            <cdnthumbaeskey></cdnthumbaeskey>
            <aeskey></aeskey>
            <encryver>0</encryver>
            <filekey></filekey>
        </appattach>
        <weappinfo>
            <pagepath></pagepath>
            <username></username>
            <appid></appid>
            <version>0</version>
            <type>0</type>
            <weappiconurl></weappiconurl>
            <shareId></shareId>
            <appservicetype>0</appservicetype>
        </weappinfo>
    </appmsg>
    <fromusername></fromusername>
    <scene>0</scene>
    <appinfo>
        <version>1</version>
        <appname></appname>
    </appinfo>
    <commenturl></commenturl>
    <realchatname></realchatname>
    <chatname></chatname>
    <membercount>0</membercount>
    <chatroomtype>0</chatroomtype>
</msg>"""

            # 压缩XML消息
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