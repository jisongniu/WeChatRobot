# -*- coding: utf-8 -*-
from typing import Any, Callable, Dict, List, Optional, Union, Protocol
import schedule
import re
import json
from datetime import datetime, time, timedelta
import croniter
import logging
import threading
import time
from wcferry import Wcf

class MessageSender(Protocol):
    """消息发送器接口"""
    def send_message(self, message: str, target: Optional[str] = None, at_all: bool = False) -> bool:
        """发送消息到指定目标
        Args:
            message: 消息内容
            target: 目标(群ID/用户ID),None表示默认目标
            at_all: 是否@所有人
        """
        ...

class WCFMessageSender(MessageSender):
    """WCF框架消息发送适配器"""
    def __init__(self, wcf: Wcf, robot=None):
        self.wcf = wcf
        self.robot = robot  # 保存Robot实例的引用
    
    def get_group_id_by_name(self, group_name: str) -> Optional[str]:
        """通过群名查找群ID
        Args:
            group_name: 群名称
        Returns:
            Optional[str]: 群ID，未找到返回None
        """
        try:
            # 首先检查群是否在允许列表中
            if not self.robot or group_name not in self.robot.allowed_groups:
                logging.error(f"群[{group_name}]不在允许列表中或机器人没有发言权限")
                return None
            
            # 从允许列表中获取群ID
            return self.robot.allowed_groups.get(group_name)
            
        except Exception as e:
            logging.error(f"查找群ID失败: {e}")
            return None
    
    def send_message(self, message: str, target: Optional[str] = None, at_all: bool = False) -> bool:
        try:
            if target:
                # 如果target是群名而不是群ID，尝试查找群ID
                if target.startswith("group[") and target.endswith("]"):
                    group_name = target[6:-1]  # 提取群名
                    group_id = self.get_group_id_by_name(group_name)
                    if not group_id:
                        error_msg = (
                            f"无法发送消息到群[{group_name}]\n"
                            "可能原因:\n"
                            "1. 群名称不正确\n"
                            "2. 该群未在允许列表中\n"
                            "3. 机器人没有在该群的发言权限\n"
                            "请检查群名称或联系管理员添加权限"
                        )
                        self.wcf.send_text(error_msg, receiver)
                        return False
                    target = group_id
                
                if at_all:
                    # 使用wcf的@所有人功能
                    self.wcf.send_text(message, target, "notify@all")
                else:
                    self.wcf.send_text(message, target)
            else:
                # 使用task中保存的sender作为默认接收者
                receiver = target or self.task.sender
                self.wcf.send_text(message, receiver)
            return True
        except Exception as e:
            logging.error(f"发送消息失败: {e}")
            return False

class TimeTask:
    def __init__(self, task_id: str, schedule_type: str, time_str: str, 
                 message: str, target: Optional[str] = None, 
                 plugin_name: Optional[str] = None,
                 at_all: bool = False,
                 sender: Optional[str] = None) -> None:
        self.task_id = task_id
        self.schedule_type = schedule_type
        self.time_str = time_str
        self.message = message
        self.target = target
        self.plugin_name = plugin_name
        self.at_all = at_all
        self.sender = sender
        self.job = None

class JobManager:
    def __init__(self, wcf: Wcf, robot=None) -> None:
        """初始化任务管理器
        Args:
            wcf: WCF实例
            robot: Robot实例，用于访问群组权限
        """
        self.tasks: Dict[str, TimeTask] = {}
        self.plugins: Dict[str, Callable] = {}
        self.message_sender = WCFMessageSender(wcf, robot)
        self._load_tasks()
        self.start_job_checker()

    def start_job_checker(self):
        """启动定时任务检查器"""
        def job_checker():
            while True:
                try:
                    self.run_pending()
                    time.sleep(1)
                except Exception as e:
                    logging.error(f"定时任务检查异常: {e}")
                    time.sleep(5)
        
        threading.Thread(target=job_checker, daemon=True).start()

    def handle_command(self, message: str, sender: str) -> Optional[str]:
        """处理定时任务命令
        Args:
            message: 消息内容
        Returns:
            Optional[str]: 回复消息,None表示不是定时任务命令
        """
        if not message.startswith("$time"):
            return None
            
        try:
            if "取消任务" in message:
                task_id = message.split()[-1]
                return self.cancel_task(task_id)
                
            elif "任务列表" in message:
                return self.list_tasks()
                
            else:
                return self.add_task(message, sender)
                
        except Exception as e:
            logging.error(f"处理定时任务命令异常: {e}")
            return "处理命令时发生错误"

    def _load_tasks(self) -> None:
        """从文件加载保存的任务"""
        try:
            with open("tasks.json", "r", encoding="utf-8") as f:
                saved_tasks = json.load(f)
                for task_data in saved_tasks:
                    task = TimeTask(**task_data)
                    self._schedule_task(task)
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.error(f"加载任务失败: {e}")
    
    def _save_tasks(self) -> None:
        """保存任务到文件"""
        try:
            tasks_data = [
                {
                    "task_id": task.task_id,
                    "schedule_type": task.schedule_type,
                    "time_str": task.time_str,
                    "message": task.message,
                    "target": task.target,
                    "plugin_name": task.plugin_name,
                    "at_all": task.at_all
                }
                for task in self.tasks.values()
            ]
            with open("tasks.json", "w", encoding="utf-8") as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存任务失败: {e}")
    
    def register_plugin(self, name: str, func: Callable) -> None:
        """注册插件功能"""
        self.plugins[name] = func

    def parse_command(self, command: str) -> Optional[Dict]:
        """解析定时任务命令
        格式: $time 周期 时间 事件 [group[群名]] [@all]
        示例: 
        - $time 每天 08:00 打卡提醒 group[AAA] @all
        - $time 今天 20:23 提醒我时间
        - $time 明天 10:30 开会提醒
        - $time 工作日 09:00 晨会
        """
        if not command.startswith("$time "):
            return None
        
        # 检查是否有@all
        at_all = "@all" in command
        command = command.replace("@all", "").strip()
        
        pattern = r"\$time\s+([^\s]+)\s+([^\s]+)\s+(.+?)(?:\s+group\[([^\]]+)\])?$"
        match = re.match(pattern, command)
        if not match:
            return None
        
        schedule_type, time_str, message, group = match.groups()
        
        # 标准化周期类型
        if schedule_type in ["每天", "daily"]:
            schedule_type = "daily"
        elif schedule_type.startswith("每周"):
            schedule_type = "weekly"
        elif schedule_type in ["工作日", "workday"]:
            schedule_type = "workday"
        elif schedule_type.startswith("cron["):
            schedule_type = "cron"
            time_str = time_str.strip("[]")
        elif schedule_type in ["今天", "today"]:
            # 处理今天的情况
            schedule_type = datetime.now().strftime("%Y-%m-%d")
        elif schedule_type in ["明天", "tomorrow"]:
            # 处理明天的情况
            schedule_type = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            try:
                # 尝试解析具体日期
                datetime.strptime(schedule_type, "%Y-%m-%d")
                schedule_type = "date"
            except:
                return None
                
        # 标准化时间格式
        try:
            # 处理没有秒数的情况
            if len(time_str.split(":")) == 2:
                time_str = f"{time_str}:00"
            # 验证时间格式
            datetime.strptime(time_str, "%H:%M:%S")
        except:
            return None
            
        return {
            "schedule_type": schedule_type,
            "time_str": time_str,
            "message": message,
            "target": group,
            "at_all": at_all
        }

    def add_task(self, command: str, sender: str) -> str:
        """添加定时任务"""
        parsed = self.parse_command(command)
        if not parsed:
            return "命令格式错误"
            
        task_id = f"{len(self.tasks)}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        task = TimeTask(
            task_id=task_id,
            sender=sender,
            **parsed
        )
        
        # 设置定时任务
        if task.schedule_type == "daily":
            job = schedule.every().day.at(task.time_str).do(
                self._execute_task, task
            )
        elif task.schedule_type == "weekly":
            # 解析周几
            weekday = self._parse_weekday(parsed["schedule_type"])
            job = schedule.every().week.days[weekday].at(task.time_str).do(
                self._execute_task, task
            )
        elif task.schedule_type == "workday":
            # 工作日判断逻辑
            job = schedule.every().day.at(task.time_str).do(
                self._execute_task_if_workday, task
            )
        elif task.schedule_type == "cron":
            # cron表达式支持
            job = self._schedule_cron(task)
        else:  # date
            date = datetime.strptime(task.schedule_type, "%Y-%m-%d")
            job = schedule.every().day.at(task.time_str).do(
                self._execute_task_on_date, task, date
            )
            
        task.job = job
        self.tasks[task_id] = task
        
        self._save_tasks()  # 保存任务
        
        return f"定时任务添加成功! ID: {task_id}"

    def cancel_task(self, task_id: str) -> str:
        """取消定时任务"""
        if task_id not in self.tasks:
            return "任务不存在"
            
        task = self.tasks[task_id]
        schedule.cancel_job(task.job)
        del self.tasks[task_id]
        self._save_tasks()  # 保存任务
        return f"已取消任务 {task_id}"

    def list_tasks(self) -> str:
        """列出所有定时任务"""
        if not self.tasks:
            return "当前没有定时任务"
            
        result = []
        for task_id, task in self.tasks.items():
            result.append(
                f"ID: {task_id}\n"
                f"类型: {task.schedule_type}\n"
                f"时间: {task.time_str}\n"
                f"内容: {task.message}\n"
                f"目标: {task.target or '默认'}\n"
                "---"
            )
        return "\n".join(result)

    def _execute_task(self, task: TimeTask) -> None:
        """执行定时任务"""
        if task.plugin_name and task.plugin_name in self.plugins:
            self.plugins[task.plugin_name](task.message, task.target)
        else:
            # 发送普通消息
            if task.at_all and task.target:
                # 如果需要@所有人且是群消息
                self.message_sender.send_message(task.message, task.target, at_all=True)
            else:
                self.message_sender.send_message(task.message, task.target)

    def _execute_task_if_workday(self, task: TimeTask) -> None:
        """仅在工作日执行任务"""
        if datetime.now().weekday() < 5:  # 0-4 为周一至周五
            self._execute_task(task)

    def _execute_task_on_date(self, task: TimeTask, target_date: datetime) -> None:
        """在指定日期执行任务"""
        if datetime.now().date() == target_date.date():
            self._execute_task(task)

    def _schedule_cron(self, task: TimeTask) -> schedule.Job:
        """使用cron表达式调度任务"""
        cron = croniter.croniter(task.time_str)
        next_time = cron.get_next(datetime)
        
        # 创建一个每分钟检查的job
        def cron_checker():
            nonlocal next_time
            now = datetime.now()
            if now >= next_time:
                self._execute_task(task)
                next_time = cron.get_next(datetime)
                
        return schedule.every().minute.do(cron_checker)

    def _parse_weekday(self, weekday_str: str) -> int:
        """解析中文星期几为数字(0-6)"""
        weekday_map = {
            "一": 0, "二": 1, "三": 2, "四": 3,
            "五": 4, "六": 5, "日": 6, "天": 6
        }
        for day, num in weekday_map.items():
            if f"周{day}" in weekday_str or f"星期{day}" in weekday_str:
                return num
        return 0

    def run_pending(self) -> None:
        """运行待执行的任务"""
        schedule.run_pending()

