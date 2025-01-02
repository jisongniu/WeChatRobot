import sqlite3
from contextlib import contextmanager
import logging
from typing import List, Dict, Optional
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = None):
        """初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，如果为 None，则使用默认路径 data/ncc_data.db
        """
        if db_path is None:
            # 获取项目根目录
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # 确保 data 目录存在
            data_dir = os.path.join(root_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            # 设置数据库路径
            self.db_path = os.path.join(data_dir, "ncc_data.db")
        else:
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
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 群组和列表的关联表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS group_lists (
                    group_wxid TEXT NOT NULL,
                    list_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_wxid, list_id),
                    FOREIGN KEY (group_wxid) REFERENCES groups (wxid),
                    FOREIGN KEY (list_id) REFERENCES forward_lists (list_id)
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
            cur.execute('CREATE INDEX IF NOT EXISTS idx_group_lists_group ON group_lists(group_wxid)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_group_lists_list ON group_lists(list_id)')
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
                    # 更新群组基本信息
                    cur.execute('''
                        INSERT OR REPLACE INTO groups 
                        (wxid, name, welcome_enabled, allow_forward, allow_speak, welcome_url, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (
                        group['wxid'], 
                        group['name'],
                        1 if group.get('welcome_enabled', 0) else 0,  # 确保布尔值被正确转换为整数
                        1 if group.get('allow_forward', 0) else 0,
                        1 if group.get('allow_speak', 0) else 0,
                        group.get('welcome_url')
                    ))
                    
                    # 更新群组的列表关联
                    if 'list_ids' in group:
                        # 先删除该群组的所有列表关联
                        cur.execute('DELETE FROM group_lists WHERE group_wxid = ?', (group['wxid'],))
                        # 添加新的列表关联
                        for list_id in group['list_ids']:
                            if list_id is not None:
                                cur.execute('''
                                    INSERT INTO group_lists (group_wxid, list_id, updated_at)
                                    VALUES (?, ?, CURRENT_TIMESTAMP)
                                ''', (group['wxid'], list_id))
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
                        INSERT OR REPLACE INTO forward_lists (list_id, list_name, description, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ''', (lst['list_id'], lst['list_name'], lst.get('description', '')))
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
            cur.execute('''
                SELECT g.wxid 
                FROM groups g
                JOIN group_lists gl ON g.wxid = gl.group_wxid
                WHERE gl.list_id = ?
            ''', (list_id,))
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
                SELECT wxid, name, welcome_enabled 
                FROM groups 
                WHERE welcome_enabled = 1
            ''')
            return [
                {
                    'wxid': row[0],
                    'name': row[1],
                    'welcome_enabled': row[2]
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
                SELECT wxid, name, welcome_enabled, allow_forward, allow_speak
                FROM groups 
                WHERE allow_speak = 1
            ''')
            return [
                {
                    'wxid': row[0],
                    'name': row[1],
                    'welcome_enabled': row[2],
                    'allow_forward': row[3],
                    'allow_speak': row[4]
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