from typing import List, Dict, Optional
import json
import os
from datetime import datetime
from dataclasses import dataclass
from notion_client import Client
import logging
from wcferry import Wcf
from .db_manager import DatabaseManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# 将处理器添加到日志记录器
logger.addHandler(console_handler)

# 防止日志重复
logger.propagate = False

@dataclass
class ForwardList:
    """处理后的转发列表结构"""
    list_id: int
    list_name: str
    groups: List[Dict[str, str]]

class NotionManager:
    def __init__(self, token: str, lists_db_id: str, groups_db_id: str, admins_db_id: str, keywords_db_id: str, wcf: Wcf, config=None):
        """初始化 NotionManager
        
        Args:
            token: Notion API token
            lists_db_id: 列表数据库ID
            groups_db_id: 群组数据库ID
            admins_db_id: 管理员数据库ID
            keywords_db_id: 关键词数据库ID
            wcf: WeChatFerry 实例
            config: 配置对象
        """
        self.wcf = wcf
        self.config = config
        self.notion = Client(auth=token)
        
        self.lists_db_id = lists_db_id
        self.groups_db_id = groups_db_id
        self.admins_db_id = admins_db_id
        self.keywords_db_id = keywords_db_id
        
        # 初始化数据库管理器
        self.db = DatabaseManager()

    def fetch_notion_data(self) -> bool:
        """从 Notion 获取原始数据并缓存到本地数据库"""
        try:
            logger.info("开始从 Notion 获取数据...")
            
            # 获取所有列表数据
            lists_response = self.notion.databases.query(database_id=self.lists_db_id)
            
            # 获取所有群组数据
            groups_response = self.notion.databases.query(database_id=self.groups_db_id)

            # 获取所有管理员数据
            admins_response = self.notion.databases.query(database_id=self.admins_db_id)
            
            # 获取所有关键词数据
            keywords_response = self.notion.databases.query(database_id=self.keywords_db_id)
            
            # 处理列表数据
            lists = []
            for page in lists_response['results']:
                list_id = page['properties'].get('分组编号', {}).get('number')
                title = page['properties'].get('组名', {}).get('title', [])
                if list_id and title:
                    lists.append({
                        'list_id': list_id,
                        'list_name': title[0]['text']['content']
                    })
            
            # 处理群组数据
            groups = []
            for page in groups_response['results']:
                group_name = page['properties'].get('群名', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                wxid_texts = page['properties'].get('group_wxid', {}).get('rich_text', [])
                wxid = wxid_texts[0]['text']['content'] if wxid_texts else None
                welcome_enabled = bool(page['properties'].get('迎新推送', {}).get('checkbox', False))
                welcome_url = page['properties'].get('迎新推送链接', {}).get('url')
                allow_forward = bool(page['properties'].get('允许转发', {}).get('checkbox', False))
                allow_speak = bool(page['properties'].get('允许发言', {}).get('checkbox', False))
                
                if group_name and wxid:
                    # 获取群组关联的列表ID
                    relations = page['properties'].get('转发群聊分组', {}).get('relation', [])
                    list_ids = []
                    if relations:
                        for relation in relations:
                            relation_id = relation['id']
                            # 查找对应的列表数据
                            for list_data in lists_response['results']:
                                if list_data['id'] == relation_id:
                                    list_id = list_data['properties'].get('分组编号', {}).get('number')
                                    if list_id is not None:
                                        list_ids.append(list_id)
                                    break
                    
                    groups.append({
                        'wxid': wxid,
                        'name': group_name,
                        'welcome_enabled': welcome_enabled,
                        'allow_forward': allow_forward,
                        'allow_speak': allow_speak,
                        'list_ids': list_ids,
                        'welcome_url': welcome_url
                    })
            
            # 处理管理员数据
            admins = []
            for page in admins_response['results']:
                name = page['properties'].get('称呼', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                wxid_texts = page['properties'].get('wxid', {}).get('rich_text', [])
                wxid = wxid_texts[0]['text']['content'] if wxid_texts else None
                
                if name and wxid:
                    admins.append({
                        'wxid': wxid,
                        'name': name
                    })
            
            # 处理关键词数据
            keywords = []
            for page in keywords_response['results']:
                # 获取关键词（标题）
                title = page['properties'].get('让对方回复', {}).get('title', [])
                if not title:
                    continue
                keyword = title[0]['text']['content']
                
                # 获取关联的群组
                relations = page['properties'].get('拉入群聊', {}).get('relation', [])
                if not relations:
                    continue
                
                # 遍历关联的群组，找到对应的wxid
                for relation in relations:
                    relation_id = relation['id']
                    # 在群组数据中查找对应的群组
                    for group in groups_response['results']:
                        if group['id'] == relation_id:
                            wxid_texts = group['properties'].get('group_wxid', {}).get('rich_text', [])
                            if wxid_texts:
                                wxid = wxid_texts[0]['text']['content']
                                keywords.append({
                                    'keyword': keyword,
                                    'group_id': wxid
                                })
            
            # 更新数据库
            self.db.update_forward_lists(lists)
            self.db.update_groups(groups)
            self.db.update_admins(admins)
            self.db.update_keywords(keywords)
            
            logger.info("成功更新本地数据库")
            return True
            
        except Exception as e:
            logger.error(f"获取 Notion 数据失败: {e}", exc_info=True)
            return False

    def get_forward_lists_and_groups(self) -> List[ForwardList]:
        """获取所有转发列表及其群组"""
        try:
            # 从数据库获取所有列表
            with self.db.get_db() as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT l.list_id, l.list_name, g.wxid, g.name
                    FROM forward_lists l
                    LEFT JOIN group_lists gl ON l.list_id = gl.list_id
                    LEFT JOIN groups g ON gl.group_wxid = g.wxid
                    ORDER BY l.list_id, g.name
                ''')
                rows = cur.fetchall()
            
            lists = {}
            for row in rows:
                list_id, list_name, group_wxid, group_name = row
                if list_id not in lists:
                    lists[list_id] = ForwardList(
                        list_id=list_id,
                        list_name=list_name,
                        groups=[]
                    )
                if group_wxid and group_name:  # 只添加有效的群组
                    lists[list_id].groups.append({
                        'group_name': group_name,
                        'wxid': group_wxid
                    })
            
            return list(lists.values())
            
        except Exception as e:
            logger.error(f"获取列表失败: {e}", exc_info=True)
            return []

    def _update_group_wxid(self, page_id: Optional[str], wxid: str, group_name: str) -> None:
        """创建或更新群组到 Notion
        
        Args:
            page_id: Notion 页面 ID，如果为 None 则创建新页面
            wxid: 微信群 ID
            group_name: 群名称
        """
        try:
            properties = {
                "群名": {
                    "title": [{
                        "text": {
                            "content": group_name
                        }
                    }]
                },
                "group_wxid": {
                    "rich_text": [{
                        "text": {
                            "content": wxid
                        }
                    }]
                }
            }
            
            if page_id:
                # 更新现有页面
                self.notion.pages.update(
                    page_id=page_id,
                    properties=properties
                )
            else:
                # 创建新页面
                properties.update({
                    "迎新推送": {"checkbox": True},
                    "允许转发": {"checkbox": True},
                    "允许发言": {"checkbox": True}
                })
                self.notion.pages.create(
                    parent={"database_id": self.groups_db_id},
                    properties=properties
                )
            
            # 更新本地数据库
            self.db.update_groups([{
                'wxid': wxid,
                'name': group_name,
                'welcome_enabled': True,
                'allow_forward': True,
                'allow_speak': True,
                'list_ids': [],
                'welcome_url': None
            }])
            
            logger.info(f"{'更新' if page_id else '创建'}群组: {group_name} ({wxid})")
            
        except Exception as e:
            logger.error(f"{'更新' if page_id else '创建'}群组失败: {e}")

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """获取指定列表ID的所有群组wxid"""
        return self.db.get_groups_by_list_id(list_id)

    def get_admins_wxid(self) -> List[str]:
        """获取所有管理员的wxid"""
        return self.db.get_admin_wxids()

    def get_admin_names(self) -> List[str]:
        """获取所有管理员的名称"""
        return self.db.get_admin_names()

    def create_new_group(self, wxid: str, group_name: str) -> bool:
        """在 Notion 中创建或更新群组记录
        
        Args:
            wxid: 微信群ID
            group_name: 群名称
            
        Returns:
            bool: 操作是否成功
        """
        try:
            self._update_group_wxid(None, wxid, group_name)
            return True
        except Exception as e:
            logger.error(f"创建/更新群组失败: {e}", exc_info=True)
            return False

