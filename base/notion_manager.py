from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from notion_client import Client
import threading
import logging

logger = logging.getLogger(__name__)

@dataclass
class ForwardList:
    list_id: int
    list_name: str
    description: str
    groups: List[Dict[str, str]]

@dataclass
class CacheData:
    data: any
    expire_time: datetime

class NotionManager:
    def __init__(self, token: str, lists_db_id: str, groups_db_id: str, cache_ttl: int = 604800):
        self.notion = Client(auth=token)
        self.lists_db_id = lists_db_id
        self.groups_db_id = groups_db_id
        self.cache_ttl = cache_ttl  # 缓存有效期（秒）
        self.cache_lock = threading.Lock()
        self._cache = {
            'lists': None,
            'groups': {}  # 按 list_id 缓存群组
        }

    def _get_cache(self, cache_key: str) -> Optional[any]:
        """获取缓存数据"""
        with self.cache_lock:
            cache_data = self._cache.get(cache_key)
            if cache_data and datetime.now() < cache_data.expire_time:
                return cache_data.data
            return None

    def _set_cache(self, cache_key: str, data: any) -> None:
        """设置缓存数据"""
        with self.cache_lock:
            self._cache[cache_key] = CacheData(
                data=data,
                expire_time=datetime.now() + timedelta(seconds=self.cache_ttl)
            )

    def clear_cache(self) -> None:
        """清除所有缓存"""
        with self.cache_lock:
            self._cache = {
                'lists': None,
                'groups': {}
            }

    def get_all_lists(self) -> List[ForwardList]:
        """获取所有转发列表（带缓存）"""
        # 尝试从缓存获取
        cached_lists = self._get_cache('lists')
        if cached_lists is not None:
            return cached_lists

        # 缓存未命中，从 Notion 获取数据
        lists = {}
        
        # 获取所有活跃的转发列表
        lists_response = self.notion.databases.query(
            database_id=self.lists_db_id,
            filter={
                "property": "是否转发",
                "checkbox": {
                    "equals": True
                }
            }
        )

        # 添加错误处理和日志
        logger.info(f"获取到 {len(lists_response['results'])} 个列表")

        for page in lists_response['results']:
            try:
                # 检查必要的属性是否存在
                if not page['properties'].get('分组编号', {}).get('number'):
                    logger.warning(f"页面缺少分组编号: {page['properties']['组名']['title'][0]['text']['content']}")
                    continue
                    
                list_id = page['properties']['分组编号']['number']
                
                # 检查组名
                title_array = page['properties'].get('组名', {}).get('title', [])
                if not title_array:
                    logger.warning(f"页面缺少组名: {page['properties']['组名']['title'][0]['text']['content']}")
                    continue
                list_name = title_array[0]['text']['content']
                
                # 检查描述
                desc_array = page['properties'].get('描述', {}).get('rich_text', [])
                description = desc_array[0]['text']['content'] if desc_array else "无描述"
                
                lists[list_id] = ForwardList(
                    list_id=list_id,
                    list_name=list_name,
                    description=description,
                    groups=[]
                )
                logger.info(f"成功处理列表: {list_id} - {list_name}")
            except Exception as e:
                logger.error(f"处理列表时出错: {e}")
                continue

        # 获取所有活跃的群组
        groups_response = self.notion.databases.query(
            database_id=self.groups_db_id,
            filter={
                "property": "是否转发",
                "checkbox": {
                    "equals": True
                }
            }
        )
        
        logger.info(f"获取到 {len(groups_response['results'])} 个群组")

        for page in groups_response['results']:
            try:
                # 修改这里：使用正确的关联字段名称
                relation_array = page['properties'].get('转发群聊分组', {}).get('relation', [])
                if not relation_array:
                    logger.warning(f"群组缺少分组关联: {page['properties']['群名']['title'][0]['text']['content']}")
                    continue
                    
                list_id = relation_array[0]['id']
                # 获取关联的 list_id
                list_page = self.notion.pages.retrieve(list_id)
                list_id = list_page['properties']['分组编号']['number']
                
                # 检查群组信息
                wxid_array = page['properties'].get('group_wxid', {}).get('rich_text', [])
                name_array = page['properties'].get('群名', {}).get('title', [])
                
                if not wxid_array or not name_array:
                    logger.warning(f"群组信息不完整: {page['properties']['群名']['title'][0]['text']['content']}")
                    continue
                    
                if list_id in lists:
                    lists[list_id].groups.append({
                        'group_wxid': wxid_array[0]['text']['content'],
                        'group_name': name_array[0]['text']['content']
                    })
                    logger.info(f"成功添加群组到列表 {list_id}")
            except Exception as e:
                logger.error(f"处理群组时出错: {e}")
                continue

        result_lists = list(lists.values())
        # 存入缓存
        self._set_cache('lists', result_lists)
        logger.info(f"成功获取 {len(result_lists)} 个转发列表")
        return result_lists

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """获取指定列表ID的所有群wxid（带缓存）"""
        cache_key = f'groups_{list_id}'
        
        # 尝试从缓存获取
        cached_groups = self._get_cache(cache_key)
        if cached_groups is not None:
            return cached_groups

        # 缓存未命中，从 Notion 获取数据
        groups = []
        
        # 首先获取list_id对应的page_id
        lists_response = self.notion.databases.query(
            database_id=self.lists_db_id,
            filter={
                "and": [
                    {
                        "property": "分组编号",
                        "number": {
                            "equals": list_id
                        }
                    },
                    {
                        "property": "是否转发",
                        "checkbox": {
                            "equals": True
                        }
                    }
                ]
            }
        )
        
        if not lists_response['results']:
            return []

        list_page_id = lists_response['results'][0]['id']
        
        # 查询关联的群组
        groups_response = self.notion.databases.query(
            database_id=self.groups_db_id,
            filter={
                "and": [
                    {
                        "property": "分组编号",
                        "relation": {
                            "contains": list_page_id
                        }
                    },
                    {
                        "property": "是否转发",
                        "checkbox": {
                            "equals": True
                        }
                    }
                ]
            }
        )

        groups = [
            page['properties']['group_wxid']['rich_text'][0]['text']['content']
            for page in groups_response['results']
        ] 

        # 存入缓存
        self._set_cache(cache_key, groups)
        return groups

    def refresh_lists(self) -> None:
        """强制刷新列表缓存"""
        self._cache['lists'] = None
        self.get_all_lists()

    def refresh_groups(self, list_id: Optional[int] = None) -> None:
        """强制刷新群组缓存
        :param list_id: 指定刷新某个列表的群组，None 表示刷新所有
        """
        if list_id is not None:
            cache_key = f'groups_{list_id}'
            self._cache[cache_key] = None
            self.get_groups_by_list_id(list_id)
        else:
            self._cache['groups'] = {}