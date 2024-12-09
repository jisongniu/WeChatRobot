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
        self.local_data_path = "data/notion_cache.json"
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.local_data_path), exist_ok=True)

    def _get_group_wxid(self, group_name: str) -> Optional[str]:
        """通过群名获取群wxid"""
        if self._cache['wxid_map'] is None:
            # 使用 query_sql 获取所有群聊
            chatrooms = self.wcf.query_sql(
                "MicroMsg.db",
                "SELECT UserName, NickName FROM Contact WHERE Type=2 AND UserName LIKE '%@chatroom';"
            )
            # 构建群名到wxid的映射
            self._cache['wxid_map'] = {
                room['NickName']: room['UserName']
                for room in chatrooms
            }
            logger.info(f"已缓存 {len(chatrooms)} 个群聊的wxid映射")
            # 打印所有群名用于调试
            logger.debug(f"所有群名: {list(self._cache['wxid_map'].keys())}")

        wxid = self._cache['wxid_map'].get(group_name)
        if wxid:
            logger.debug(f"找到群 {group_name} 的wxid: {wxid}")
        else:
            logger.warning(f"未找到群 {group_name} 的wxid")
        return wxid

    def get_all_lists(self) -> List[ForwardList]:
        """获取所有转发列表及其群组"""
        try:
            logger.info("开始从 Notion 获取列表信息...")
            lists = {}
            
            # 1. 获取所有启用的转发列表
            logger.info("正在查询转发列表...")
            lists_response = self.notion.databases.query(
                database_id=self.lists_db_id,
                filter={
                    "property": "是否转发",
                    "checkbox": {
                        "equals": True
                    }
                }
            )
            logger.info(f"获取到 {len(lists_response['results'])} 个转发列表")
            
            # 2. 获取所有允许发言的群组
            groups_response = self.notion.databases.query(
                database_id=self.groups_db_id,
                filter={
                    "property": "允许发言",
                    "checkbox": {
                        "equals": True
                    }
                }
            )

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

            # 4. 处理每个列表
            for page in lists_response['results']:
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

            # 5. 处理每个群组并关联到列表
            for page in groups_response['results']:
                try:
                    # 获取群名
                    name_array = page['properties'].get('群名', {}).get('title', [])
                    if not name_array:
                        continue
                    group_name = name_array[0]['text']['content']
                    
                    # 获取群的 wxid
                    wxid = group_wxids.get(group_name)
                    
                    # 获取关联的列表
                    relations = page['properties'].get('转发群聊分组', {}).get('relation', [])
                    
                    # 将群组添加到每个关联的列表中
                    for relation in relations:
                        list_page = self.notion.pages.retrieve(relation['id'])
                        list_id = list_page['properties']['分组编号']['number']
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

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """根据列表ID获取对应的群组wxid列表（从本地缓存读取）"""
        try:
            lists = self.load_lists_from_local()
            for lst in lists:
                if lst.list_id == list_id:
                    return [
                        group['wxid'] 
                        for group in lst.groups 
                        if group.get('wxid')  # 只返回有 wxid 的群组
                    ]
            return []
        except Exception as e:
            logger.error(f"获取群组列表失败: {e}")
            return []

    def refresh_lists(self) -> None:
        """刷新列表缓存"""
        self._cache['wxid_map'] = None
        logger.info("已刷新列表")


    def get_all_allowed_groups(self) -> List[str]:
        """获取所有允许发言的群组wxid列表"""
        try:
            groups = []
            lists = self.load_lists_from_local()
            if not lists:  # 如果本地缓存不存在或为空
                logger.warning("本地缓存不存在或为空，请先刷新列表")
                return []
            
            # 从所有列表中收集群组的 wxid
            for lst in lists:
                for group in lst.groups:
                    if wxid := group.get('wxid'):  # 只添加有 wxid 的群组
                        if wxid not in groups:  # 避免重复
                            groups.append(wxid)
            
            return groups
        except Exception as e:
            logger.error(f"获取允许群组失败: {e}")
            return []

    def save_lists_to_local(self) -> bool:
        """将列表信息保存到本地文件"""
        try:
            logger.info("开始获取并保存列表信息...")
            lists = self.get_all_lists()
            if not lists:
                logger.error("未获取到任何列表信息")
                return False
            
            logger.info(f"成功获取 {len(lists)} 个列表")
            
            data = {
                "last_updated": datetime.now().isoformat(),
                "lists": [
                    {
                        "list_id": lst.list_id,
                        "list_name": lst.list_name,
                        "groups": lst.groups
                    }
                    for lst in lists
                ]
            }
            
            logger.info(f"准备保存到: {self.local_data_path}")
            with open(self.local_data_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info("成功保存列表信息到本地")
            return True
        except Exception as e:
            logger.error(f"保存列表信息到本地失败: {e}", exc_info=True)
            return False

    def load_lists_from_local(self) -> List[ForwardList]:
        """从本地文件加载列表信息"""
        try:
            if not os.path.exists(self.local_data_path):
                logger.warning("本地缓存文件不存在")
                return []
                
            with open(self.local_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            lists = []
            for lst_data in data['lists']:
                lists.append(ForwardList(
                    list_id=lst_data['list_id'],
                    list_name=lst_data['list_name'],
                    groups=lst_data['groups']
                ))
            
            logger.info(f"成功从本地加载 {len(lists)} 个列表")
            return lists
        except Exception as e:
            logger.error(f"从本地加载列表信息失败: {e}")
            return []

    def get_local_lists_info(self) -> str:
        """获取本地保存的列表信息的可读形式"""
        try:
            if not os.path.exists(self.local_data_path):
                return "未找到本地缓存，请先使用刷新列表功能"
                
            with open(self.local_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            last_updated = datetime.fromisoformat(data['last_updated'])
            info = f"最后更新时间：{last_updated.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            for lst in data['lists']:
                info += f"列表 {lst['list_id']}: {lst['list_name']}\n"
                info += "包含群组：\n"
                for group in lst['groups']:
                    info += f"- {group['group_name']}\n"
                info += "\n"
                
            return info
        except Exception as e:
            logger.error(f"获取本地列表信息失败: {e}")
            return "获取本地列表信息失败"

    def get_list_info_by_id(self, list_id: int) -> str:
        """根据列表ID获取特定列表的信息"""
        try:
            lists = self.load_lists_from_local()
            for lst in lists:
                if lst.list_id == list_id:
                    info = f"列表 {lst.list_id}: {lst.list_name}\n"
                    info += "包含群组：\n"
                    for group in lst.groups:
                        info += f"- {group['group_name']}\n"
                    return info
            return f"未找到ID为 {list_id} 的列表"
        except Exception as e:
            logger.error(f"获取列表信息失败: {e}")
            return "获取列表信息失败"
        