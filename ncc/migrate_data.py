import os
import json
import logging
import sys

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ncc.db_manager import DatabaseManager

def main():
    """从 JSON 文件迁移数据到 SQLite 数据库"""
    try:
        # 初始化数据库管理器
        db = DatabaseManager()
        
        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_file = os.path.join(current_dir, "data.json")
        
        # 执行迁移
        db.migrate_from_json(json_file)
        print("数据迁移成功！")
        
    except Exception as e:
        print(f"迁移失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 