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
            "请回复指定数字\n"
            "1 👈 转发消息\n"
            "2 👈 刷新群聊列表，更新列表后请操作再转发\n"
            "3 👈 查看群聊列表信息\n"
            "4 👈 查看团队成员\n"
            "0 👈 退出管理模式"
        )
        self.sendTextMsg(menu, receiver)
        
    def handle_message(self, msg) -> bool:
        """统一处理所有NCC相关消息"""
        # 添加调试日志
        logger.info(f"handle_message 收到消息: type={msg.type}, content={msg.content}")
        
        if msg.content.lower() == "ncc":
            if msg.sender in self.forward_admin:
                self.forward_state = ForwardState.WAITING_CHOICE_MODE
                self._send_menu(msg.sender)
                return True
            else:
                self.sendTextMsg("对不起，你未开通ncc管理权限，私聊大松获取。", msg.sender)
                return False
            
        # 如果已经在某个状态中，继续处理
        if self.forward_state != ForwardState.IDLE:
            logger.info(f"当前状态: {self.forward_state}")
            return self._handle_forward_state(msg)
        
        return False

    def _handle_forward_state(self, msg) -> bool:
        """处理不同状态下的消息"""
        # 在任何状态下都可以退出
        if msg.content == "0":
            self._reset_state()
            self.sendTextMsg("已退出管理模式", msg.sender)
            return True

        if self.forward_state == ForwardState.WAITING_CHOICE_MODE:
            if msg.content == "2":
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
                self.sendTextMsg("请发送需要转发的内容，支持公众号、推文、视频号、文字、图片、合并消息，一个一个来\n发送【选择群聊】进入下一步\n随时发送【0】退出转发模式", msg.sender)
                return True
            elif msg.content == "3":
                self.sendTextMsg("列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4", msg.sender)
                return True
            elif msg.content == "4":
                # 获取管理员昵称列表
                admin_names = []
                for admin_id in self.forward_admin:
                    nickname = self.wcf.get_info_by_wxid(admin_id).get('name', admin_id)
                    admin_names.append(nickname)
                admin_list = "成员：\n" + "\n".join(f"👤 {name}" for name in admin_names)
                self.sendTextMsg(admin_list, msg.sender)
                return True
            else:
                self.sendTextMsg("请输入有效的选项，或发送【0】退出转发模式", msg.sender)
            return True
        
        #信息收集阶段
        elif self.forward_state == ForwardState.WAITING_MESSAGE:
            # 添加调试日志
            logger.info(f"收到消息，类型: {msg.type}, 内容: {msg.content}")
            
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
                # 发送群聊列表给发送者，以供选择
                self.sendTextMsg(response, msg.sender)
                return True
            
            try:
                # 只有图片消息需要特殊处理（提前下载）
                if msg.type == 3:
                    self.sendTextMsg("检测到图片消息，原图下载有点慢，等会儿", msg.sender)
                    img_path = self.wcf.download_image(msg.id, msg.extra, self.images_dir, timeout=120)
                    if not img_path or not os.path.exists(img_path):
                        self.sendTextMsg("图片下载失败，请检查图片是否正常", msg.sender)
                        return True
                    logger.info(f"图片下载成功: {img_path}")
                
                # 所有消息都直接添加到收集器
                self.forward_messages.append(msg)
                logger.info(f"消息已添加到收集器，当前数量: {len(self.forward_messages)}")
                self.sendTextMsg(f"已收集 {len(self.forward_messages)} 条消息，继续发送或者：选择群聊", msg.sender)
                
            except TimeoutError:
                logger.error("图片下载超时")
                self.sendTextMsg("图片下载超时，请稍后重试", msg.sender)
            except Exception as e:
                logger.error(f"消息收集失败: {e}", exc_info=True)  # 添加完整的异常堆栈
                self.sendTextMsg("消息收集异常，请联系管理员", msg.sender)
            return True

        #转发阶段    
        elif self.forward_state == ForwardState.WAITING_CHOICE:
            try:
                list_id = int(msg.content)
                if self.forward_messages:
                    groups = self.notion_manager.get_groups_by_list_id(list_id)
                    if not groups:
                        self.sendTextMsg(f"未找到ID为 {list_id} 的列表或列表中没有有效的群组，退出管理模式", msg.sender)
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
                self.sendTextMsg("请输入有效的选项，或发送【0】退出转发模式", msg.sender)
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

    