from typing import Optional
from .notion_manager import NotionManager
import logging

logger = logging.getLogger(__name__)

class NCCManager:
    def __init__(self, notion_manager: NotionManager):
        self.notion_manager = notion_manager

    def handle_command(self, command: str) -> str:
        """处理NCC相关命令"""
        if command == "刷新列表":
            return self.refresh_lists()
        elif command.isdigit():
            return self.get_list_info(int(command))
        else:
            return self.get_help_info()

    def refresh_lists(self) -> str:
        """刷新并保存列表信息"""
        success = self.notion_manager.save_lists_to_local()
        if success:
            return "列表已刷新，可以通过发送列表编号查看具体信息"
        return "刷新列表失败，请稍后重试"

    def get_list_info(self, list_id: int) -> str:
        """获取特定列表信息"""
        return self.notion_manager.get_list_info_by_id(list_id)

    def get_help_info(self) -> str:
        """获取帮助信息"""
        return (
            "NCC社群管理：\n"
            "1. 转发消息请回复：1\n"
            "2. 发送"刷新列表"更新群组信息（每次更新Notion后，请操作一次）\n"
            "3. 列表信息，请登陆查看：https://www.notion.so/bigsong/NCC-1564e93f5682805d9a2ff0519c24738b?pvs=4\n"
        )

    def get_all_lists_info(self) -> str:
        """获取所有列表信息"""
        return self.notion_manager.get_local_lists_info() 