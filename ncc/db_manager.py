import sqlite3
from contextlib import contextmanager
import logging
from typing import List, Dict, Optional
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "notion_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        with self.get_db() as conn:
            cur = conn.cursor()
            
            # 群组表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    wxid TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    welcome_enabled INTEGER DEFAULT 0,
                    list_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 转发列表表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS forward_lists (
                    list_id INTEGER PRIMARY KEY,
                    list_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 管理员表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    wxid TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 迎新消息表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_wxid TEXT NOT NULL,
                    message_type INTEGER NOT NULL,
                    content TEXT,
                    extra TEXT,
                    sequence INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (group_wxid) REFERENCES groups (wxid)
                )
            ''')
            
            # 创建索引
            cur.execute('CREATE INDEX IF NOT EXISTS idx_groups_list_id ON groups(list_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_welcome_messages_group ON welcome_messages(group_wxid)')
            
            conn.commit()

    @contextmanager
    def get_db(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def update_groups(self, groups: List[Dict]):
        """更新群组信息"""
        with self.get_db() as conn:
            cur = conn.cursor()
            for group in groups:
                cur.execute('''
                    INSERT OR REPLACE INTO groups (wxid, name, welcome_enabled, list_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (group['wxid'], group['name'], group.get('welcome_enabled', 0), group.get('list_id')))
            conn.commit()

    def update_forward_lists(self, lists: List[Dict]):
        """更新转发列表信息"""
        with self.get_db() as conn:
            cur = conn.cursor()
            for lst in lists:
                cur.execute('''
                    INSERT OR REPLACE INTO forward_lists (list_id, list_name, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (lst['list_id'], lst['list_name']))
            conn.commit()

    def update_admins(self, admins: List[Dict]):
        """更新管理员信息"""
        with self.get_db() as conn:
            cur = conn.cursor()
            for admin in admins:
                cur.execute('''
                    INSERT OR REPLACE INTO admins (wxid, name, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (admin['wxid'], admin['name']))
            conn.commit()

    def get_groups_by_list_id(self, list_id: int) -> List[str]:
        """获取指定列表ID的所有群组wxid"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT wxid FROM groups WHERE list_id = ?', (list_id,))
            return [row[0] for row in cur.fetchall()]

    def get_admin_wxids(self) -> List[str]:
        """获取所有管理员的wxid"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT wxid FROM admins')
            return [row[0] for row in cur.fetchall()]

    def get_admin_names(self) -> List[str]:
        """获取所有管理员的名称"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT name FROM admins')
            return [row[0] for row in cur.fetchall()]

    def get_welcome_enabled_groups(self) -> List[Dict]:
        """获取所有启用迎新消息的群组"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT wxid, name, welcome_enabled, list_id 
                FROM groups 
                WHERE welcome_enabled = 1
            ''')
            return [
                {
                    'wxid': row[0],
                    'name': row[1],
                    'welcome_enabled': row[2],
                    'list_id': row[3]
                }
                for row in cur.fetchall()
            ]

    def get_welcome_messages(self, group_wxid: str) -> List[Dict]:
        """获取指定群的迎新消息"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT message_type, content, extra, sequence
                FROM welcome_messages
                WHERE group_wxid = ?
                ORDER BY sequence
            ''', (group_wxid,))
            return [
                {
                    'type': row[0],
                    'content': row[1],
                    'extra': row[2],
                    'sequence': row[3]
                }
                for row in cur.fetchall()
            ]

    def save_welcome_messages(self, group_wxid: str, messages: List[Dict]):
        """保存群组的迎新消息"""
        with self.get_db() as conn:
            cur = conn.cursor()
            # 先删除原有的消息
            cur.execute('DELETE FROM welcome_messages WHERE group_wxid = ?', (group_wxid,))
            # 插入新的消息
            for i, msg in enumerate(messages):
                cur.execute('''
                    INSERT INTO welcome_messages 
                    (group_wxid, message_type, content, extra, sequence)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    group_wxid,
                    msg['type'],
                    msg.get('content'),
                    msg.get('extra'),
                    i
                ))
            conn.commit()

    def migrate_from_json(self, json_file_path: str):
        """从JSON文件迁移数据"""
        if not os.path.exists(json_file_path):
            logger.warning(f"JSON文件不存在: {json_file_path}")
            return
            
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if 'groups' in data:
                self.update_groups(data['groups'])
            if 'lists' in data:
                self.update_forward_lists(data['lists'])
            if 'admins' in data:
                self.update_admins(data['admins'])
                
            logger.info(f"从 {json_file_path} 迁移数据成功")
        except Exception as e:
            logger.error(f"迁移数据失败: {e}")
            raise 