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
from .db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class ForwardState(Enum):
    IDLE = "idle"
    WAITING_CHOICE_MODE = "waiting_choice_mode"
    WAITING_MESSAGE = "waiting_message"
    WAITING_CHOICE = "waiting_choice"
    WELCOME_MANAGE = "welcome_manage"  # 迎新消息管理状态
    WELCOME_GROUP_CHOICE = "welcome_group_choice"  # 选择要管理迎新消息的群
    WELCOME_COLLECTING = "welcome_collecting"  # 收集新的迎新消息

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
    def __init__(self, robot, notion_manager: NotionManager, wcf):
        self.robot = robot  # 保存 robot 实例的引用
        self.notion_manager = notion_manager
        self.wcf = wcf
        self.welcome_service = WelcomeService(wcf)  # 初始化迎新服务
        self.db = DatabaseManager()  # 初始化数据库管理器
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
        if msg.content.lower().strip() == "ncc":
            admin_wxids = self.db.get_admin_wxids()
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
            if msg.content == "5":  # 进入迎新消息管理模式
                operator_state.state = ForwardState.WELCOME_GROUP_CHOICE
                # 获取所有启用了迎新推送的群组
                groups = self.db.get_welcome_enabled_groups()
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

            elif msg.content == "2":  # 同步 Notion 数据到本地缓存
                self.robot.sync_data_from_notion()  # 使用 robot 的同步方法
                self.sendTextMsg("同步成功，请选择操作", msg.sender)
                self._send_menu(msg.sender)
                return True
            elif msg.content == "1":  # 进入消息转发模式
                operator_state.state = ForwardState.WAITING_MESSAGE
                operator_state.messages = []
                self.sendTextMsg("请发送需要转发的内容，支持公众号、推文、视频号、文字、图片、合并消息，一个一个来\n发送【1】进入下一步\n随时发送【0】退出转发模式", msg.sender)
                return True
            elif msg.content == "3":  # 查看 Notion 后台链接
                self.sendTextMsg("列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4", msg.sender)
                return True
            elif msg.content == "4":  # 查看团队成员列表
                # 获取管理员称呼列表
                admin_names = self.db.get_admin_names()
                admin_list = "成员：\n" + "\n".join(f"👤 {name}" for name in admin_names)
                self.sendTextMsg(admin_list, msg.sender)
                return True
            else:
                self.sendTextMsg("请输入有效的选项，或发送【0】退出转发模式", msg.sender)
            return True
        
        #信息收集阶段
        elif operator_state.state == ForwardState.WAITING_MESSAGE:
            if msg.content == "1":
                if not operator_state.messages:
                    self.sendTextMsg("还未收集到任何消息，请先发送需要转发的内容", msg.sender)
                    return True
                
                operator_state.state = ForwardState.WAITING_CHOICE
                # 从数据库获取转发列表
                with self.db.get_db() as conn:
                    cur = conn.cursor()
                    cur.execute('''
                        SELECT list_id, list_name, description
                        FROM forward_lists
                        ORDER BY list_id
                    ''')
                    lists = cur.fetchall()
                
                if not lists:
                    self.sendTextMsg("未找到可用的转发列表，请先使用【刷新列表】更新数据", msg.sender)
                    self._reset_operator_state(msg.sender)
                    return True
                    
                response = f"已收集 {len(operator_state.messages)} 条消息\n请选择想要转发的分组编号项（支持多选，如：1+2+3），按0退出：\n\n"
                # 添加"所有群聊"选项
                response += f"1 👈 所有群聊\n"
                # 遍历列表
                for list_id, list_name, description in lists:
                    response += f"{list_id} 👈 {list_name}"
                    if description:
                        response += f" （{description}）"
                    response += "\n"
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
                self.sendTextMsg(f"已收集 {len(operator_state.messages)} 条消息，继续发送或者回复【1】选择群聊", msg.sender)
                
            except TimeoutError:
                logger.error("图片下载超时")
                self.sendTextMsg("图片下载超时，请稍后重试", msg.sender)
            except Exception as e:
                logger.error(f"消息收集失败: {e}", exc_info=True)
                self.sendTextMsg("消息收集异常，请联系管理员", msg.sender)
            return True

        #转发阶段    
        elif operator_state.state == ForwardState.WAITING_CHOICE:
            try:
                # 处理多选列表
                list_ids = [int(list_id.strip()) for list_id in msg.content.split("+")]
                
                if operator_state.messages:
                    groups = set()  # 使用集合来自动去重
                    
                    # 获取所有群组
                    with self.db.get_db() as conn:
                        cur = conn.cursor()
                        if 1 in list_ids:  # 如果选择了"所有群聊"
                            cur.execute('''
                                SELECT DISTINCT g.wxid 
                                FROM groups g
                                JOIN group_lists gl ON g.wxid = gl.group_wxid
                                WHERE g.allow_forward = 1
                            ''')
                        else:
                            placeholders = ','.join('?' * len(list_ids))
                            cur.execute(f'''
                                SELECT DISTINCT g.wxid 
                                FROM groups g
                                JOIN group_lists gl ON g.wxid = gl.group_wxid
                                WHERE gl.list_id IN ({placeholders}) 
                                AND g.allow_forward = 1
                            ''', list_ids)
                        groups = {row[0] for row in cur.fetchall()}
                    
                    if not groups:
                        self.sendTextMsg("未找到任何可转发的群组，请重新选择，或发送【0】退出转发模式", msg.sender)
                        return True
                        
                    total_groups = len(groups)
                    total_messages = len(operator_state.messages)
                    
                    self.sendTextMsg(f"开始转发 {total_messages} 条消息到 {total_groups} 个群...\n为避免风控，将会添加随机延迟，请耐心等待...", msg.sender)
                    
                    # 将转发任务添加到队列
                    self.forward_queue.put((operator_state.messages, list(groups), msg.sender))
                    self._reset_operator_state(msg.sender)
                
                return True
                
            except ValueError:
                self.sendTextMsg("请输入有效的选项（支持多选，如：1+2+3），或发送【0】退出转发模式", msg.sender)
                return True
                
        elif operator_state.state == ForwardState.WELCOME_GROUP_CHOICE:
            try:
                choice = int(msg.content)
                if choice == 0:  # 退出迎新消息管理
                    self._reset_operator_state(msg.sender)
                    self.sendTextMsg("已退出迎新消息管理", msg.sender)
                    return True

                groups = self.db.get_welcome_enabled_groups()
                if 1 <= choice <= len(groups):  # 选择要管理的群，进入迎新消息管理菜单
                    group = groups[choice - 1]
                    operator_state.current_group = group['wxid']
                    operator_state.state = ForwardState.WELCOME_MANAGE
                    self.welcome_service.show_menu(msg.sender)  # 显示迎新消息管理菜单（查看/设置）
                    return True
                else:
                    self.sendTextMsg("无效的选择，请重新输入", msg.sender)
                return True
            except ValueError:
                self.sendTextMsg("请输入有效的数字", msg.sender)
                return True

        elif operator_state.state == ForwardState.WELCOME_MANAGE: #上一步选择群后，进入迎新消息管理菜单
            try:
                choice = int(msg.content)
                if choice == 0:  # 退出迎新消息管理
                    self._reset_operator_state(msg.sender)
                    self.sendTextMsg("已退出迎新消息管理", msg.sender)
                    return True
                elif choice == 1:  # 查看当前群的迎新消息（在welcome_service.py中实现）
                    self.welcome_service.show_current_messages(operator_state.current_group, msg.sender)
                    return True
                elif choice == 2:  # 设置新的迎新消息，进入消息收集状态
                    operator_state.state = ForwardState.WELCOME_COLLECTING
                    operator_state.messages = []
                    self.sendTextMsg("请发送新的迎新消息，发送完成后回复数字1", msg.sender)
                    return True
                else:
                    self.sendTextMsg("无效的选择，请重新输入。退出请回复0", msg.sender)
                return True
            except ValueError:
                self.sendTextMsg("请输入有效的数字。退出请回复0", msg.sender)
                return True

        elif operator_state.state == ForwardState.WELCOME_COLLECTING:
            if msg.content == "1":  # 完成消息收集，保存并返回管理菜单
                if not operator_state.messages:
                    self.sendTextMsg("未收到任何消息，请重新发送，退出请回复0", msg.sender)
                    return True
                
                # 保存消息（在welcome_service.py中实现）
                self.welcome_service.save_messages(operator_state.current_group, operator_state.messages, msg.sender)
                
                # 重置状态
                self._reset_operator_state(msg.sender)
                return True
                
            # 收集消息（支持文本、图片、合并转发消息，具体处理在welcome_service.py中）
            operator_state.messages.append(msg)
            self.sendTextMsg(f"✅ 已收集 {len(operator_state.messages)} 条消息，继续发送或回复数字1完成设置", msg.sender)
            return True

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
        MAX_RETRIES = 3  # 最大重试次数
        
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
                failed_messages = []  # 记录失败的消息
                
                # 为每个群添加随机延迟
                for i, group in enumerate(groups):
                    # 每个群之间的基础延迟3-5秒
                    group_delay = random.uniform(3, 5)
                    
                    # 每10个群增加额外延迟5-10秒，避免频繁发送
                    if i > 0 and i % 10 == 0:
                        extra_delay = random.uniform(5, 10)
                        time.sleep(extra_delay)
                    
                    group_failed_messages = []  # 记录当前群发送失败的消息
                    
                    for msg in messages:
                        retries = 0
                        success = False
                        
                        # 添加重试机制
                        while retries < MAX_RETRIES and not success:
                            try:
                                if self._forward_message(msg, group):
                                    success = True
                                    success_count += 1
                                else:
                                    retries += 1
                                    if retries < MAX_RETRIES:
                                        time.sleep(2)  # 重试前等待
                            except Exception as e:
                                logger.error(f"发送消息失败 (重试 {retries + 1}/{MAX_RETRIES}): {e}")
                                retries += 1
                                if retries < MAX_RETRIES:
                                    time.sleep(2)
                        
                        if not success:
                            failed_count += 1
                            group_failed_messages.append({
                                'msg_id': msg.id,
                                'type': msg.type,
                                'error': f"发送失败，已重试 {MAX_RETRIES} 次"
                            })
                        
                        # 每条消息间隔1-2秒
                        time.sleep(random.uniform(1, 2))
                    
                    if group_failed_messages:
                        failed_messages.append({
                            'group': group,
                            'messages': group_failed_messages
                        })
                    
                    time.sleep(group_delay)
                
                # 发送最终结果
                status = f"转发完成！\n成功：{success_count} 条\n失败：{failed_count} 条\n总计：{total_messages} 条消息到 {total_groups} 个群"
                
                # 如果有失败的消息，添加详细信息
                if failed_messages:
                    status += "\n\n失败详情："
                    for group_fail in failed_messages:
                        group_name = self.wcf.get_room_name(group_fail['group']) or group_fail['group']
                        status += f"\n群「{group_name}」:"
                        for msg in group_fail['messages']:
                            status += f"\n- 消息ID {msg['msg_id']} (类型 {msg['type']}): {msg['error']}"
                
                self.sendTextMsg(status, operator_id)
                
            except Exception as e:
                logger.error(f"处理转发队列时出错: {e}", exc_info=True)
                if 'operator_id' in locals():
                    self.sendTextMsg(f"转发过程中发生错误: {str(e)}", operator_id)
            finally:
                self.forward_queue.task_done()

    def sync_data_from_notion(self) -> None:
        """从 Notion 同步数据并更新到程序中
        使用 Robot 类的同步方法来保持一致性
        """
        self.robot.sync_data_from_notion()

    
