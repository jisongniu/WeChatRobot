import logging
import json
import os
from typing import Dict, List, Optional
from wcferry import Wcf
from .notion_manager import NotionManager

logger = logging.getLogger(__name__)

class InviteService:
    """关键词邀请入群服务"""
    
    def __init__(self, wcf: Wcf, notion_manager: NotionManager):
        self.wcf = wcf
        self.notion_manager = notion_manager
        self.keywords_db_id = self.notion_manager.keywords_db_id
        if not self.keywords_db_id:
            logger.error("未配置 KEYWORDS_DB_ID")
            return
            
        self.local_data_path = "data/keywords_cache.json"
        self.keywords_map = {}  # 关键词到群组的映射
        
        # 确保数据目录存在
        os.makedirs("data", exist_ok=True)
        
        # 初始化时加载数据
        self.update_keywords_data()
        
    def update_keywords_data(self) -> None:
        """从 Notion 更新关键词数据"""
        try:
            # 获取关键词数据
            keywords_data = self.notion_manager.notion.databases.query(
                database_id=self.keywords_db_id
            ).get("results", [])
            
            # 处理数据
            keywords_map = {}
            for item in keywords_data:
                # 获取关键词（标题）
                title = item["properties"].get("让对方回复", {}).get("title", [])
                if not title:
                    continue
                keyword = title[0]["text"]["content"]
                
                # 获取关联的群组
                relations = item["properties"].get("拉入群聊", {}).get("relation", [])
                if not relations:
                    continue
                    
                # 存储关键词和关联的群组ID
                keywords_map[keyword] = [rel["id"] for rel in relations]
            
            # 保存到本地文件
            with open(self.local_data_path, "w", encoding="utf-8") as f:
                json.dump({
                    "keywords": keywords_map
                }, f, ensure_ascii=False, indent=2)
                
            # 更新内存中的映射
            self.keywords_map = keywords_map
            logger.info("关键词数据更新成功")
            
        except Exception as e:
            logger.error(f"更新关键词数据失败: {e}")
            
    def get_target_groups(self, keyword: str) -> List[str]:
        """获取关键词对应的目标群组wxid列表
        
        Args:
            keyword: 触发的关键词
            
        Returns:
            目标群组的wxid列表
        """
        try:
            # 检查关键词是否存在
            if keyword not in self.keywords_map:
                return []
                
            # 获取关联的群组ID列表
            group_ids = self.keywords_map[keyword]
            
            # 从本地缓存中获取群组wxid
            target_groups = []
            with open(self.notion_manager.local_data_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                
            for group in cache_data.get("groups", []):
                if group["id"] in group_ids:
                    # 获取群组的wxid
                    wxid_texts = group["properties"].get("group_wxid", {}).get("rich_text", [])
                    if wxid_texts:
                        wxid = wxid_texts[0]["text"]["content"]
                        target_groups.append(wxid)
            
            return target_groups
            
        except Exception as e:
            logger.error(f"获取目标群组失败: {e}")
            return []
            
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
            target_groups = self.get_target_groups(keyword)
            if not target_groups:
                logger.info(f"关键词 {keyword} 没有对应的目标群组")
                return False
                
            # 邀请用户到所有目标群组
            success = False
            for group_id in target_groups:
                result = self.wcf.invite_chatroom_members(group_id, user_wxid)
                if result:
                    success = True
                    logger.info(f"邀请用户 {user_wxid} 到群 {group_id}")
                else:
                    logger.error(f"邀请用户 {user_wxid} 到群 {group_id} 失败")
                    
            return success
            
        except Exception as e:
            logger.error(f"处理关键词邀请失败: {e}")
            return False 