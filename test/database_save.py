import os
import json
from notion_client import Client
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def save_notion_data():
    """保存Notion数据到本地"""
    try:
        # Notion配置
        token = "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"
        lists_db_id = "1564e93f568280baa110f5c48b5249b6"
        groups_db_id = "1564e93f56828007b10cd8a5d2fa1f50"
        
        # 创建Notion客户端
        notion = Client(auth=token)
        
        # 创建保存目录
        save_dir = "test/notion_data"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        # 获取并保存列表数据
        lists_response = notion.databases.query(
            database_id=lists_db_id,
            filter={
                "property": "是否转发",
                "checkbox": {
                    "equals": True
                }
            }
        )
        
        # 保存列表数据
        with open(os.path.join(save_dir, "群聊分组.json"), "w", encoding="utf-8") as f:
            json.dump(lists_response, f, ensure_ascii=False, indent=2)
        logger.info("列表数据已保存")
        
        # 获取并保存群组数据
        groups_response = notion.databases.query(
            database_id=groups_db_id,
            filter={
                "property": "允许发言",
                "checkbox": {
                    "equals": True
                }
            }
        )
        
        # 保存群组数据
        with open(os.path.join(save_dir, "所有群聊.json"), "w", encoding="utf-8") as f:
            json.dump(groups_response, f, ensure_ascii=False, indent=2)
        logger.info("群组数据已保存")
        
        # 保存元数据
        metadata = {
            "export_time": datetime.now().isoformat(),
            "lists_count": len(lists_response["results"]),
            "groups_count": len(groups_response["results"])
        }
        
        with open(os.path.join(save_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.info("元数据已保存")
        
        return True
        
    except Exception as e:
        logger.error(f"保存数据失败: {e}")
        return False

if __name__ == "__main__":
    if save_notion_data():
        logger.info("数据保存完成")
    else:
        logger.error("数据保存失败") 