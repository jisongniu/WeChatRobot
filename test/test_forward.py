#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
from wcferry import Wcf, WxMsg
from queue import Empty

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 确保图片保存目录存在
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "temp_images")
if not os.path.exists(IMAGES_DIR):
    os.makedirs(IMAGES_DIR)
    logger.info(f"创建图片目录: {IMAGES_DIR}")

def on_message(msg: WxMsg):
    if msg.type == 3:  # 图片消息
        logger.info("=" * 50)
        logger.info("检测到图片消息")
        logger.info(f"消息ID: {msg.id}")
        
        try:
            # 下载图片
            logger.info(f"尝试下载图片到目录: {IMAGES_DIR}")
            img_path = wcf.download_image(msg.id, msg.extra, IMAGES_DIR, timeout=60)
            
            if img_path and os.path.exists(img_path):
                logger.info(f"图片下载成功: {img_path}")
                logger.info(f"文件大小: {os.path.getsize(img_path)} 字节")
                
                # 测试发送
                receiver = "filehelper"
                logger.info(f"测试发送到 {receiver}")
                
                # 方式1 - send_image
                logger.info("方式1 - send_image:")
                result1 = wcf.send_image(img_path, receiver)
                logger.info(f"结果1: {'成功' if result1 == 0 else '失败'}")
                
                # 方式2 - forward_msg
                logger.info("方式2 - forward_msg:")
                result2 = wcf.forward_msg(msg.id, receiver)
                logger.info(f"结果2: {'成功' if result2 == 1 else '失败'}")
            else:
                logger.error(f"图片下载失败，返回路径: {img_path}")
                
        except Exception as e:
            logger.error(f"处理图片消息失败: {e}", exc_info=True)
        
        logger.info("=" * 50)

def main():
    logger.info(f"当前工作目录: {os.getcwd()}")
    logger.info("等待微信登录...")
    wcf.enable_receiving_msg()
    logger.info("开始监听消息...")
    logger.info("请发送图片消息进行测试")
    logger.info("按 Ctrl+C 退出")
    
    while True:
        try:
            msg = wcf.get_msg()
            if msg:
                on_message(msg)
        except Empty:
            continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"处理消息出错: {e}", exc_info=True)
            continue

if __name__ == "__main__":
    wcf = Wcf(debug=True)
    main()