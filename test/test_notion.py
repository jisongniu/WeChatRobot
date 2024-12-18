import os
from notion_client import Client
from typing import NamedTuple
import logging
from dataclasses import dataclass
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ForwardList:
    list_id: int
    list_name: str
    groups: List[Dict[str, str]]

class NotionManager:
    def __init__(self, token: str, lists_db_id: str, groups_db_id: str):
        self.notion = Client(auth=token)
        self.lists_db_id = lists_db_id
        self.groups_db_id = groups_db_id
        
    def get_all_lists(self):
        """获取所有转发列表"""
        try:
            lists = {}
            lists_response = self.notion.databases.query(
                database_id=self.lists_db_id,
                filter={
                    "property": "是否转发",
                    "checkbox": {
                        "equals": True
                    }
                }
            )
            
            logger.info(f"获取到 {len(lists_response['results'])} 个列表")

            for page in lists_response['results']:
                try:
                    # 检查必要的属性是否存在
                    if not page['properties'].get('分组编号', {}).get('number'):
                        logger.warning(f"页面缺少分组编号")
                        continue
                        
                    list_id = page['properties']['分组编号']['number']
                    
                    # 检查组名
                    title_array = page['properties'].get('组名', {}).get('title', [])
                    if not title_array:
                        logger.warning(f"页面缺少组名")
                        continue
                    list_name = title_array[0]['text']['content']
                    
                    lists[list_id] = ForwardList(
                        list_id=list_id,
                        list_name=list_name,
                        groups=[]
                    )
                    logger.info(f"成功处理列表: {list_id} - {list_name}")
                    
                except Exception as e:
                    logger.error(f"处理列表时出错: {e}")
                    continue

            # 获取活跃的群组
            groups_response = self.notion.databases.query(
                database_id=self.groups_db_id,
                filter={
                    "property": "允许发言",
                    "checkbox": {
                        "equals": True
                    }
                }
            )
            
            logger.info(f"获取到 {len(groups_response['results'])} 个群组")

            for page in groups_response['results']:
                try:
                    # 检查关联属性
                    relation_array = page['properties'].get('转发群聊分组', {}).get('relation', [])
                    if not relation_array:
                        continue
                    
                    # 获取群名
                    name_array = page['properties'].get('群名', {}).get('title', [])
                    if not name_array:
                        continue
                    
                    group_name = name_array[0]['text']['content']
                    
                    # 处理每个关联的分组
                    for relation in relation_array:
                        try:
                            list_page = self.notion.pages.retrieve(relation['id'])
                            list_id = list_page['properties']['分组编号']['number']
                            
                            if list_id in lists:
                                lists[list_id].groups.append({
                                    'group_name': group_name
                                })
                                logger.info(f"成功添加群组 {group_name} 到列表 {list_id}")
                        except Exception as e:
                            logger.error(f"处理群组关联时出错: {e}")
                            continue
                        
                except Exception as e:
                    logger.error(f"处理群组时出错: {e}")
                    continue

            result_lists = list(lists.values())
            logger.info(f"成功获取 {len(result_lists)} 个转发列表")
            return result_lists
            
        except Exception as e:
            logger.error(f"获取列表失败: {e}")
            return []

def main():
    # 从环境变量获取配置
    token = "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"  # 替换为你的 Notion token
    lists_db_id = "1564e93f568280baa110f5c48b5249b6"  # 替换为你的列表数据库 ID
    groups_db_id = "1564e93f56828007b10cd8a5d2fa1f50"  # 替换为你的群组数据库 ID
    
    notion_mgr = NotionManager(token, lists_db_id, groups_db_id)
    
    # 测试获取所有列表
    print("\n=== 测试获取所有列表和群组 ===")
    lists = notion_mgr.get_all_lists()
    for lst in lists:
        print(f"\n列表ID: {lst.list_id}")
        print(f"列表名称: {lst.list_name}")
        print(" 关联群组:")
        for group in lst.groups:
            print(f"  - {group['group_name']}")

if __name__ == "__main__":
    main() 