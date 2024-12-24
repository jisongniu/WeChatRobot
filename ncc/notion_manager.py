from typing import List, Dict, Optional
import json
import os
from datetime import datetime
from dataclasses import dataclass
from notion_client import Client
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# 将处理器添加到日志记录器
logger.addHandler(console_handler)

# 防止日志重复
logger.propagate = False

@dataclass
class NotionCache:
    """原始 Notion 数据的缓存结构"""
    last_updated: str
    lists_data: List[dict]  # 原始列表数据
    groups_data: List[dict]  # 原始群组数据

@dataclass
class ForwardList:
    """处理后的转发列表结构"""
    list_id: int
    list_name: str
    groups: List[Dict[str, str]]

class NotionManager:
    def __init__(self, token: str, lists_db_id: str, groups_db_id: str, admins_db_id: str, wcf=None):
        self.notion = Client(auth=token)
        self.lists_db_id = lists_db_id
        self.groups_db_id = groups_db_id
        self.admins_db_id = admins_db_id
        self.wcf = wcf
        self.local_data_path = "data/notion_cache.json"
        self.welcome_groups = {}  # {group_wxid: welcome_url}
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.local_data_path), exist_ok=True)

    # 获取 Notion 原始数据，存储为notion_cache.json
    def fetch_notion_data(self) -> bool:
        """从 Notion 获取原始数据并缓存到本地"""
        try:
            logger.info("开始从 Notion 获取数据...")
            
            # 获取所有列表数据（不做过滤）
            lists_response = self.notion.databases.query(
                database_id=self.lists_db_id
            )
            
            # 获取所有群组数据（不做过滤）
            groups_response = self.notion.databases.query(
                database_id=self.groups_db_id
            )

            # 获取所有管理员数据
            admins_response = self.notion.databases.query(
                database_id=self.admins_db_id
            )
            
            # 保存原始数据到本地
            cache_data = {
                "last_updated": datetime.now().isoformat(),
                "lists": lists_response['results'],
                "groups": groups_response['results'],
                "admins": admins_response['results']
            }
            
            with open(self.local_data_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            logger.info("成功缓存 Notion 数据到本地")
            return True
            
        except Exception as e:
            logger.error(f"获取 Notion 数据失败: {e}", exc_info=True)
            return False

    def get_all_lists_and_groups(self) -> List[ForwardList]:
        """获取所有转发列表及其群组"""
        try:
            # 检查并加载缓存数据
            if not os.path.exists(self.local_data_path):
                logger.warning("本地缓存不存在，尝试从 Notion 获取数据...")
                if not self.fetch_notion_data():
                    return []
            
            # 读取缓存数据
            with open(self.local_data_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            lists = {}
            
            # 从缓存中筛选启用的转发列表
            enabled_lists = [
                page for page in cache_data['lists']
                if page['properties'].get('是否转发', {}).get('checkbox', False)
            ]
            logger.info(f"获取到 {len(enabled_lists)} 个启用的转发列表")
            
            # 从缓存中筛选允许发言的群组
            enabled_groups = [
                page for page in cache_data['groups']
                if page['properties'].get('允许发言', {}).get('checkbox', False)
            ]

            # 3. 构建群组 wxid 映射（如果有 wcf）
            group_wxids = {}
            if self.wcf:
                chatrooms = self.wcf.query_sql(
                    "MicroMsg.db",
                    "SELECT UserName, NickName FROM Contact WHERE Type=2 AND UserName LIKE '%@chatroom';"
                )
                group_wxids = {
                    room['NickName']: room['UserName']
                    for room in chatrooms
                }

            # 处理每个启用的列表
            for page in enabled_lists:
                list_id = page['properties'].get('分组编号', {}).get('number')
                if not list_id:
                    continue
                
                title = page['properties'].get('组名', {}).get('title', [])
                if not title:
                    continue
                
                list_name = title[0]['text']['content']
                lists[list_id] = ForwardList(
                    list_id=list_id,
                    list_name=list_name,
                    groups=[]
                )

            # 处理每个允许发言的群组
            for page in enabled_groups:
                try:
                    name_array = page['properties'].get('群名', {}).get('title', [])
                    if not name_array:
                        continue
                    
                    group_name = name_array[0]['text']['content']
                    
                    # 获取群的 wxid
                    wxid = group_wxids.get(group_name)
                    
                    # 如果找到了 wxid，更新到 Notion
                    if wxid:
                        self._update_group_wxid(page['id'], wxid)
                    
                    # 处理群组关联
                    relations = page['properties'].get('转发群聊分组', {}).get('relation', [])
                    
                    # 将群组添加到每个关联的列表中
                    for relation in relations:
                        for list_data in cache_data['lists']:
                            if list_data['id'] == relation['id']:
                                list_id = list_data['properties']['分组编号']['number']
                                if list_id in lists:
                                    lists[list_id].groups.append({
                                        'group_name': group_name,
                                        'wxid': wxid
                                    })
                except Exception as e:
                    logger.error(f"处理群组时出错: {e}")
                    continue

            return list(lists.values())
            
        except Exception as e:
            logger.error(f"获取列表失败: {e}", exc_info=True)
            return []

    def _update_group_wxid(self, page_id: str, wxid: str) -> None:
        """更新群组的 wxid 到 Notion
        
        Args:
            page_id: Notion 页面 ID
            wxid: 微信群 ID
        """
        try:
            self.notion.pages.update(
                page_id=page_id,
                properties={
                    "group_wxid": {  # Notion 中需要有这个属性
                        "rich_text": [{
                            "text": {
                                "content": wxid
                            }
                        }]
                    }
                }
            )
            logger.debug(f"成功更新群组 wxid 到 Notioin: {wxid}")
        except Exception as e:
            logger.error(f"更新群组 wxid 到 Notion 失败: {e}")

    def get_all_allowed_groups(self) -> List[str]:
        """获取所有允许机器人响应的群组wxid列表"""
        try:
            # 检查并加载缓存数据
            if not os.path.exists(self.local_data_path):
                logger.warning("本地缓存不存在，尝试从 Notion 获取数据...")
                if not self.fetch_notion_data():
                    return []
            
            # 读取缓存数据
            with open(self.local_data_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 获取微信群 wxid 映射
            wxid_map = {}
            if self.wcf:
                chatrooms = self.wcf.query_sql(
                    "MicroMsg.db",
                    "SELECT UserName, NickName FROM Contact WHERE Type=2 AND UserName LIKE '%@chatroom';"
                )
                wxid_map = {
                    room['NickName']: room['UserName']
                    for room in chatrooms
                }

            # 从缓存中筛选允许发言的群组
            allowed_groups = []
            for page in cache_data.get('groups', []):
                # 检查是否允许发言
                if not page['properties'].get('允许发言', {}).get('checkbox', False):
                    continue
                
                # 获取群名
                group_name = page['properties'].get('群名', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                if not group_name:
                    continue
                    
                # 先尝试从缓存获取 wxid
                wxid_texts = page['properties'].get('group_wxid', {}).get('rich_text', [])
                wxid = wxid_texts[0]['text']['content'] if wxid_texts else None
                
                # 如果缓存中没有 wxid，尝试从微信获取
                if not wxid and wxid_map:
                    wxid = wxid_map.get(group_name)
                    if wxid:
                        # 更新本地缓存
                        for group in cache_data['groups']:
                            if group['id'] == page['id']:
                                if 'group_wxid' not in group['properties']:
                                    group['properties']['group_wxid'] = {'rich_text': []}
                                group['properties']['group_wxid']['rich_text'] = [{
                                    'text': {'content': wxid}
                                }]
                        
                        # 保存更新后的缓存
                        with open(self.local_data_path, 'w', encoding='utf-8') as f:
                            json.dump(cache_data, f, ensure_ascii=False, indent=2)
                            
                        logger.info(f"找到群 {group_name} 的 wxid: {wxid}，正在更新到本地缓存和 Notion")
                        # 更新到 Notion
                        self._update_group_wxid(page['id'], wxid)
                
                if wxid:
                    allowed_groups.append(wxid)
                    logger.debug(f"添加允许发言的群: {group_name} ({wxid})")
                else:
                    logger.warning(f"群 {group_name} 未找到对应的 wxid")
            
            #logger.info(f"共找到 {len(allowed_groups)} 个允许发言的群组")
            return allowed_groups
            
        except Exception as e:
            logger.error(f"获取允许响应的群组失败: {e}")
            return []

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """根据列表ID获取该列表下可转发到的群组wxid列表"""
        try:
            forward_lists = self.get_all_lists_and_groups()
            for lst in forward_lists:
                if lst.list_id == list_id:
                    return [
                        group['wxid'] 
                        for group in lst.groups 
                        if group.get('wxid')  # 只返回有 wxid 的群组
                    ]
            return []
        except Exception as e:
            logger.error(f"获取转发列表的群组失败: {e}")
            return []

    def get_groups_info(self) -> Dict[str, str]:
        """获取群名到群ID的映射
        Returns:
            Dict[str, str]: {群名: 群ID}
        """
        try:
            # 缓存处理
            if hasattr(self, '_groups_cache'):
                return self._groups_cache
                
            # 获取数据
            groups = {}
            lists = self.get_all_lists_and_groups()
            for lst in lists:
                for group in lst.groups:
                    name = group.get('group_name')
                    wxid = group.get('wxid')
                    if name and wxid:
                        groups[name] = wxid
                        
            # 保存缓存
            self._groups_cache = groups
            return groups
            
        except Exception as e:
            logger.error(f"获取群组信息失败: {e}")
            return {}

    def get_admins(self) -> List[str]:
        """获取所有管理员的wxid列表"""
        try:
            # 检查并加载缓存数据
            if not os.path.exists(self.local_data_path):
                logger.warning("本地缓存不存在，尝试从 Notion 获取数据...")
                if not self.fetch_notion_data():
                    return []
            
            # 读取缓存数据
            with open(self.local_data_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 从缓存中获取管理员数据
            admin_wxids = []
            for admin in cache_data.get('admins', []):
                # 获取wxid属性
                wxid_texts = admin['properties'].get('wxid', {}).get('rich_text', [])
                if wxid_texts:
                    wxid = wxid_texts[0]['text']['content']
                    admin_wxids.append(wxid)
            
            return admin_wxids
            
        except Exception as e:
            logger.error(f"获取管理员列表失败: {e}")
            return []







        