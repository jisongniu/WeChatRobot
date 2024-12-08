# -*- coding: utf-8 -*-

import logging
import re
import time
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread
from base.func_zhipu import ZhiPu
from enum import Enum, auto

from wcferry import Wcf, WxMsg

from base.func_bard import BardAssistant
from base.func_chatglm import ChatGLM
from base.func_chatgpt import ChatGPT
from base.func_chengyu import cy
from base.func_news import News
from base.func_tigerbot import TigerBot
from base.func_xinghuo_web import XinghuoWeb
from configuration import Config
from constants import ChatType, MIN_ACCEPT_DELAY, MAX_ACCEPT_DELAY, FRIEND_WELCOME_MSG
from job_mgmt import Job
from WeChatRobot.base.notion_manager import NotionManager
import random  

__version__ = "39.2.4.0"


class ForwardState(Enum):
    IDLE = auto()
    WAITING_CHOICE_MODE = auto()  # 新增状态：等待用户选择模式
    WAITING_MESSAGE = auto()
    WAITING_CHOICE = auto()


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int) -> None:
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        # 选择模型
        if ChatType.is_in_chat_types(chat_type):
            if chat_type == ChatType.TIGER_BOT.value and TigerBot.value_check(self.config.TIGERBOT):
                self.chat = TigerBot(self.config.TIGERBOT)
            elif chat_type == ChatType.CHATGPT.value and ChatGPT.value_check(self.config.CHATGPT):
                self.chat = ChatGPT(self.config.CHATGPT)
            elif chat_type == ChatType.XINGHUO_WEB.value and XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
            elif chat_type == ChatType.CHATGLM.value and ChatGLM.value_check(self.config.CHATGLM):
                self.chat = ChatGLM(self.config.CHATGLM)
            elif chat_type == ChatType.BardAssistant.value and BardAssistant.value_check(self.config.BardAssistant):
                self.chat = BardAssistant(self.config.BardAssistant)
            elif chat_type == ChatType.ZhiPu.value and ZhiPu.value_check(self.config.ZhiPu):
                self.chat = ZhiPu(self.config.ZhiPu)
            else:
                self.LOG.warning("未配置模型")
                self.chat = None
        else:
            if TigerBot.value_check(self.config.TIGERBOT):
                self.chat = TigerBot(self.config.TIGERBOT)
            elif ChatGPT.value_check(self.config.CHATGPT):
                self.chat = ChatGPT(self.config.CHATGPT)
            elif XinghuoWeb.value_check(self.config.XINGHUO_WEB):
                self.chat = XinghuoWeb(self.config.XINGHUO_WEB)
            elif ChatGLM.value_check(self.config.CHATGLM):
                self.chat = ChatGLM(self.config.CHATGLM)
            elif BardAssistant.value_check(self.config.BardAssistant):
                self.chat = BardAssistant(self.config.BardAssistant)
            elif ZhiPu.value_check(self.config.ZhiPu):
                self.chat = ZhiPu(self.config.ZhiPu)
            else:
                self.LOG.warning("未配置模型")
                self.chat = None

        self.LOG.info(f"已选择: {self.chat}")

        self.notion_manager = NotionManager(
            token=config.NOTION['TOKEN'],
            lists_db_id=config.NOTION['LISTS_DB_ID'],
            groups_db_id=config.NOTION['GROUPS_DB_ID'],
            wcf=wcf
        )
        self.forward_state = ForwardState.IDLE
        self.forward_message = None
        self.forward_admin = config.FORWARD_ADMIN

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        return self.toChitchat(msg)

    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        status = False
        texts = re.findall(r"^([#|?|？])(.*)$", msg.content)
        # [('#', '天天向上')]
        if texts:
            flag = texts[0][0]
            text = texts[0][1]
            if flag == "#":  # 接龙
                if cy.isChengyu(text):
                    rsp = cy.getNext(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True
            elif flag in ["?", "？"]:  # 查词
                if cy.isChengyu(text):
                    rsp = cy.getMeaning(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True

        return status

    def toChitchat(self, msg: WxMsg) -> bool:
        """处理闲聊消息，通过 ChatGPT 生成回复
        """
        # 如果没有配置 ChatGPT，返回固定回复
        if not self.chat:
            rsp = "你@我干嘛？"
        else:  # 如果配置了 ChatGPT，通过 ChatGPT 生成回复
            # 从消息内容中移除 @ 和空格，得到问题
            q = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
            # 通过 ChatGPT 获取答案
            rsp = self.chat.get_answer(q, (msg.roomid if msg.from_group() else msg.sender))

        # 如果获取到了回复，发送回复
        if rsp:
            # 如果是群聊，发送回复到群聊，并 @ 发送者
            if msg.from_group():
                self.sendTextMsg(rsp, msg.roomid, msg.sender)
            else:  # 如果是私聊，直接发送回复
                self.sendTextMsg(rsp, msg.sender)
            return True  # 返回处理成功
        else:  # 如果没有获取到回复，记录错误日志
            self.LOG.error(f"无法从 ChatGPT 获得答案")
            return False  # 返回处理失败

    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """

        # 群聊消息
        if msg.from_group():
            # 如果在群里被 @，看是否在notion里允许响应的群列表里
            allowed_groups = self.notion_manager.get_all_allowed_groups()
            if msg.roomid not in allowed_groups:  # 不在允许响应的群列表里，忽略
                return

            if msg.is_at(self.wxid):  # 被@
                self.toAt(msg)

            else:  # 其他消息
                self.toChitchat(msg)

            return  # 处理完群聊信息，后面就不需要处理了

        # 非群聊信息，按消息类型进行处理
        if msg.type == 37:  # 好友请求
            self.handle_friend_request(msg)

        elif msg.type == 10000:  # 系统信息
            self.sayHiToNewFriend(msg)

        elif msg.type == 0x01:  # 文本消息
            # 让配置加载更灵活，自己可以更新配置。也可以利用定时任务更新。

            if msg.from_self():  # 判断消息是否是机器人自己发送的
                if msg.content == "^更新$":  # 判断消息内容是否匹配正则表达式 "^更新$"
                    self.config.reload()  # 重新加载配置文件
                    self.LOG.info("已更新")  # 记录日志 
                    
            # 如果是管理员且在处理转发流程
            elif msg.sender == self.forward_admin:
                if msg.content == "刷新列表":
                    self.notion_manager.refresh_lists()
                    self.sendTextMsg("已刷新转发列表", msg.sender)
                    return
                elif msg.content == "删除缓存":
                    self.notion_manager.clear_cache()
                    self.sendTextMsg("已删除缓存", msg.sender)
                    return
                if self._handle_forward_admin_msg(msg):
                    return
            else:
                # 如果不是以上流程，则进行闲聊
                self.toChitchat(msg)  # 闲聊

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    self.LOG.info(msg)
                    self.processMsg(msg)
                except Empty:
                    continue  # Empty message
                except Exception as e:
                    self.LOG.error(f"Receiving message error: {e}")

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # 初始化@列表为空
        ats = ""
        # 如果有@列表
        if at_list:
            # 如果@列表是"notify@all"，则@所有人
            if at_list == "notify@all":
                ats = " @所有人"
            else:
                # 将@列表按逗号分割成wxid列表
                wxids = at_list.split(",")
                # 遍历wxid列表
                for wxid in wxids:
                    # 根据wxid和接收人查找群昵称，并添加到@列表中
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # 构建最终发送的消息内容
        # 如果@列表为空，则直接发送消息
        if ats == "":
            self.LOG.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            # 如果@列表不为空，则在消息内容后添加@列表
            self.LOG.info(f"To {receiver}: {ats}\r{msg}")
            self.wcf.send_text(f"{ats}\n\n{msg}", receiver, at_list)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact;")
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def handle_friend_request(self, msg):
        """处理好友请求的完整流程：延迟接受并发送欢迎消息
        Args:
            msg: 好友请求消息
        """
        def delayed_accept():
            try:
                # 随机延迟30-90秒
                delay = random.randint(MIN_ACCEPT_DELAY, MAX_ACCEPT_DELAY)
                self.LOG.info(f"将在{delay}秒后通过好友请求")
                time.sleep(delay)
                
                self.accept_friend_request(msg)  # 调用具体的接受请求函数
                
                # 等待一下让系统处理完好友请求
                time.sleep(1)
                
                # 获取新好友信息
                new_friend = self.get_friend_by_wxid(msg.sender)
                if new_friend:
                    # 发送欢迎消息
                    welcome_msg = FRIEND_WELCOME_MSG
                    self.sendTextMsg(welcome_msg, msg.sender)
                    self.LOG.info(f"已发送欢迎消息给：{new_friend.nickname}")
            except Exception as e:
                self.LOG.error(f"处理好友请求失败：{e}")
        
        # 启动新线程处理请求，避免阻塞主线程
        Thread(target=delayed_accept, name="AcceptFriend").start()
    
    def accept_friend_request(self, msg):
        """通过好友请求
        Args:
            msg: 好友请求消息
        """
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)
            self.LOG.info(f"已通过好友请求: {msg.content}")
        except Exception as e:
            self.LOG.error(f"同意好友出错：{e}")
    
    def get_friend_by_wxid(self, wxid):
        """根据wxid获取好友信息
        Args:
            wxid: 好友的wxid
        Returns:
            好友信息对象
        """
        try:
            # 查询数据库获取好友昵称
            contacts = self.wcf.query_sql(
                "MicroMsg.db", 
                f"SELECT NickName FROM Contact WHERE UserName='{wxid}';"
            )
            if contacts and len(contacts) > 0:
                return type('Friend', (), {
                    'wxid': wxid,
                    'nickname': contacts[0]["NickName"]
                })
            return None
        except Exception as e:
            self.LOG.error(f"获取好友信息失败：{e}")
            return None

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(f"Hi {nickName[0]}，我自动通过了你的好友请求。", msg.sender)

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)

    def _handle_forward_admin_msg(self, msg: WxMsg) -> bool:
        """处理转发管理员的消息"""
        if msg.content == "转发":
            if msg.sender == self.forward_admin:
                self.forward_state = ForwardState.WAITING_CHOICE_MODE
                self.sendTextMsg("已进入转发模式。\n如果希望刷新群聊列表，回复刷新列表。\n如果希望删除缓存，回复删除缓存。\n🌟如果想直接转发，回复1。", msg.sender)
                return True
            else:
                self.sendTextMsg("对不起，你未开通转发权限，私聊大松获取。", msg.sender)
                return False
            
        elif self.forward_state == ForwardState.WAITING_CHOICE_MODE:
            if msg.content == "1":
                self.forward_state = ForwardState.WAITING_MESSAGE
                self.forward_message = []  # 初始化为列表，用于存储多条消息
                self.sendTextMsg("请发送需要转发的内容（类型可以是公众号推文、视频号视频、文字、图片，数量不限），完成后回复选择群聊。", msg.sender)
                return True
            return False
            
        elif self.forward_state == ForwardState.WAITING_MESSAGE:
            if msg.content == "选择群聊":
                self.forward_state = ForwardState.WAITING_CHOICE
                # 获取并显示所有可用列表
                lists = self.notion_manager.get_all_lists()
                response = "请选择转发列表编号：\n"
                for lst in lists:
                    response += f"{lst.list_id}. {lst.list_name} ({lst.description})\n"
                self.sendTextMsg(response, msg.sender)
            else:
                self.forward_message.append(msg)  # 将消息添加到列表中
                return True
                
        elif self.forward_state == ForwardState.WAITING_CHOICE:
            try:
                list_id = int(msg.content)
                if self.forward_message:
                    groups = self.notion_manager.get_groups_by_list_id(list_id)
                    for group in groups:
                        for fwd_msg in self.forward_message:
                            self._forward_message(fwd_msg, group)
                    self.sendTextMsg(f"已转发 {len(self.forward_message)} 条消息到 {len(groups)} 个群", msg.sender)
                
                self.forward_state = ForwardState.IDLE
                self.forward_message = None
                return True
            except ValueError:
                self.sendTextMsg("请输入正确的列表编号", msg.sender)
                return True
                
        return False

    def _forward_message(self, msg: WxMsg, group: str) -> None:
        """转发消息到指定群"""
        try:
            if msg.type == 0x01:  # 文本消息
                self.wcf.send_text(msg.content, group)
            elif msg.type == 0x03:  # 图片消息
                self.wcf.send_image(msg.file, group)
            elif msg.type == 0x25:  # 链接消息
                self.wcf.send_xml(msg.content, group)
            elif msg.type == 0x2B:  # 视频号视频
                self.wcf.send_xml(msg.content, group)
            # 可以根据需要添加更多消息类型的支持
            time.sleep(random.uniform(1, 2))  # 添加随机延迟，避免频率过快
        except Exception as e:
            self.LOG.error(f"转发消息到群 {group} 失败: {e}")
