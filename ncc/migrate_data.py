import os
import json
import sqlite3
import logging
from typing import List, Dict, Optional
from .db_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_welcome_messages(old_db_path: str, db_manager: DatabaseManager) -> bool:
    """从旧的welcome_messages.db迁移数据"""
    if not os.path.exists(old_db_path):
        logger.warning(f"旧数据库不存在: {old_db_path}")
        return False
        
    try:
        # 连接旧数据库
        with sqlite3.connect(old_db_path) as old_conn:
            old_cur = old_conn.cursor()
            
            # 获取所有迎新消息
            old_cur.execute("""
                SELECT group_id, message_type, content, path, recorditem 
                FROM welcome_messages 
                ORDER BY id ASC
            """)
            rows = old_cur.fetchall()
            
            # 获取所有欢迎小卡片URL
            old_cur.execute("SELECT group_id, welcome_url FROM welcome_urls")
            urls = {row[0]: row[1] for row in old_cur.fetchall()}
            
            # 更新小卡片URL到新数据库
            for group_id, url in urls.items():
                db_manager.set_welcome_url(group_id, url)
                logger.info(f"已迁移群 {group_id} 的小卡片URL")
            
            # 按群组整理消息
            messages_by_group = {}
            for row in rows:
                group_id, msg_type, content, path, recorditem = row
                if group_id not in messages_by_group:
                    messages_by_group[group_id] = []
                    
                # 转换消息类型
                if msg_type == "text":
                    messages_by_group[group_id].append({
                        "type": 1,
                        "content": content,
                        "extra": None
                    })
                elif msg_type == "image":
                    messages_by_group[group_id].append({
                        "type": 3,
                        "content": None,
                        "extra": path
                    })
                elif msg_type == "merged":
                    messages_by_group[group_id].append({
                        "type": 49,
                        "content": None,
                        "extra": recorditem
                    })
            
            # 保存到新数据库
            for group_id, messages in messages_by_group.items():
                db_manager.save_welcome_messages(group_id, messages)
                logger.info(f"已迁移群 {group_id} 的 {len(messages)} 条迎新消息")
            
            logger.info("迎新消息迁移完成")
            return True
            
    except Exception as e:
        logger.error(f"迁移迎新消息失败: {e}")
        return False

def migrate_from_json(json_path: str, db_manager: DatabaseManager) -> bool:
    """从JSON文件迁移数据"""
    try:
        db_manager.migrate_from_json(json_path)
        logger.info("JSON数据迁移完成")
        return True
    except Exception as e:
        logger.error(f"迁移JSON数据失败: {e}")
        return False

def main():
    """主迁移函数"""
    try:
        # 初始化数据库管理器
        db_manager = DatabaseManager()
        
        # 迁移JSON数据
        json_path = "data/notion_cache.json"
        if os.path.exists(json_path):
            if migrate_from_json(json_path, db_manager):
                # 备份旧文件
                backup_path = f"{json_path}.bak"
                os.rename(json_path, backup_path)
                logger.info(f"已备份旧JSON文件到: {backup_path}")
        
        # 迁移迎新消息数据
        old_db_path = os.path.join(os.path.dirname(__file__), "welcome_messages.db")
        if os.path.exists(old_db_path):
            if migrate_welcome_messages(old_db_path, db_manager):
                # 备份旧数据库
                backup_path = f"{old_db_path}.bak"
                os.rename(old_db_path, backup_path)
                logger.info(f"已备份旧数据库到: {backup_path}")
        
        logger.info("数据迁移完成")
        return True
        
    except Exception as e:
        logger.error(f"数据迁移失败: {e}")
        return False

if __name__ == "__main__":
    main() 