import logging
import json
import os
from typing import Dict, List, Optional
from wcferry import Wcf
from .notion_manager import NotionManager
from threading import Thread

logger = logging.getLogger(__name__)

class InviteService:
    """关键词邀请入群服务"""
    
    def __init__(self, wcf: Wcf, notion_manager: NotionManager):
        self.wcf = wcf
        self.notion_manager = notion_manager
        self.db = notion_manager.db
        
    def handle_keyword(self, keyword: str, user_wxid: str) -> bool:
        """处理关键词并邀请用户
        
        Args:
            keyword: 触发的关键词
            user_wxid: 用户的wxid
            
        Returns:
            是否成功处理
        """
        try:
            # 获取目标群组
            target_groups = self.db.get_groups_by_keyword(keyword)
            if not target_groups:
                return False
            
            # 创建后台线程处理邀请
            def do_invite():
                for group_id in target_groups:
                    try:
                        result = self.wcf.invite_chatroom_members(group_id, user_wxid)
                        if result:
                            logger.info(f"成功邀请用户 {user_wxid} 到群 {group_id}")
                        else:
                            logger.error(f"邀请用户 {user_wxid} 到群 {group_id} 失败")
                    except Exception as e:
                        logger.error(f"邀请用户到群 {group_id} 时发生错误: {e}")
                        
            Thread(target=do_invite, name="GroupInvite", daemon=True).start()
            return True
            
        except Exception as e:
            logger.error(f"处理关键词邀请失败: {e}")
            return False 