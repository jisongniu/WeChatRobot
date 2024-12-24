#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil

import yaml


class Config(object):
    def __init__(self) -> None:
        self.reload()

    def _load_config(self) -> dict:
        pwd = os.path.dirname(os.path.abspath(__file__))
        try:
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)
        except FileNotFoundError:
            shutil.copyfile(f"{pwd}/config.yaml.template", f"{pwd}/config.yaml")
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)

        return yconfig

    def reload(self) -> None:
        yconfig = self._load_config()
        logging.config.dictConfig(yconfig["logging"])
        self.NOTION = {
            "token": yconfig["NOTION"]["token"],
            "lists_db_id": yconfig["NOTION"]["lists_db_id"],
            "groups_db_id": yconfig["NOTION"]["groups_db_id"],
            "admins_db_id": yconfig["NOTION"]["admins_db_id"]
        }
        self.NEWS = yconfig["news"]["receivers"]
        self.REPORT_REMINDER = yconfig["report_reminder"]["receivers"]
        self.CHATGPT = yconfig.get("chatgpt", {})
        self.TIGERBOT = yconfig.get("tigerbot", {})
        self.XINGHUO_WEB = yconfig.get("xinghuo_web", {})
        self.CHATGLM = yconfig.get("chatglm", {})
        self.BardAssistant = yconfig.get("bard", {})
        self.ZhiPu = yconfig.get("zhipu", {})
        self.FASTGPT = yconfig.get("fastgpt", {})

# 添加别名兼容旧代码
Configuration = Config
