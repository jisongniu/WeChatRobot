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
from base.func_fastgpt import FastGPT  # 添加FastGPT导入
from base.func_news import News
from base.func_tigerbot import TigerBot
from base.func_xinghuo_web import XinghuoWeb
from configuration import Config
from constants import ChatType, MIN_ACCEPT_DELAY, MAX_ACCEPT_DELAY, FRIEND_WELCOME_MSG
from job_mgmt import JobManager
from ncc.notion_manager import NotionManager
from ncc.ncc_manager import NCCManager, ForwardState
from ncc.welcome_service import WelcomeService  # 添加导入
import random  
import os
from base.func_music import MusicService
from base.func_feishu import FeishuBot  # 添加导入

__version__ = "39.3.3.2"


class Robot:
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int = 0):
        """初始化机器人
        
        Args:
            config (Config): 配置对象
            wcf (Wcf): wcf对象
            chat_type (int, optional): 聊天类型. Defaults to 0.
        """
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self.processed_msgs = set()  # 添加消息去重集合
        self.job_mgr = JobManager(wcf, self)
        self.music_service = MusicService(wcf)  # 初始化音乐服务

        # 确保数据目录存在
        os.makedirs("data", exist_ok=True)
        
        self.notion_manager = NotionManager(
            token=config.NOTION["TOKEN"],
            lists_db_id=config.NOTION["LISTS_DB_ID"],
            groups_db_id=config.NOTION["GROUPS_DB_ID"],
            admins_db_id=config.NOTION["ADMINS_DB_ID"],
            wcf=self.wcf
        )
        
        # 初始化时更新一次 Notion 数据
        self.notion_manager.update_notion_data()
        # 初始化允许的群组列表
        self.allowed_groups = self.notion_manager.get_all_allowed_groups()
        
        self.ncc_manager = NCCManager(
            notion_manager=self.notion_manager,
            wcf=self.wcf
        )

        # 初始化飞书机器人
        self.feishu_bot = None
        if self.config.FEISHU_BOT.get("webhook"):
            self.feishu_bot = FeishuBot(
                self.config.FEISHU_BOT["webhook"],
                wcf,
                self.notion_manager,
                self.ncc_manager
            )
        
        # 添加 WelcomeService 初始化
        self.welcome_service = WelcomeService(wcf=self.wcf)
        # 加载群组配置
        self.welcome_service.load_groups_from_local()

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
            elif chat_type == ChatType.FASTGPT.value and FastGPT.value_check(self.config.FASTGPT):
                self.chat = FastGPT(self.config.FASTGPT)
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
            elif FastGPT.value_check(self.config.FASTGPT):
                self.chat = FastGPT(self.config.FASTGPT)
            # elif ZhiPu.value_check(self.config.ZhiPu):
            #     self.chat = ZhiPu(self.config.ZhiPu)
            else:
                self.LOG.warning("未配置模型")
                self.chat = None

    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙息
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

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def toAIchat(self, msg: WxMsg) -> bool:
        """AI模式
        """
        self.LOG.info("正在查询ai获取回复")
        rsp = self.chat.get_answer(msg.content, (msg.roomid if msg.from_group() else msg.sender))

        # 如果获取到了回复，发送回复
        if rsp:
            # 如果是群聊，发送回复到群聊，并 @ 发送者
            if msg.from_group():
                self.sendTextMsg(rsp, msg.roomid, msg.sender)
                # 发送飞书通知
                if self.feishu_bot:
                    self.feishu_bot.notify(rsp, msg.roomid, msg.content, msg.sender, True)
            else:  # 如果是私聊，直接发送回复
                self.sendTextMsg(rsp, msg.sender)
                # 发送飞书通知
                if self.feishu_bot:
                    self.feishu_bot.notify(rsp, msg.sender, msg.content, msg.sender, False)
            return True  # 返回处理成功
        else:  # 如果没有获取到回复，记录错误日志
            self.LOG.error(f"无法从配置的LLm模型获得答案")
            return False  # 返回处理失败
        
        

    

    def processMsg(self, msg: WxMsg) -> None:
        """当收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """
        try:
            # 处理定时任务命令
            result = self.job_mgr.handle_command(msg.content, msg.sender)
            if result:
                self.sendTextMsg(result, msg.roomid if msg.from_group() else msg.sender)
                return
            
            # 检查被允许群聊里文字消息
            if msg.from_group() and msg.roomid in self.allowed_groups and msg.type == 0x01 and not msg.from_self():
                # 类型1—— 被艾特或者以问：开头
                if msg.content.startswith("@肥肉") or msg.is_at(self.wxid) or msg.content.startswith("问："):
                    self.LOG.info(f"在被允许的群聊中被艾特或被问，处理消息")  
                    # 从消息内容中移除 @ 和空格，得到问题
                    cleaned_content = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
                    # 移除前缀
                    cleaned_content = cleaned_content.replace("问：", "")
                    
                    def process_ai_reply():
                        # 通过 ai 获取答案
                        msg.content = cleaned_content  # 修改msg.content为清理后的内容
                        self.toAIchat(msg)
                        
                    Thread(target=process_ai_reply, name="AIReply").start()
                    return
                
                # 类型2—— 触发关键词肥肉
                if "肥肉" in msg.content and not msg.content.startswith("@肥肉") and not msg.is_at(self.wxid):
                    self.LOG.info(f"触发关键词肥肉且没有被艾特")  # 被@的或者问的
                    def delayed_msg():
                        # 先拍一拍
                        self.wcf.send_pat_msg(msg.roomid, msg.sender)
                        # 然后调用 toai
                        self.toAIchat(msg)
                        
                    Thread(target=delayed_msg, name="PatAndMsg").start()
                    return  # 处理完肥肉关键词且没有被艾特就返回，不再处理其他逻辑
                
                # 类型3—— 触发关键词点歌
                if "点歌" in msg.content:
                    self.LOG.info(f"触发关键词点歌")
                    self.toMusic(msg)
                    return
                
            # 非群聊消息
            if not msg.from_group():
                
                # 类型1—— NCC 命令
                # 获取各个操作者的状态  
                operator_state = self.ncc_manager.operator_states.get(msg.sender)
                # 如果消息内容是 ncc 或者操作者状态不是 Idle
                if msg.content.lower() == "ncc" or (operator_state and operator_state.state != ForwardState.IDLE):
                    # 处理 NCC 命令
                    if self.ncc_manager.handle_message(msg):
                        return
                    

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



        except Exception as e:
            self.LOG.error(f"消息处理异常: {e}")

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    if msg:  # 确保消息不为空
                        self.LOG.info(msg)
                        self.processMsg(msg)
                except Empty:
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    continue
                except Exception as e:
                    self.LOG.error(f"处理消息异常: {e}")
                    time.sleep(1)  # 发生异常时等待较长时间

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        try:
            # 添加随机延迟
            delay = random.uniform(0.5, 1.5)  # 随机 0.5-1.5 秒延迟
            time.sleep(delay)
            
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

        except Exception as e:
            self.LOG.error(f"发送消息失败: {e}")

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
        同时检查定时任务
        """
        def check_jobs():
            """在独立线程中检查定时任务"""
            while True:
                try:
                    self.job_mgr.run_pending()
                    time.sleep(1)
                except Exception as e:
                    self.LOG.error(f"检查定时任务异常: {e}")
                    time.sleep(5)

        def check_wcf_alive():
            """检查wcf连接状态"""
            while True:
                try:
                    if not self.wcf.is_receiving_msg():
                        self.LOG.warning("消息接收已断开，尝试重新连接...")
                        self.wcf.enable_receiving_msg()
                    time.sleep(5)
                except Exception as e:
                    self.LOG.error(f"检查wcf状态异常: {e}")
                    time.sleep(5)

        try:
            # 启动定时任务检查线程
            job_thread = Thread(target=check_jobs, name="JobChecker", daemon=True)
            job_thread.start()
            
            # 启动wcf状态检查线程
            wcf_thread = Thread(target=check_wcf_alive, name="WcfChecker", daemon=True)
            wcf_thread.start()
            
            # 主循环
            while True:
                try:
                    time.sleep(1)
                except KeyboardInterrupt:
                    self.LOG.info("收到退出信号，正在退出...")
                    break
                except Exception as e:
                    self.LOG.error(f"主循环异常: {e}")
                    time.sleep(5)
                
        except Exception as e:
            self.LOG.error(f"keepRunningAndBlockProcess异常: {e}")
        finally:
            self.LOG.info("正在清理资源...")
            try:
                self.wcf.cleanup()
            except:
                pass

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
            # 添加了好友更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(FRIEND_WELCOME_MSG, msg.sender)  

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = News().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)

    def toMusic(self, msg: WxMsg) -> bool:
        """处理点歌消息
        Args:
            msg: 微信消息结构
        Returns:
            bool: 是否处理成功
        """
        return self.music_service.process_music_command(msg.content, msg.roomid)
