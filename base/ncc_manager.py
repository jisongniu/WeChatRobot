from typing import Optional
from .notion_manager import NotionManager
import logging

logger = logging.getLogger(__name__)

class NCCManager:
    def __init__(self, notion_manager: NotionManager):
        self.notion_manager = notion_manager
        self.current_mode = None
        self.current_list_id = None

    def handle_command(self, command: str) -> str:
        """处理NCC相关命令"""
        command = command.strip()
        
        if command == "ncc":
            self.exit_current_mode()
            return self.get_memu()
        elif command == "刷新列表":
            return self.refresh_lists()
        elif command == "1":  # 转发模式
            self.current_mode = "forward"
            return self.get_forward_help()
        else:
            # 如果在转发模式下
            if self.current_mode == "forward":
                if command.isdigit():
                    list_id = int(command)
                    return self.start_forward_mode(list_id)
                else:
                    return "请输入正确的列表编号，或输入 'ncc' 返回主菜单"
            return "未知命令，请输入 'ncc' 查看帮助"

    def refresh_lists(self) -> str:
        """刷新并保存列表信息"""
        success = self.notion_manager.save_lists_to_local()
        if success:
            return "列表已刷新成功！"
        return "刷新列表失败"

    def get_forward_help(self) -> str:
        """获取转发模式的帮助信息"""
        info = "转发模式：\n"
        info += self.notion_manager.get_local_lists_info()
        info += "\n请回复列表编号开始转发"
        return info

    def start_forward_mode(self, list_id: int) -> str:
        """开始转发模式"""
        groups = self.notion_manager.get_groups_by_list_id(list_id)
        if not groups:
            self.current_mode = None
            self.current_list_id = None
            return f"未找到ID为 {list_id} 的列表或列表中没有有效的群组"
        
        self.current_list_id = list_id
        return f"已进入转发模式，消息将被转发到列表 {list_id} 的 {len(groups)} 个群组\n发送消息开始转发，发送 'ncc' 退出转发模式"

    def get_memu(self) -> str:
        """获取NCC管理菜单"""
        return (
            "NCC社群管理：\n"
            "1. 转发消息请回复：1\n"
            "2. 发送【刷新列表】更新群组信息（每次更新Notion后，请操作一次）\n"
            "3. 列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4"
        ) 

    def get_current_list_id(self) -> Optional[int]:
        """获取当前转发列表ID"""
        return self.current_list_id if self.current_mode == "forward" else None

    def exit_current_mode(self) -> None:
        """退出当前模式"""
        self.current_mode = None
        self.current_list_id = None 