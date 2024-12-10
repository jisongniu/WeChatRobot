from typing import Optional, List
from enum import Enum
from .notion_manager import NotionManager
import logging
import time
import random
from configuration import Configuration as Config
import os
from wcferry import WxMsg
from threading import Lock

logger = logging.getLogger(__name__)

class ForwardState(Enum):
    IDLE = "idle"
    WAITING_CHOICE_MODE = "waiting_choice_mode"
    WAITING_MESSAGE = "waiting_message"
    WAITING_CHOICE = "waiting_choice"

class NCCManager:
    def __init__(self, notion_manager: NotionManager, config: Config, wcf):
        self.notion_manager = notion_manager
        self.forward_state = ForwardState.IDLE
        self.current_list_id = None
        self.forward_messages = []
        self.forward_admin = config.FORWARD_ADMINS
        self.wcf = wcf
        self.images_dir = os.path.join(os.path.dirname(__file__), "ncc_images")
        if not os.path.exists(self.images_dir):
            os.makedirs(self.images_dir)
        self.image_lock = Lock()
        
    def _send_menu(self, receiver):
        """发送NCC管理菜单"""
        menu = (
            "NCC社群管理：\n"
            "1. 转发消息请回复：1\n"
            "2. 发送【刷新列表】更新群组信息（每次更新Notion后，请操作一次）\n"
            "3. 列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4"
        )
        self.sendTextMsg(menu, receiver)
        
    def handle_message(self, msg) -> bool:
        """统一处理所有NCC相关消息"""
        if msg.content == "ncc":
            if msg.sender in self.forward_admin:
                self.forward_state = ForwardState.WAITING_CHOICE_MODE
                self._send_menu(msg.sender)
                return True
            else:
                self.sendTextMsg("对不起，你未开通ncc管理权限，私聊大松获取。", msg.sender)
                return False
            
        # 如果已经在某个状态中，继续处理
        if self.forward_state != ForwardState.IDLE:
            return self._handle_forward_state(msg)
        
        return False

    def _handle_forward_state(self, msg) -> bool:
        """处理不同状态下的消息"""
        if self.forward_state == ForwardState.WAITING_CHOICE_MODE:
            if msg.content == "刷新列表":
                logger.info("收到刷新列表命令")
                if self.notion_manager.save_lists_to_local():
                    self.sendTextMsg("已刷新转发列表", msg.sender)
                else:
                    self.sendTextMsg("刷新列表失败", msg.sender)
                self._send_menu(msg.sender)
                return True
            elif msg.content == "1":
                self.forward_state = ForwardState.WAITING_MESSAGE
                self.forward_messages = []
                self.sendTextMsg("请发送需要转发的内容（支持公众号、推文、视频号、文字、图片、合并消息，数量不限，完毕后输入➡️选择群聊", msg.sender)
                return True
            return True
        
        elif self.forward_state == ForwardState.WAITING_MESSAGE:
            if msg.content == "选择群聊":
                if not self.forward_messages:
                    self.sendTextMsg("还未收集到任何消息，请先发送需要转发的内容", msg.sender)
                    return True
                
                self.forward_state = ForwardState.WAITING_CHOICE
                lists = self.notion_manager.load_lists_from_local()
                if not lists:
                    self.sendTextMsg("未找到可用的转发列表，请先使用【刷新列表】更新数据", msg.sender)
                    self._reset_state()
                    return True
                    
                response = f"已收集 {len(self.forward_messages)} 条消息\n请选择想要转发的分组编号：\n"
                # 遍历列表，筛选符合条件的群聊
                for lst in lists:
                    response += f"{lst.list_id} 👈 {lst.list_name}\n"
                # 发送群聊列表给消息发送者
                self.sendTextMsg(response, msg.sender)
            else:
                # 收集消息，如果是图片先下载
                if msg.type == 3:  # 图片消息
                    try:
                        img_path = self.wcf.download_image(msg.id, msg.extra, self.images_dir, timeout=120)
                        if not img_path or not os.path.exists(img_path):
                            self.sendTextMsg("图片下载失败，请检查图片是否正常", msg.sender)
                            return True
                    except TimeoutError:
                        self.sendTextMsg("图片下载超时，请稍后重试", msg.sender)
                        return True
                    except Exception as e:
                        logger.error(f"图片下载失败: {e}")
                        self.sendTextMsg("图片下载异常，请联系管理员", msg.sender)
                        return True
                
                self.forward_messages.append(msg)
                return True
            
        elif self.forward_state == ForwardState.WAITING_CHOICE:
            try:
                list_id = int(msg.content)
                if self.forward_messages:
                    groups = self.notion_manager.get_groups_by_list_id(list_id)
                    if not groups:
                        self.sendTextMsg(f"未找到ID为 {list_id} 的列表或列表中没有有效的群组", msg.sender)
                        self._reset_state()
                        return True
                        
                    total_groups = len(groups)
                    total_messages = len(self.forward_messages)
                    
                    self.sendTextMsg(f"开始转发 {total_messages} 条消息到 {total_groups} 个群...", msg.sender)
                    
                    success_count = 0
                    failed_count = 0
                    
                    for group in groups:
                        for fwd_msg in self.forward_messages:
                            if self._forward_message(fwd_msg, group):
                                success_count += 1
                            else:
                                failed_count += 1
                            time.sleep(random.uniform(0.5, 1))
                        time.sleep(random.uniform(1, 2))
                    
                    status = f"转发完成！\n成功：{success_count} 条\n失败：{failed_count} 条\n总计：{total_messages} 条消息到 {total_groups} 个群"
                    self.sendTextMsg(status, msg.sender)
                
                self._reset_state()
                return True
                
            except ValueError:
                self.sendTextMsg("请输入正确的列表编号", msg.sender)
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
    
    def _reset_state(self) -> None:
        """重置所有状态"""
        self.forward_state = ForwardState.IDLE
        self.current_list_id = None
        self.forward_messages = []

    def refresh_lists(self) -> bool:
        """刷新并保存列表信息"""
        return self.notion_manager.save_lists_to_local()

    def sendTextMsg(self, msg: str, receiver: str) -> None:
        """发送文本消息"""
        self.wcf.send_text(msg, receiver)

    