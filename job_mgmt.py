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
    def send_message(self, message: str, target: Optional[str] = None, at_all: bool = False, sender: Optional[str] = None) -> bool:
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
        """通过群名查找群ID"""
        try:
            # 1. 直接从 db_manager 获取群组信息
            groups = self.robot.db.get_speak_enabled_groups()
            groups_info = {group['name']: group['wxid'] for group in groups}
            
            # 2. 简单的字典查找
            if group_name in groups_info:
                group_id = groups_info[group_name]
                logging.debug(f"找到群: {group_name} -> {group_id}")
                return group_id
                
            logging.error(f"群[{group_name}]不在允许列表中")
            return None
            
        except Exception as e:
            logging.error(f"查找群ID失败: {e}")
            return None
    
    def send_message(self, message: str, target: Optional[str] = None, at_all: bool = False, sender: Optional[str] = None) -> bool:
        try:
            logging.debug(f"准备发送消息: msg={message}, target={target}, at_all={at_all}, sender={sender}")
            if target:
                if at_all:
                    # 使用wcf的@所有人功能
                    self.wcf.send_text(message, target, "notify@all")
                else:
                    self.wcf.send_text(message, target)
            else:
                # 使用传入的sender作为默认接收者
                receiver = target or sender
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
                    # 根据任务类型设置定时
                    if task.schedule_type == "daily":
                        job = schedule.every().day.at(task.time_str).do(
                            self._execute_task, task
                        )
                    elif task.schedule_type == "weekly":
                        # 解析周几
                        weekday = self._parse_weekday(task.schedule_type)
                        job = schedule.every().week.days[weekday].at(task.time_str).do(
                            self._execute_task, task
                        )
                    elif task.schedule_type == "workday":
                        job = schedule.every().day.at(task.time_str).do(
                            self._execute_task_if_workday, task
                        )
                    elif task.schedule_type == "cron":
                        job = self._schedule_cron(task)
                    else:  # date
                        date = datetime.strptime(task.schedule_type, "%Y-%m-%d")
                        job = schedule.every().day.at(task.time_str).do(
                            self._execute_task_on_date, task, date
                        )
                    
                    task.job = job
                    self.tasks[task.task_id] = task
                    
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
        #logging.info(f"命令匹配结果: {match.groups() if match else None}")
        if not match:
            return None
            
        schedule_type, time_str, message, group = match.groups()
        # logging.info(f"解析出的参数: type={schedule_type}, time={time_str}, msg={message}, group={group}")
        
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
        # logging.info(f"尝试添加任务: command={command}, sender={sender}")
        parsed = self.parse_command(command)
        logging.debug(f"解析结果: {parsed}")
        if not parsed:
            return "命令格式错误"
            
        # 如果是群消息，先转换群名为群ID
        target = parsed.get('target')
        if target:
            # 移除 group[] 包装（如果有的话）
            if target.startswith("group[") and target.endswith("]"):
                group_name = target[6:-1]
            else:
                group_name = target
                
            # 从 allowed_groups 中查找群ID
            group_id = self.message_sender.get_group_id_by_name(group_name)
            if not group_id:
                return f"无法找到群[{group_name}]的ID，请检查群名称或权限"
                
            logging.info(f"群名[{group_name}]已转换为群ID: {group_id}")
            parsed['target'] = group_id
            
        task_id = f"t{len(self.tasks)}_{int(datetime.now().timestamp())}"
        task = TimeTask(
            task_id=task_id,
            sender=sender,
            **parsed
        )
        logging.debug(f"创建任务对象: {task.__dict__}")
        
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
        try:
            logging.info(f"开始执行任务[{task.task_id}]: {task.__dict__}")
            
            if task.plugin_name and task.plugin_name in self.plugins:
                self.plugins[task.plugin_name](task.message, task.target)
            else:
                # 发送普通消息
                if task.at_all and task.target:
                    self.message_sender.send_message(task.message, task.target, at_all=True, sender=task.sender)
                else:
                    self.message_sender.send_message(task.message, task.target, sender=task.sender)
                logging.info(f"消息已发送到: {task.target}")
        except Exception as e:
            logging.error(f"执行任务[{task.task_id}]失败: {e}", exc_info=True)

    def _execute_task_if_workday(self, task: TimeTask) -> None:
        """仅在工作日执行任务"""
        if datetime.now().weekday() < 5:  # 0-4 为周一至周五
            self._execute_task(task)

    def _execute_task_on_date(self, task: TimeTask, target_date: datetime) -> None:
        """在指定日期执行任务"""
        now = datetime.now()
        task_time = datetime.strptime(task.time_str, "%H:%M:%S").time()
        target_datetime = datetime.combine(target_date.date(), task_time)
        
        logging.info(f"检查定时任务: now={now}, target={target_datetime}")
        
        if now.date() == target_date.date() and now.time() >= task_time:
            self._execute_task(task)
            # 任务执行完后，从任务列表中移除
            if task.task_id in self.tasks:
                schedule.cancel_job(task.job)
                del self.tasks[task.task_id]
                self._save_tasks()
                logging.info(f"一次性任务 {task.task_id} 执行完成，已移除")

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

    def clean_expired_tasks(self) -> None:
        """清理过期的一次性任务"""
        now = datetime.now()
        expired_tasks = []
        
        for task_id, task in self.tasks.items():
            # 检查一次性任务（date类型）是否过期
            if task.schedule_type.startswith('20'):  # 年份格式
                task_date = datetime.strptime(task.schedule_type, "%Y-%m-%d")
                task_time = datetime.strptime(task.time_str, "%H:%M:%S").time()
                task_datetime = datetime.combine(task_date.date(), task_time)
                
                # 只清理已经过期超过1分钟的任务
                if (now - task_datetime).total_seconds() > 60:
                    expired_tasks.append(task_id)
                    schedule.cancel_job(task.job)
        
        # 移除过期任务
        for task_id in expired_tasks:
            del self.tasks[task_id]
        
        if expired_tasks:
            self._save_tasks()
            logging.info(f"已清理 {len(expired_tasks)} 个过期任务")

    def run_pending(self) -> None:
        """运行待执行的任务"""
        self.clean_expired_tasks()  # 在执行完任务后再清理过期任务
        schedule.run_pending()

