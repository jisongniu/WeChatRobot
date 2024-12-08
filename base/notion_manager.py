from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from notion_client import Client
import logging

logger = logging.getLogger(__name__)

@dataclass
class ForwardList:
    list_id: int
    list_name: str
    groups: List[Dict[str, str]]

class NotionManager:
    def __init__(self, token: str, lists_db_id: str, groups_db_id: str, wcf=None):
        self.notion = Client(auth=token)
        self.lists_db_id = lists_db_id
        self.groups_db_id = groups_db_id
        self.wcf = wcf
        self._cache = {'wxid_map': None}

    def _get_group_wxid(self, group_name: str) -> Optional[str]:
        """通过群名获取群wxid"""
        if self._cache['wxid_map'] is None:
            chatrooms = self.wcf.get_rooms()
            self._cache['wxid_map'] = {
                self.wcf.get_room_name(room): room
                for room in chatrooms
            }
            logger.info(f"已缓存 {len(chatrooms)} 个群聊的wxid映射")

        return self._cache['wxid_map'].get(group_name)

    def get_all_lists(self) -> List[ForwardList]:
        """获取所有转发列表及其群组"""
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
                    list_id = page['properties'].get('分组编号', {}).get('number')
                    if not list_id:
                        continue
                        
                    title_array = page['properties'].get('组名', {}).get('title', [])
                    if not title_array:
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
                    relation_array = page['properties'].get('转发群聊分组', {}).get('relation', [])
                    if not relation_array:
                        continue
                    
                    name_array = page['properties'].get('群名', {}).get('title', [])
                    if not name_array:
                        continue
                    
                    group_name = name_array[0]['text']['content']
                    
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

            return list(lists.values())
            
        except Exception as e:
            logger.error(f"获取列表失败: {e}")
            return []

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """根据列表ID获取对应的群组wxid列表"""
        try:
            response = self.notion.databases.query(
                database_id=self.lists_db_id,
                filter={
                    "property": "分组编号",
                    "number": {
                        "equals": list_id
                    }
                }
            )

            if not response['results']:
                logger.warning(f"未找到ID为 {list_id} 的列表")
                return []

            groups_relation = response['results'][0]['properties'].get('转发群聊分组', {}).get('relation', [])
            if not groups_relation:
                logger.warning(f"列表 {list_id} 未关联任何群组")
                return []

            all_groups = []
            for relation in groups_relation:
                try:
                    group_page = self.notion.pages.retrieve(relation['id'])
                    name_array = group_page['properties'].get('群名', {}).get('title', [])
                    if name_array:
                        group_name = name_array[0]['text']['content']
                        group_wxid = self._get_group_wxid(group_name)
                        if group_wxid:
                            all_groups.append(group_wxid)
                        else:
                            logger.warning(f"未找到群组 {group_name} 的wxid")
                except Exception as e:
                    logger.error(f"获取群组详情失败: {e}")
                    continue

            return all_groups

        except Exception as e:
            logger.error(f"获取群组列表失败: {e}")
            return []

    def refresh_lists(self) -> None:
        """刷新列表缓存"""
        self._cache['wxid_map'] = None
        logger.info("已刷新列表缓存")

    def clear_cache(self) -> None:
        """清除所有缓存"""
        self._cache = {'wxid_map': None}
        logger.info("已清除所有缓存")

    def get_all_allowed_groups(self) -> List[str]:
        """获取所有允许发言的群组wxid列表"""
        try:
            groups = []
            response = self.notion.databases.query(
                database_id=self.groups_db_id,
                filter={
                    "property": "允许发言",
                    "checkbox": {
                        "equals": True
                    }
                }
            )
            
            for page in response['results']:
                name_array = page['properties'].get('群名', {}).get('title', [])
                if name_array:
                    group_name = name_array[0]['text']['content']
                    group_wxid = self._get_group_wxid(group_name)
                    if group_wxid:
                        groups.append(group_wxid)
                    
            return groups
        except Exception as e:
            logger.error(f"获取允许群组失败: {e}")
            return []
        