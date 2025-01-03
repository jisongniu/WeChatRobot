#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import signal
from argparse import ArgumentParser

from configuration import Config
from constants import ChatType
from robot import Robot, __version__
from wcferry import Wcf
from job_mgmt import JobManager

def main(chat_type: int):
    """主函数"""
    config = Config()
    wcf = Wcf(debug=False)

    def handler(sig, frame):
        wcf.cleanup()  # 退出前清理环境
        exit(0)

    signal.signal(signal.SIGINT, handler)

    robot = Robot(config, wcf, chat_type)
   
    # 添加AI模型提示
    if robot.chat:
        robot.LOG.info(f"当前使用的AI模型是：{robot.chat.__repr__()}")
    else:
        robot.LOG.warning("当前未配置任何AI模型")

    # 机器人启动发送测试消息
    robot.sendTextMsg("启动成功！", "filehelper")

    # 接收消息
    # robot.enableRecvMsg()     # 可能会丢消息？
    robot.enableReceivingMsg()  # 加队列

    # 让机器人一直跑
    robot.keepRunningAndBlockProcess()

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('-c', type=int, default=7, help=f'选择模型参数序号: {ChatType.help_hint()}') #默认使用7号模型，FastGPT
    args = parser.parse_args()
    main(args.c)
