#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil

import yaml


class Config(object):
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """加载配置"""
        # 获取当前文件所在目录
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

        if not os.path.exists(self.config_path):
            # 如果配置文件不存在，从模板复制一份
            shutil.copy(f"{self.config_path}.template", self.config_path)

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # 加载各个配置项
        self._load_chatgpt()
        self._load_tigerbot()
        self._load_chatglm()
        self._load_xinghuo()
        self._load_fastgpt()
        self._load_groups()
        self._load_news()
        self._load_feishu_bot()  # 添加飞书机器人配置加载

    def _load_feishu_bot(self):
        """加载飞书机器人配置"""
        self.FEISHU_BOT = {}
        if "feishu_bot" in self.config:
            self.FEISHU_BOT = {
                "webhook": self.config["feishu_bot"].get("webhook", ""),
                "enable_notify": self.config["feishu_bot"].get("enable_notify", True),
                "exclude_keywords": self.config["feishu_bot"].get("exclude_keywords", [])
            }

    def _load_chatgpt(self):
        """加载chatgpt配置"""
        self.CHATGPT = self.config.get("chatgpt", {})

    def _load_tigerbot(self):
        """加载tigerbot配置"""
        self.TIGERBOT = self.config.get("tigerbot", {})

    def _load_chatglm(self):
        """加载chatglm配置"""
        self.CHATGLM = self.config.get("chatglm", {})

    def _load_xinghuo(self):
        """加载xinghuo配置"""
        self.XINGHUO_WEB = self.config.get("xinghuo_web", {})

    def _load_fastgpt(self):
        """加载fastgpt配置"""
        self.FASTGPT = self.config.get("fastgpt", {})

    def _load_groups(self):
        """加载groups配置"""
        self.NOTION = {
            "TOKEN": self.config["NOTION"]["TOKEN"],
            "LISTS_DB_ID": self.config["NOTION"]["LISTS_DB_ID"],
            "GROUPS_DB_ID": self.config["NOTION"]["GROUPS_DB_ID"],
            "ADMINS_DB_ID": self.config["NOTION"]["ADMINS_DB_ID"]
        }

    def _load_news(self):
        """加载news配置"""
        self.NEWS = self.config["news"]["receivers"]

    def _load_report_reminder(self):
        """加载report_reminder配置"""
        self.REPORT_REMINDER = self.config["report_reminder"]["receivers"]

    def _load_bard(self):
        """加载bard配置"""
        self.BardAssistant = self.config.get("bard", {})

    def _load_zhipu(self):
        """加载zhipu配置"""
        self.ZhiPu = self.config.get("zhipu", {})

# 添加别名兼容旧代码
Configuration = Config
