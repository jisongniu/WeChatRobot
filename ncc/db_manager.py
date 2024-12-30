import sqlite3
from contextlib import contextmanager
import logging
from typing import List, Dict, Optional
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = "ncc_data.db"):
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
                    allow_forward INTEGER DEFAULT 0,  -- 允许转发
                    allow_speak INTEGER DEFAULT 0,    -- 允许发言
                    list_id INTEGER,
                    welcome_url TEXT,
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
                    operator TEXT NOT NULL,  -- 操作者的wxid
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (group_wxid) REFERENCES groups (wxid),
                    FOREIGN KEY (operator) REFERENCES admins (wxid)
                )
            ''')
            
            # 创建索引
            cur.execute('CREATE INDEX IF NOT EXISTS idx_groups_list_id ON groups(list_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_welcome_messages_group ON welcome_messages(group_wxid)')
            
            # 关键词表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (group_id) REFERENCES groups (wxid)
                )
            ''')
            
            # 创建关键词索引
            cur.execute('CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword)')
            
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
        """更新群组信息，使用事务确保原子性"""
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                for group in groups:
                    cur.execute('''
                        INSERT OR REPLACE INTO groups 
                        (wxid, name, welcome_enabled, allow_forward, allow_speak, list_id, welcome_url, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (
                        group['wxid'], 
                        group['name'], 
                        group.get('welcome_enabled', 0),
                        group.get('allow_forward', 0),
                        group.get('allow_speak', 0),
                        group.get('list_id'),
                        group.get('welcome_url')
                    ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"更新群组信息失败: {e}")
                raise

    def update_forward_lists(self, lists: List[Dict]):
        """更新转发列表信息，使用事务确保原子性"""
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                for lst in lists:
                    cur.execute('''
                        INSERT OR REPLACE INTO forward_lists (list_id, list_name, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    ''', (lst['list_id'], lst['list_name']))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"更新转发列表失败: {e}")
                raise

    def update_admins(self, admins: List[Dict]):
        """更新管理员信息，使用事务确保原子性"""
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                for admin in admins:
                    cur.execute('''
                        INSERT OR REPLACE INTO admins (wxid, name, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    ''', (admin['wxid'], admin['name']))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"更新管理员信息失败: {e}")
                raise

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
                SELECT message_type, content, extra
                FROM welcome_messages
                WHERE group_wxid = ?
                ORDER BY id
            ''', (group_wxid,))
            return [
                {
                    'type': row[0],
                    'content': row[1],
                    'extra': row[2]
                }
                for row in cur.fetchall()
            ]

    def save_welcome_messages(self, group_wxid: str, messages: List[Dict], operator: str):
        """保存群组的迎新消息，使用事务确保原子性
        
        Args:
            group_wxid: 群wxid
            messages: 消息列表
            operator: 操作者wxid
        """
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                # 先删除原有的消息
                cur.execute('DELETE FROM welcome_messages WHERE group_wxid = ?', (group_wxid,))
                # 插入新的消息
                for msg in messages:
                    cur.execute('''
                        INSERT INTO welcome_messages 
                        (group_wxid, message_type, content, extra, operator)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        group_wxid,
                        msg['type'],
                        msg.get('content'),
                        msg.get('extra'),
                        operator
                    ))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"保存迎新消息失败: {e}")
                raise

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

    def get_welcome_url(self, group_id: str) -> Optional[str]:
        """获取群的欢迎小卡片URL"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT welcome_url FROM groups WHERE wxid = ?', (group_id,))
            result = cur.fetchone()
            return result[0] if result and result[0] else None

    def set_welcome_url(self, group_id: str, welcome_url: str) -> bool:
        """设置群的欢迎小卡片URL，使用事务确保原子性"""
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    UPDATE groups 
                    SET welcome_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE wxid = ?
                ''', (welcome_url, group_id))
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                logger.error(f"设置欢迎小卡片URL失败: {e}")
                return False

    def get_admin_name_by_wxid(self, wxid: str) -> Optional[str]:
        """根据wxid获取管理员昵称"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT name FROM admins WHERE wxid = ?', (wxid,))
            result = cur.fetchone()
            return result[0] if result else wxid  # 如果找不到，返回wxid作为后备 

    def get_speak_enabled_groups(self) -> List[Dict]:
        """获取所有允许发言的群组"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT wxid, name, welcome_enabled, allow_forward, allow_speak, list_id 
                FROM groups 
                WHERE allow_speak = 1
            ''')
            return [
                {
                    'wxid': row[0],
                    'name': row[1],
                    'welcome_enabled': row[2],
                    'allow_forward': row[3],
                    'allow_speak': row[4],
                    'list_id': row[5]
                }
                for row in cur.fetchall()
            ] 

    def update_keywords(self, keywords_data: List[Dict]):
        """更新关键词数据，使用事务确保原子性"""
        with self.get_db() as conn:
            try:
                cur = conn.cursor()
                # 先清空旧数据
                cur.execute('DELETE FROM keywords')
                # 插入新数据
                for item in keywords_data:
                    cur.execute('''
                        INSERT INTO keywords (keyword, group_id, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    ''', (item['keyword'], item['group_id']))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"更新关键词数据失败: {e}")
                raise

    def get_groups_by_keyword(self, keyword: str) -> List[str]:
        """根据关键词获取对应的群组wxid列表"""
        with self.get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT group_id FROM keywords WHERE keyword = ?', (keyword,))
            return [row[0] for row in cur.fetchall()] 