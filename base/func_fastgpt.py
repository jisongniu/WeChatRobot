#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import datetime
import httpx
from typing import Dict, List, Optional
import json

class FastGPT:
    def __init__(self, conf: dict) -> None:
        self.api_key = conf.get("key")  # 格式应该是 fastgpt-xxx
        self.api_url = conf.get("api", "http://localhost:3000/api/v1/chat/completions")  # 默认本地地址
        self.proxy = conf.get("proxy")
        self.prompt = conf.get("prompt")
        self.LOG = logging.getLogger("FastGPT")
        
        # 初始化HTTP客户端，设置较长的超时时间（5分钟）
        self.timeout = httpx.Timeout(300.0, connect=60.0)  # 总超时300秒，连接超时60秒
        transport = httpx.HTTPTransport(retries=0)  # 禁用自动重试
        if self.proxy:
            self.client = httpx.Client(proxies=self.proxy, timeout=self.timeout, transport=transport)
        else:
            self.client = httpx.Client(timeout=self.timeout, transport=transport)
            
        self.conversation_list = {}
        self.system_content_msg = {"role": "system", "content": self.prompt} if self.prompt else None

    def __repr__(self):
        return 'FastGPT'

    @staticmethod
    def value_check(conf: dict) -> bool:
        if conf:
            if conf.get("key") and conf.get("api"):
                return True
        return False

    def get_answer(self, question: str, wxid: str) -> str:
        """获取回答
        Args:
            question: 问题内容
            wxid: wxid或者roomid,个人时为微信id，群消息时为群id
        """
        self.updateMessage(wxid, question, "user")
        rsp = ""
        
        try:
            # 只使用必要的请求头，完全匹配curl
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # 准备消息列表，只发送当前消息
            payload = {
                "chatId": wxid,
                "stream": False,
                "detail": False,
                "messages": [
                    {
                        "content": question,
                        "role": "user"
                    }
                ]
            }
            
            # 记录请求信息
            self.LOG.info(f"正在发送请求到 FastGPT API: {self.api_url}")
            self.LOG.debug(f"请求负载: {json.dumps(payload, ensure_ascii=False)}")
            
            # 使用data参数模拟curl的--data-raw
            response = self.client.post(
                self.api_url,
                headers=headers,
                data=json.dumps(payload),  # 使用data参数，对应curl的--data-raw
                follow_redirects=True  # 对应curl的--location
            )
            
            self.LOG.debug(f"API响应: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get("choices") and len(result["choices"]) > 0:
                    rsp = result["choices"][0]["message"]["content"]
                    rsp = rsp[2:] if rsp.startswith("\n\n") else rsp
                    rsp = rsp.replace("\n\n", "\n")
                    self.updateMessage(wxid, rsp, "assistant")
            else:
                self.LOG.error(f"FastGPT API返回错误状态码: {response.status_code}")
                self.LOG.error(f"错误响应: {response.text}")
                
        except httpx.ConnectTimeout:
            self.LOG.error("连接FastGPT API超时，请检查服务是否启动")
        except httpx.ReadTimeout:
            self.LOG.error("读取FastGPT API响应超时，这可能是因为模型处理时间较长")
        except httpx.RequestError as e:
            self.LOG.error(f"请求FastGPT API时发生错误：{str(e)}")
        except Exception as e:
            self.LOG.error(f"发生未知错误：{str(e)}")

        return rsp

    def updateMessage(self, wxid: str, question: str, role: str) -> None:
        """更新对话历史
        Args:
            wxid: wxid或者roomid,个人时为微信id，群消息时为群id
            question: 问题或回答内容
            role: 角色，user或assistant
        """
        now_time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        time_mk = "当需要回答时间时请直接参考回复:"

        # 初始化聊天记录
        if wxid not in self.conversation_list:
            self.conversation_list[wxid] = []
            if self.system_content_msg:
                self.conversation_list[wxid].append(self.system_content_msg)
            self.conversation_list[wxid].append(
                {"role": "system", "content": time_mk + now_time}
            )

        # 添加当前消息
        self.conversation_list[wxid].append({
            "role": role,
            "content": question
        })

        # 更新时间
        for cont in self.conversation_list[wxid]:
            if cont["role"] == "system" and cont["content"].startswith(time_mk):
                cont["content"] = time_mk + now_time

        # 保持最近10条记录
        if len(self.conversation_list[wxid]) > 10:
            self.LOG.info(f"滚动清除微信记录：{wxid}")
            # 删除多余的记录，倒着删，且跳过第一个的系统消息
            del self.conversation_list[wxid][1]

if __name__ == "__main__":
    from configuration import Config
    config = Config().FASTGPT
    if not config:
        exit(0)

    chat = FastGPT(config)

    while True:
        q = input(">>> ")
        try:
            time_start = datetime.now()
            print(chat.get_answer(q, "wxid"))
            time_end = datetime.now()
            print(f"{round((time_end - time_start).total_seconds(), 2)}s")
        except Exception as e:
            print(e) 