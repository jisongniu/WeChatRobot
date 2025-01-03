# -*- coding: utf-8 -*-

import logging
import re
import time
import random  
import os
import json
from queue import Empty
from threading import Thread
from typing import List, Optional

from wcferry import Wcf, WxMsg

from base.func_bard import BardAssistant
from base.func_chatglm import ChatGLM
from base.func_chatgpt import ChatGPT
from base.func_chengyu import cy
from base.func_fastgpt import FastGPT
from base.func_tigerbot import TigerBot
from base.func_xinghuo_web import XinghuoWeb
from base.func_music import MusicService
from base.func_feishu import FeishuBot

from configuration import Config
from constants import ChatType, FRIEND_WELCOME_MSG
from job_mgmt import JobManager
from ncc.notion_manager import NotionManager
from ncc.ncc_manager import NCCManager, ForwardState
from ncc.welcome_service import WelcomeService
from ncc.invite_group import InviteService
from ncc.db_manager import DatabaseManager

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
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
        self.processed_msgs = set()  # 添加消息去重集合
        self.job_mgr = JobManager(wcf, self)
        self.music_service = MusicService(wcf)  # 初始化音乐服务

        # 确保数据目录存在
        os.makedirs("data", exist_ok=True)
        
        # 初始化数据库管理器
        self.db = DatabaseManager()
        
        # 初始化 Notion 管理器
        self.notion_manager = NotionManager(
            token=config.NOTION["TOKEN"],
            lists_db_id=config.NOTION["LISTS_DB_ID"],
            groups_db_id=config.NOTION["GROUPS_DB_ID"],
            admins_db_id=config.NOTION["ADMINS_DB_ID"],
            keywords_db_id=config.NOTION["KEYWORDS_DB_ID"],
            wcf=self.wcf,
            config=config)
        
        # 初始化时更新一次 Notion 数据
        self.notion_manager.fetch_notion_data()
        
        # 初始化允许的群组列表
        speak_enabled_groups = self.db.get_speak_enabled_groups()
        self.allowed_groups = [group['wxid'] for group in speak_enabled_groups]
        
        # 初始化 NCC 管理器
        self.ncc_manager = NCCManager(
            robot=self,
            notion_manager=self.notion_manager,
            wcf=self.wcf)
        
        # 初始化关键词邀请服务
        self.invite_service = InviteService(
            wcf=self.wcf,
            notion_manager=self.notion_manager)

        # 初始化飞书机器人
        self.feishu_bot = None
        if self.config.FEISHU_BOT.get("webhook"):
            self.feishu_bot = FeishuBot(
                self.config.FEISHU_BOT["webhook"],
                wcf,
                self.notion_manager,
                self.ncc_manager)
        
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
            self.LOG.error("无法从配置的LLm模型获得答案")
            return False  # 返回处理失败

    def processMsg(self, msg: WxMsg) -> None:
        """处理消息"""
        try:
            # 1. 处理自己发送的消息
            if msg.from_self():
                if msg.type == 0x01 and msg.content == "*更新":  # 只处理文本消息的更新命令
                    self.config.reload()
                    self.sync_data_from_notion()
                return
            
            # 2. 处理定时任务命令
            result = self.job_mgr.handle_command(msg.content, msg.sender)
            if result:
                self.sendTextMsg(result, msg.roomid if msg.from_group() else msg.sender)
                return
            
            # 3. 处理系统消息
            if msg.type == 10000:
                if msg.from_group():  # 群系统消息
                    # 1. 检测群名修改
                    name_change = re.search(r'修改群名为\u201c(.*?)\u201d', msg.content)
                    if name_change:
                        new_name = name_change.group(1)
                        # 更新数据库中的群名
                        self.db.update_groups([{
                            'wxid': msg.roomid,
                            'name': new_name,
                            'welcome_enabled': True,
                            'allow_forward': True,
                            'allow_speak': True
                        }])
                        
                        # 更新 Notion
                        self.notion_manager.create_new_group(msg.roomid, new_name)
                        
                        # 发送飞书通知
                        if self.feishu_bot:
                            self.feishu_bot.notify(f"群 {msg.roomid} 的名称已更新为：{new_name}，数据库和 Notion 都已更新")
                    
                    # 2. 检测新群邀请
                    elif re.search(r".*邀请你加入了群聊", msg.content):
                        # 获取群名称
                        group_info = self.wcf.query_sql(
                            "MicroMsg.db",
                            f"SELECT NickName FROM Contact WHERE UserName='{msg.roomid}';"
                        )
                        if group_info and len(group_info) > 0:
                            group_name = group_info[0]["NickName"]
                            # 创建新群组记录
                            self.notion_manager.create_new_group(msg.roomid, group_name)
                            # 发送飞书通知
                            if self.feishu_bot:
                                self.feishu_bot.notify(f"已将群聊 {group_name} ({msg.roomid}) 添加到 Notion")
                    
                    # 3. 检测新成员加入
                    else:
                        self.welcome_service.handle_message(msg)
                
                else:  # 私聊系统消息
                    self.sayHiToNewFriend(msg)
                    
                return
            
            # 4. 处理群聊消息
            if msg.from_group():
                # 非允许群聊，直接返回
                if msg.roomid not in self.allowed_groups:
                    return

                # 处理允许群聊的文字消息
                if msg.type == 0x01 and not msg.from_self():
                    # 1. 处理被艾特或问题消息
                    if msg.content.startswith("@肥肉") or msg.is_at(self.wxid) or msg.content.startswith("问："):
                        self.LOG.info(f"在被允许的群聊中被艾特或被问，处理消息")
                        # 清理消息内容
                        cleaned_content = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
                        cleaned_content = cleaned_content.replace("问：", "")
                        
                        def process_ai_reply():
                            msg.content = cleaned_content
                            self.toAIchat(msg)
                        Thread(target=process_ai_reply, name="AIReply").start()
                        return
                    
                    # 2. 处理关键词"肥肉"
                    if "肥肉" in msg.content and not msg.content.startswith("@肥肉") and not msg.is_at(self.wxid):
                        self.LOG.info(f"触发关键词肥肉且没有被艾特")
                        def delayed_msg():
                            # 先拍一拍
                            self.wcf.send_pat_msg(msg.roomid, msg.sender)
                            # 然后调用 toai
                            self.toAIchat(msg)
                        Thread(target=delayed_msg, name="PatAndMsg").start()
                        return
                    
                    # 3. 处理点歌命令
                    if "点歌" in msg.content:
                        self.LOG.info(f"触发关键词点歌")
                        self.toMusic(msg)
                        return
                return
            
            # 接下来处理私聊消息
            # 1. 优先处理 NCC 命令
            operator_state = self.ncc_manager.operator_states.get(msg.sender)
            if msg.content.lower() == "ncc" or (operator_state and operator_state.state != ForwardState.IDLE) or msg.sender == "wxid_kscqqrkpg39121":
                if self.ncc_manager.handle_message(msg):
                    return
            
            # 2. 处理点歌命令
            if "点歌" in msg.content:
                self.LOG.info(f"触发关键词点歌")
                self.toMusic(msg)
                return
                
            # 3. 处理关键词邀请
            if self.invite_service.handle_keyword(msg.content, msg.sender):
                #处理成功，返回
                return
            
            # 4. 触发肥肉关键词交给 AI 处理
            if "肥肉" in msg.content:
                self.toAIchat(msg)
                return
            
            # 5. 其他文字消息触发：
            else:
                self.sendTextMsg('hey～如果你想和肥肉聊天的话，发送内容需要包含"肥肉"哦～', msg.sender)
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
            delay = random.uniform(1, 5)  # 随机 1-5 秒延迟
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
                    'nickname': contacts[wxid]
                })
            return None
        except Exception as e:
            self.LOG.error(f"获取好友信息失败：{e}")
            return None

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        """处理新好友入群后的欢迎消息"""
        if "以上是打招呼的内容" in msg.content:
            self.sendTextMsg(FRIEND_WELCOME_MSG, msg.sender)
            # 发送飞书通知，添加了新好友，发送欢迎消息
            if self.feishu_bot:
                self.feishu_bot.notify("有人来加肥肉，发送欢迎消息", msg.sender, msg.content, msg.sender, False)

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

    def sync_data_from_notion(self) -> None:
        """从 Notion 同步数据并更新到程序中
        1. 更新 Notion 数据到数据库
        2. 更新内存中的群组列表
        3. 更新欢迎服务的群组配置
        """
        # 先更新 Notion 数据到数据库
        self.notion_manager.fetch_notion_data()
        # 然后更新内存中的群组列表
        speak_enabled_groups = self.db.get_speak_enabled_groups()
        self.allowed_groups = [group['wxid'] for group in speak_enabled_groups]
        # 更新欢迎服务的群组配置
        self.welcome_service.load_groups_from_local()
        self.LOG.info("已更新配置和数据")
