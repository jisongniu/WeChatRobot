from typing import Optional, List, Dict
from enum import Enum
from .notion_manager import NotionManager
import logging
import time
import random
from configuration import Configuration as Config
import os
from wcferry import WxMsg
from threading import Lock
from datetime import datetime, timedelta
from dataclasses import dataclass
from queue import Queue
import threading
from .welcome_service import WelcomeService

logger = logging.getLogger(__name__)

class ForwardState(Enum):
    IDLE = "idle"
    WAITING_CHOICE_MODE = "waiting_choice_mode"
    WAITING_MESSAGE = "waiting_message"
    WAITING_CHOICE = "waiting_choice"
    WELCOME_MANAGE = "welcome_manage"  # 迎新消息管理状态
    WELCOME_GROUP_CHOICE = "welcome_group_choice"  # 选择要管理迎新消息的群

@dataclass
class OperatorState:
    """每个操作者的状态"""
    state: ForwardState = ForwardState.IDLE
    list_id: Optional[int] = None
    messages: List[WxMsg] = None
    current_group: Optional[str] = None  # 当前正在管理迎新消息的群ID

    def __post_init__(self):
        if self.messages is None:
            self.messages = []

class NCCManager:
    def __init__(self, notion_manager: NotionManager, wcf):
        self.notion_manager = notion_manager
        self.wcf = wcf
        self.welcome_service = WelcomeService(wcf)  # 初始化迎新服务
        self.images_dir = os.path.join(os.path.dirname(__file__), "ncc_images")
        if not os.path.exists(self.images_dir):
            os.makedirs(self.images_dir)
        self.image_lock = Lock()
        self.operator_states: Dict[str, OperatorState] = {}  # 每个操作者的状态
        
        # 添加消息队列和处理线程
        self.forward_queue = Queue()
        self.forward_thread = threading.Thread(target=self._process_forward_queue, daemon=True)
        self.forward_thread.start()

    def _get_operator_state(self, operator_id: str) -> OperatorState:
        """获取操作者的状态，如果不存在则创建"""
        if operator_id not in self.operator_states:
            self.operator_states[operator_id] = OperatorState()
        return self.operator_states[operator_id]

    def _send_menu(self, receiver):
        """发送NCC管理菜单"""
        menu = (
            "NCC社群管理：\n"
            "请回复指定数字\n"
            "1 👈 转发消息\n"
            "2 👈 同步 Notion 更改\n"
            "3 👈 查看 Notion 后台\n"
            "4 👈 查看团队成员\n"
            "5 👈 迎新消息管理\n"
            "0 👈 退出管理模式"
        )
        self.sendTextMsg(menu, receiver)
        
    def handle_message(self, msg) -> bool:
        """统一处理所有NCC相关消息"""
        # 添加调试日志
        #logger.info(f"handle_message 收到消息: type={msg.type}, content={msg.content}")
        
        if msg.content.lower() == "ncc":
            admin_wxids = self.notion_manager.get_admins_wxid()
            if msg.sender in admin_wxids:
                operator_state = self._get_operator_state(msg.sender)
                operator_state.state = ForwardState.WAITING_CHOICE_MODE
                self._send_menu(msg.sender)
                return True
            else:
                self.sendTextMsg("对不起，你未开通ncc管理权限，私聊大松获取。", msg.sender)
                return False

        # 获取操作者的状态
        operator_state = self.operator_states.get(msg.sender)
        if operator_state and operator_state.state != ForwardState.IDLE:
            return self._handle_forward_state(msg, operator_state)
        
        return False

    def _handle_forward_state(self, msg: WxMsg, operator_state: OperatorState) -> bool:
        """处理不同状态下的消息"""
        # 在任何状态下都可以退出
        if msg.content == "0":
            self._reset_operator_state(msg.sender)
            self.sendTextMsg("已退出管理模式", msg.sender)
            return True

        if operator_state.state == ForwardState.WAITING_CHOICE_MODE:
            if msg.content == "5":  # 处理迎新消息管理选项
                operator_state.state = ForwardState.WELCOME_GROUP_CHOICE
                # 获取所有启用了迎新推送的群组
                groups = self.welcome_service.load_groups_from_local()
                if not groups:
                    self.sendTextMsg("未找到启用迎新推送的群组，请先在Notion的群管理页面开启迎新推送开关", msg.sender)
                    self._reset_operator_state(msg.sender)
                    return True
                
                response = "所有开启迎新推送的群聊列表：\n（迎新消息开关请在Notion的群管理页面操作）\n\n"
                for i, group in enumerate(groups, 1):
                    response += f"{i} 👈 {group['name']}\n"
                response += "\n请回复数字选择要管理的群聊，回复0退出"
                self.sendTextMsg(response, msg.sender)
                return True
            elif msg.content == "2":
                self.notion_manager.update_notion_data()
                # 发送菜单以供选择
                self.sendTextMsg("同步成功，请选择操作", msg.sender)
                self._send_menu(msg.sender)
                return True
            elif msg.content == "1":
                operator_state.state = ForwardState.WAITING_MESSAGE
                operator_state.messages = []
                self.sendTextMsg("请发送需要转发的内容，支持公众号、推文、视频号、文字、图片、合并消息，一个一个来\n发送【选择群聊】进入下一步\n随时发送【0】退出转发模式", msg.sender)
                return True
            elif msg.content == "3":
                self.sendTextMsg("列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4", msg.sender)
                return True
            elif msg.content == "4":
                # 获取管理员称呼列表
                admin_names = self.notion_manager.get_admin_names()
                admin_list = "成员：\n" + "\n".join(f"👤 {name}" for name in admin_names)
                self.sendTextMsg(admin_list, msg.sender)
                return True
            else:
                self.sendTextMsg("请输入有效的选项，或发送【0】退出转发模式", msg.sender)
            return True
        
        #信息收集阶段
        elif operator_state.state == ForwardState.WAITING_MESSAGE:
            # 添加调试日志
            logger.debug(f"收到消息，类型: {msg.type}, 内容: {msg.content}")
            
            if msg.content == "选择群聊":
                if not operator_state.messages:
                    self.sendTextMsg("还未收集到任何消息，请先发送需要转发的内容", msg.sender)
                    return True
                
                operator_state.state = ForwardState.WAITING_CHOICE
                lists = self.notion_manager.get_forward_lists_and_groups()
                if not lists:
                    self.sendTextMsg("未找到可用的转发列表，请先使用【刷新列表】更新数据", msg.sender)
                    self._reset_operator_state(msg.sender)
                    return True
                    
                response = f"已收集 {len(operator_state.messages)} 条消息\n请选择想要转发的分组编号，按0退出：\n"
                # 添加"所有群聊"选项
                response += f"1 👈 所有群聊\n"
                # 遍历列表，筛选符合条件的群聊
                for lst in lists:
                    response += f"{lst.list_id} 👈 {lst.list_name}\n"
                # 发送群聊列表给发送者，以供选择
                self.sendTextMsg(response, msg.sender)
                return True
            
            try:
                # 只有图片消息需要特殊处理（提前下载）
                if msg.type == 3:
                    self.sendTextMsg("检测到图片消息，原图上传有点慢，等会儿，好了叫你", msg.sender)
                    img_path = self.wcf.download_image(msg.id, msg.extra, self.images_dir, timeout=120)
                    if not img_path or not os.path.exists(img_path):
                        self.sendTextMsg("图片下载失败，请检查图片是否正常", msg.sender)
                        return True
                    logger.info(f"图片下载成功: {img_path}")
                
                # 所有消息都直接添加到收集器
                operator_state.messages.append(msg)
                logger.info(f"消息已添加到收集器，当前数量: {len(operator_state.messages)}")
                self.sendTextMsg(f"已收集 {len(operator_state.messages)} 条消息，继续发送或者：选择群聊", msg.sender)
                
            except TimeoutError:
                logger.error("图片下载超时")
                self.sendTextMsg("图片下载超时，请稍后重试", msg.sender)
            except Exception as e:
                logger.error(f"消息收集失败: {e}", exc_info=True)  # 添加完整的异常堆栈
                self.sendTextMsg("消息收集异常，请联系管理员", msg.sender)
            return True

        #转发阶段    
        elif operator_state.state == ForwardState.WAITING_CHOICE:
            try:
                list_id = int(msg.content)
                if operator_state.messages:
                    groups = []
                    if list_id == 1:  # 处理"所有群聊"选项
                        # 获取所有启用了转发的群组
                        lists = self.notion_manager.get_forward_lists_and_groups()
                        print(f"lists有这些：{lists}")
                        # 从所有列表的所有群组中，提取出有效的 wxid，去重后存储到 forward_groups
                        forward_groups = list(set(
                            group['wxid'] for lst in lists 
                            for group in lst.groups 
                            if group.get('wxid')  # 确保只包含有效的 wxid
                        ))
                        print(f"forward_groups有这些：{forward_groups}")
                        if not forward_groups:
                            self.sendTextMsg("未找到任何可转发的群组，请重新选择，或发送【0】退出转发模式", msg.sender)
                            return True
                        groups = forward_groups
                    else:
                        groups = self.notion_manager.get_groups_by_list_id(list_id)
                        if not groups:
                            self.sendTextMsg(f"未找到ID为 {list_id} 的列表或列表中没有有效的群组，请重新选择，或发送【0】退出转发模式", msg.sender)
                            return True
                        
                    total_groups = len(groups)
                    total_messages = len(operator_state.messages)
                    
                    self.sendTextMsg(f"开始转发 {total_messages} 条消息到 {total_groups} 个群...\n为避免风控，将会添加随机延迟，请耐心等待...", msg.sender)
                    
                    # 将转发任务添加到队列
                    self.forward_queue.put((operator_state.messages, groups, msg.sender))
                    self._reset_operator_state(msg.sender)
                
                return True
                
            except ValueError:
                self.sendTextMsg("请输入有效的选项，或发送【0】退出转发模式", msg.sender)
                return True
                
        elif operator_state.state == ForwardState.WELCOME_GROUP_CHOICE:
            try:
                choice = int(msg.content)
                if choice == 0:
                    self._reset_operator_state(msg.sender)
                    self.sendTextMsg("已退出迎新消息管理", msg.sender)
                    return True

                groups = self.welcome_service.load_groups_from_local()
                if 1 <= choice <= len(groups):
                    group = groups[choice - 1]
                    operator_state.current_group = group['wxid']
                    operator_state.state = ForwardState.WELCOME_MANAGE
                    # 调用迎新消息管理功能，并等待其完成
                    self.welcome_service.manage_welcome_messages(group['wxid'], msg.sender)
                    # 完成后重置状态
                    self._reset_operator_state(msg.sender)
                    return True
                else:
                    self.sendTextMsg("无效的选择，请重新输入", msg.sender)
                return True
            except ValueError:
                self.sendTextMsg("请输入有效的数字", msg.sender)
                return True

        # 如果状态是WELCOME_MANAGE，消息应该由welcome_service处理
        elif operator_state.state == ForwardState.WELCOME_MANAGE:
            return self.welcome_service.handle_message(msg)

        return False
    
    def _forward_message(self, msg: WxMsg, receiver: str) -> bool:
        """根据消息类型选择合适的转发方式"""
        if msg.type == 3:  # 图片消息
            try:
                with self.image_lock:  # 只锁定发送过程
                    img_path = os.path.join(self.images_dir, f"{msg.id}_{msg.extra}")
                    if os.path.exists(img_path):
                        if self.wcf.send_image(img_path, receiver) == 0:
                            time.sleep(0.5)  # 等待发送完成
                            return True
            except Exception as e:
                logger.error(f"图片发送失败: {e}")
                return False
            
            # 如果发送失败，尝试直接转发
            return self.wcf.forward_msg(msg.id, receiver) == 1
        
        # 其他类型消息使用 forward_msg
        return self.wcf.forward_msg(msg.id, receiver) == 1
    
    def _reset_operator_state(self, operator_id: str) -> None:
        """重置特定操作者的状态"""
        if operator_id in self.operator_states:
            del self.operator_states[operator_id]

    def sendTextMsg(self, msg: str, receiver: str) -> None:
        """发送文本消息"""
        self.wcf.send_text(msg, receiver)

    def _process_forward_queue(self):
        """处理转发队列的后台线程"""
        while True:
            try:
                # 从队列获取转发任务
                task = self.forward_queue.get()
                if task is None:
                    continue
                    
                messages, groups, operator_id = task
                total_groups = len(groups)
                total_messages = len(messages)
                
                success_count = 0
                failed_count = 0
                
                # 为每个群添加随机延迟
                for i, group in enumerate(groups):
                    # 每个群之间的基础延迟3-5秒
                    group_delay = random.uniform(3, 5)
                    
                    # 每10个群增加额外延迟5-10秒，避免频繁发送
                    if i > 0 and i % 10 == 0:
                        extra_delay = random.uniform(5, 10)
                        time.sleep(extra_delay)
                        
                    for msg in messages:
                        if self._forward_message(msg, group):
                            success_count += 1
                        else:
                            failed_count += 1
                        # 每条消息间隔1-2秒
                        time.sleep(random.uniform(1, 2))
                    
                    time.sleep(group_delay)
                    
                
                # 发送最终结果
                status = f"转发完成！\n成功：{success_count} 条\n失败：{failed_count} 条\n总计：{total_messages} 条消息到 {total_groups} 个群"
                self.sendTextMsg(status, operator_id)
                
            except Exception as e:
                logging.error(f"处理转发队列时出错: {e}")
            finally:
                self.forward_queue.task_done()

    
