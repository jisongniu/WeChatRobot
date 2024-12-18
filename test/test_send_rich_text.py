from wcferry import Wcf
import logging
import time
import os
import requests
from urllib.parse import urlparse
import hashlib

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def download_thumbnail(url: str, save_dir: str = "temp") -> str:
    """下载缩略图并返回本地路径"""
    try:
        # 创建临时目录
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        # 生成文件名
        file_name = hashlib.md5(url.encode()).hexdigest()[:10] + ".jpg"
        file_path = os.path.join(save_dir, file_name)
        
        # 如果文件已存在，直接返回
        if os.path.exists(file_path):
            logger.debug(f"使用缓存的缩略图: {file_path}")
            return file_path
            
        # 下载图片
        logger.debug(f"开始下载缩略图: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 保存图片
        with open(file_path, "wb") as f:
            f.write(response.content)
            
        logger.debug(f"缩略图下载成功: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"下载缩略图失败: {e}")
        return None

def test_send_rich_text(wcf: Wcf):
    """测试发送富文本消息"""
    try:
        # 检查微信登录状态
        if not wcf.is_login():
            logger.error("微信未登录，请先登录微信")
            return False
            
        logger.info(f"当前登录的微信ID: {wcf.get_self_wxid()}")
        
        # 发送富文本消息
        logger.info("开始发送富文本消息...")
        
        result = wcf.send_rich_text(
            name="NCC社区",
            account="gh_0b00895e7394",
            title="点开看看？",
            digest="选择你所热爱的，热爱你所选择的",
            url="https://mp.weixin.qq.com/s/QAM-70Nn4TP8mgsoyyK32g",
            thumburl="",  # 不使用缩略图
            receiver="filehelper"
        )
        
        # 处理结果
        if isinstance(result, str):
            logger.error(f"发送失败，错误信息: {result}")
            return False
            
        if result is None:
            logger.error("发送失败：返回结果为空")
            return False
            
        if isinstance(result, int):
            if result == 0:
                logger.info("消息发送成功")
                return True
            logger.error(f"消息发送失败，错误代码: {result}")
            return False
            
        logger.error(f"未知的返回结果类型: {type(result)}, 值: {result}")
        return False
            
    except Exception as e:
        logger.error(f"发送消息时发生错误: {e}")
        return False

def verify_wechat_status(wcf: Wcf) -> bool:
    """验证微信状态"""
    try:
        # 检查进程
        if not wcf.is_login():
            logger.error("微信未登录")
            return False
            
        # 测试基本功能
        test_msg = "测试消息"
        if wcf.send_text(test_msg, "filehelper") != 0:
            logger.error("基本消息发送测试失败")
            return False
            
        return True
    except Exception as e:
        logger.error(f"状态验证失败: {e}")
        return False

def main():
    """主函数"""
    wcf = None
    try:
        # 创建 Wcf 实例
        wcf = Wcf(debug=True)
        logger.info("WCF实例创建成功")
        
        # 等待微信启动和注入完成
        logger.info("等待微信启动和注入完成...")
        time.sleep(5)
        
        if not wcf.is_login():
            logger.error("微信未登录或注入未完成")
            return
            
        # 运行测试
        if test_send_rich_text(wcf):
            logger.info("测试成功完成!")
        else:
            logger.error("测试失败")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
    finally:
        if wcf:
            wcf.cleanup()
        logger.info("测试程序结束")

if __name__ == "__main__":
    main()