# -*- coding: utf-8 -*-

import logging
import re
import time
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread
# from base.func_zhipu import ZhiPu  # 不需要zhipu的话就不用
from enum import Enum, auto
from typing import List, Optional

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
from ncc.notion_manager import NotionManager
from ncc.ncc_manager import NCCManager, ForwardState
from ncc.welcome_service import WelcomeService  # 添加导入
import random  
import os

__version__ = "39.3.3.2"


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int = 0):
        """初始化机器人
        
        Args:
            config (Config): 配置对象
            wcf (Wcf): wcf对象
            chat_type (int, optional): 聊天类型. Defaults to 0.
        """
        super().__init__()
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self.processed_msgs = set()  # 添加消息去重集合
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
            # elif chat_type == ChatType.ZhiPu.value and ZhiPu.value_check(self.config.ZhiPu):
            #     self.chat = ZhiPu(self.config.ZhiPu)
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
            # elif ZhiPu.value_check(self.config.ZhiPu):
            #     self.chat = ZhiPu(self.config.ZhiPu)
            else:
                self.LOG.warning("未配置模型")
                self.chat = None


        # 确保数据目录存在
        os.makedirs("data", exist_ok=True)
        
        self.notion_manager = NotionManager(
            token=self.config.NOTION['TOKEN'],
            lists_db_id=self.config.NOTION['LISTS_DB_ID'],
            groups_db_id=self.config.NOTION['GROUPS_DB_ID'],
            wcf=self.wcf
        )
        # 初始化时加载一次群组列表
        self.allowed_groups = self.notion_manager.get_all_allowed_groups()
        
        self.ncc_manager = NCCManager(
            notion_manager=self.notion_manager,
            config=self.config,
            wcf=self.wcf
        )
        
        # 添加 WelcomeService 初始化
        self.welcome_service = WelcomeService(wcf=self.wcf)
        # 加载群组配置
        self.welcome_service.load_groups_from_local()
        
        self.forward_admin = config.FORWARD_ADMINS

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False



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
    
    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        return self.toAIchat(msg)

    def toAIchat(self, msg: WxMsg) -> bool:
        """AI模式
        """
        # 如果没有配置 ChatGPT，返回固定回复
        if not self.chat:
            rsp = self.toChitchat(msg)
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
        
        
    def toChitchat(self, msg: WxMsg) -> bool:
        """
        处理闲聊消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        rsp = None
        if msg.content.startswith("问：") or msg.content.startswith("【问：】"):
            # 移除前缀
            msg.content = msg.content.replace("问：", "").replace("【问：】", "")
            return self.toAIchat(msg)
        elif "机器" in msg.content:
            rsp = "有事【问：】开头，没事憋找我，滚。"
        else:
            rsp = None  # 不回复
            
        if rsp:  # 只有在有响应时才发送
            self.sendTextMsg(rsp, msg.roomid if msg.from_group() else msg.sender)
            return True
            
        return False
        

    

    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """
        #被艾特或者被问：
        if msg.is_at(self.wxid) or msg.content.startswith("问："):  # 被@的话
            if msg.from_group() and msg.roomid not in self.allowed_groups:
                return  # 如果是群消息且群不在允许列表中，直接返回
            self.toAt(msg)  # 否则处理消息


        # 非群聊信息，按消息类型进行处理

        # 好友请求,已经被 not implemented 了
        # if msg.type == 37:  
        #     self.handle_friend_request(msg)
        #     return

        elif msg.type == 10000:  # 系统消息
            if msg.from_group():  # 是群消息
                is_join, member_name = self.welcome_service.is_join_message(msg)
                if is_join:
                    self.welcome_service.send_welcome(msg.roomid, member_name)
                    return
            else:  # 不是群消息，可能是好友申请通过
                self.sayHiToNewFriend(msg)
                return

        # 处理自己发送的消息
        if msg.from_self():
            if msg.type == 0x01 and msg.content == "*更新":  # 只处理文本消息的更新命令
                self.config.reload()
                self.allowed_groups = self.notion_manager.get_all_allowed_groups()
                # 添加欢迎配置更新
                self.welcome_service.load_groups_from_local()
                self.LOG.info("已更新")
            return

        # 处理 NCC 命令（仅限私聊）
        if msg.content.lower() == "ncc" or self.ncc_manager.forward_state != ForwardState.IDLE:
            if self.ncc_manager.handle_message(msg):
                    return

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
        """ 送消息
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
        """处理好友请求"""
        try:
            # 构造消息ID并检查是否处理过
            msg_id = f"{msg.type}_{msg.id}_{msg.ts}"
            if msg_id in self.processed_msgs:
                self.LOG.info(f"好友请求已处理过，跳过: {msg_id}")
                return
            
            # 添加到已处理集合（提前添加防止并发）
            self.processed_msgs.add(msg_id)
            
            # 解析消息内容
            xml_content = msg.content
            self.LOG.info(f"收到新好友请求: {xml_content}")
            
            # 提取验证信息
            v3_match = re.search(r'encryptusername="([^"]*)"', xml_content)
            v4_match = re.search(r'ticket="([^"]*)"', xml_content)
            scene_match = re.search(r'scene="(\d+)"', xml_content)
            
            if not (v3_match and v4_match and scene_match):
                self.LOG.error("无法从消息中提取必要的验证信息")
                return
            
            v3 = v3_match.group(1)
            v4 = v4_match.group(1)
            scene = int(scene_match.group(1))
            
            def delayed_accept():
                try:
                    delay = random.randint(MIN_ACCEPT_DELAY, MAX_ACCEPT_DELAY)
                    self.LOG.info(f"将在{delay}秒后通过好友请求")
                    time.sleep(delay)
                    
                    result = self.wcf.accept_new_friend(v3, v4, scene)
                    self.LOG.info(f"通过好友请求结果: {result}")
                    
                    if result == 1:
                        self.LOG.info("好友请求通过成功")
                    else:
                        self.LOG.warning(f"好友请求通过失败，返回值: {result}")
                    
                except Exception as e:
                    self.LOG.error(f"处理好友请求失败：{e}", exc_info=True)
                    self.LOG.debug(f"处理好友请求失败的详细信息: {e}")
            
            Thread(target=delayed_accept, name="AcceptFriend").start()
                
        except Exception as e:
            self.LOG.error(f"处理好友请求主流程异常：{e}", exc_info=True)

    def accept_friend_request(self, msg):
        """通过好友请求"""
        try:
            self.LOG.info(f"处理好友请求消息: {msg.content}")
            
            # 使用正则表达式提取 v3 和 v4
            v3_match = re.search(r'encryptusername="([^"]*)"', msg.content)
            v4_match = re.search(r'ticket="([^"]*)"', msg.content)
            scene_match = re.search(r'scene="(\d+)"', msg.content)
            
            if not (v3_match and v4_match):
                self.LOG.error("无法从消息中提取必要的验证信息")
                self.LOG.debug(f"消息内容: {msg.content}")
                return
            
            v3 = v3_match.group(1)
            v4 = v4_match.group(1)
            scene = int(scene_match.group(1)) if scene_match else 30  # 如果没有scene，默认使用30
            
            self.LOG.info(f"提取的验证信息: v3={v3}, v4={v4}, scene={scene}")
            
            # 调用 wcf 的接口通过好友请求
            result = self.wcf.accept_new_friend(v3, v4, scene)
            
            if result == 1:
                self.LOG.info("已成功通过好友请求")
            else:
                self.LOG.error(f"通过好友请求失败，返回值: {result}")
            
        except Exception as e:
            self.LOG.error(f"处理好友请求异常: {e}", exc_info=True)
    
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
        """处理新好友入群后的欢迎消息"""
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(FRIEND_WELCOME_MSG, msg.sender)  

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)
