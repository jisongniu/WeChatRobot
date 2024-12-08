# WeChatRobot - 智能微信机器人

## 项目简介

WeChatRobot 是一个基于 wcferry 的智能微信机器人框架,支持多种AI对话模型,具备群管理、消息转发、新闻推送等功能。

## 主要功能

### 1. AI对话能力
支持多种AI模型对接:
- ChatGPT
- 智谱AI
- TigerBot
- ChatGLM
- 讯飞星火
- Bard Assistant

### 2. 群聊管理
- 自动处理好友请求
- 新好友欢迎语
- 群聊@回复
- 成语查询与接龙
- 定时新闻推送

### 3. 消息转发系统
- 支持多种消息类型转发(文字、图片、公众号文章、视频等)
- 基于 Notion 的群组管理
- 批量转发功能
- 延迟发送机制

## 项目结构

```
WeChatRobot/
├── base/                   # 基础功能模块
│   ├── func_chatgpt.py    # ChatGPT 接口
│   ├── func_zhipu.py      # 智谱AI 接口
│   ├── func_tigerbot.py   # TigerBot 接口
│   ├── func_news.py       # 新闻服务
│   ├── func_chengyu.py    # 成语功能
│   └── notion_manager.py  # Notion管理器
├── robot.py               # 机器人核心类
├── job_mgmt.py           # 任务管理
├── configuration.py       # 配置管理
├── constants.py          # 常量定义
├── main.py               # 程序入口
└── config.yaml.template  # 配置模板
```

## 配置说明

在使用前需要复制 `config.yaml.template` 为 `config.yaml` 并完成配置:

```yaml
# AI模型配置
CHATGPT:
  API_KEY: "your-api-key"
  PROXY: "http://127.0.0.1:7890"  # 可选

TIGERBOT:
  API_KEY: "your-api-key"

# Notion配置
NOTION:
  TOKEN: "your-notion-token"
  LISTS_DB_ID: "your-database-id"
  GROUPS_DB_ID: "your-database-id"

# 群组配置
GROUPS:
  - "group1-id"
  - "group2-id"

# 其他配置...
```

## 使用方法

1. 安装依赖:
```bash
pip install -r requirements.txt
```

2. 配置 config.yaml

3. 运行机器人:
```bash
python main.py
```

## 高级功能

### 1. 好友管理
- 自动延迟接受好友请求
- 可配置欢迎语
- 支持自定义好友验证规则

### 2. AI对话
- 支持多种AI模型
- 可配置对话上下文
- 支持群聊@回复
- 私聊直接对话

### 3. 群组管理
- 基于Notion的群组管理系统
- 支持群组分类和批量操作
- 灵活的消息转发机制

## 注意事项

1. 请合理配置机器人,避免触发微信的安全机制
2. 转发消息时建议添加随机延迟
3. 妥善保管各平台的API密钥
4. 定期备份配置文件

## 转发功能概述

本功能允许管理员将各类消息(文字、图片、公众号文章、视频号视频等)批量转发到预设的群组列表中。

## 使用流程

1. **进入转发模式**
   - 发送 "转发" 命令给机器人
   - 机器人会回复以下选项:
     ```
     已进入转发模式。
     如果希望刷新群聊列表，回复刷新列表。
     如果希望删除缓存，回复删除缓存。
     🌟如果想直接转发，回复1。
     ```

2. **发送待转发内容**
   - 回复 "1" 后开始收集需要转发的内容
   - 支持的消息类型:
     - 文字消息
     - 图片
     - 公众号推文
     - 视频号视频
   - 可以连续发送多条消息
   - 发送完成后回复 "选择群聊"

3. **选择目标群组**
   - 机器人会显示可用的群组列表
   - 每个列表包含 ID、名称和描述
   - 输入对应的列表 ID 进行转发

4. **其他功能**
   - 回复 "刷新列表" 可更新群组列表
   - 回复 "删除缓存" 可清除缓存数据
   
### 注意事项
1. 仅管理员可使用此功能
2. 转发过程中如遇错误会记录到日志
3. 建议合理控制单次转发的消息数量
4. 确保机器人在目标群组中有发言权限