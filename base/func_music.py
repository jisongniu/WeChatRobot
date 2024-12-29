import requests
import re
import lz4.block as lb
from typing import Optional, Dict, Any
from loguru import logger

class MusicService:
    """音乐服务类，用于处理点歌功能"""
    
    def __init__(self, wcf):
        self.wcf = wcf
        # 主API和备用API
        self.primary_api = "https://qqmusic.qqovo.cn/getSearchByKey"
        self.fallback_api = "https://www.hhlqilongzhu.cn/api/dg_wyymusic.php"

    def search_song(self, song_name: str) -> Dict[str, Any]:
        """
        搜索歌曲信息
        Args:
            song_name: 歌曲名称
        Returns:
            包含歌曲信息的字典
        """
        try:
            # 尝试主API
            params = {
                "key": song_name,
                "page": 1,
                "limit": 1
            }
            logger.info(f"正在请求主API，参数：{params}")
            response = requests.get(self.primary_api, params=params)
            logger.info(f"主API响应状态码：{response.status_code}")
            
            # 如果主API失败，使用备用API
            if response.status_code == 400:
                logger.info("主API请求失败，使用备用API")
                fallback_params = {
                    "gm": song_name,
                    "n": 1,
                    "num": 1,
                    "type": "json"
                }
                logger.info(f"正在请求备用API，参数：{fallback_params}")
                response = requests.get(self.fallback_api, params=fallback_params)
                logger.info(f"备用API响应状态码：{response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"API返回数据：{data}")
                return data
            else:
                logger.error(f"API请求失败，状态码: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"搜索歌曲时发生错误：{e}")
            return None

    def get_play_url(self, song_mid: str, song_name: str) -> Dict[str, Any]:
        """
        获取歌曲播放链接
        """
        try:
            # 尝试主API
            music_play_api = f"https://qqmusic.qqovo.cn/getMusicPlay?songmid={song_mid}&quality=m4a"
            logger.info(f"正在请求音乐播放链接：{music_play_api}")
            response = requests.get(music_play_api)
            logger.info(f"播放链接API响应状态码：{response.status_code}")
            
            use_fallback = False
            if response.status_code == 200:
                data = response.json()
                logger.info(f"播放链接API返回数据：{data}")
                # 检查是否真的获取到了播放链接
                play_url = data.get('data', {}).get('playUrl', {}).get(song_mid, {}).get('url')
                if not play_url:
                    logger.info("主API未返回有效播放链接，切换到备用API")
                    use_fallback = True
            else:
                use_fallback = True
            
            # 如果主API失败或没有返回有效链接，使用备用API
            if use_fallback:
                logger.info("使用备用接口获取播放链接")
                fallback_params = {
                    "gm": song_name,
                    "n": 1,
                    "num": 1,
                    "type": "json"
                }
                logger.info(f"正在请求备用播放链接API，参数：{fallback_params}")
                response = requests.get(self.fallback_api, params=fallback_params)
                logger.info(f"备用播放链接API响应状态码：{response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"备用API返回数据：{data}")
                    # 验证备用API返回的播放链接
                    if data.get('music_url'):
                        return data
            
            if not use_fallback:
                return data
                
            logger.error("所有API都未能获取到有效的播放链接")
            return None
            
        except Exception as e:
            logger.error(f"获取播放链接时发生错误：{e}")
            return None

    def generate_xml_message(self, song_name: str, singer_name: str, data_url: str, play_url: str, singer_pic: str) -> str:
        """生成音乐XML消息"""
        return f"""<?xml version="1.0"?>
<msg>
        <appmsg appid="wx8dd6ecd81906fd84" sdkver="0">
                <title>{song_name}</title>
                <des>{singer_name}\n❤Bot-祝您天天开心❤</des>
                <action>view</action>
                <type>3</type>
                <showtype>0</showtype>
                <content />
                <url>{data_url}</url>
                <dataurl>{play_url}</dataurl>
                <lowurl/>
                <lowdataurl/>
                <recorditem />
                <thumburl />
                <messageaction />
                <laninfo />
                <extinfo />
                <sourceusername />
                <sourcedisplayname />
                <commenturl />
                <appattach>
                        <totallen>0</totallen>
                        <attachid />
                        <emoticonmd5></emoticonmd5>
                        <fileext />
                        <aeskey></aeskey>
                </appattach>
                <webviewshared>
                        <publisherId />
                        <publisherReqId>0</publisherReqId>
                </webviewshared>
                <weappinfo>
                        <pagepath />
                        <username />
                        <appid />
                        <appservicetype>0</appservicetype>
                </weappinfo>
                <websearch />
                <songalbumurl>{singer_pic}</songalbumurl>
        </appmsg>
        <scene>0</scene>
        <appinfo>
                <version>49</version>
                <appname>网易云音乐</appname>
        </appinfo>
        <commenturl />
</msg>"""

    def process_music_command(self, content: str, room_id: str) -> bool:
        """
        处理点歌命令
        Args:
            content: 消息内容
            room_id: 房间ID
        Returns:
            处理是否成功
        """
        try:
            if '点歌' in content:
                match = re.search(r'点歌\s*(.*)', content)
                if not match:
                    logger.error("无法提取歌曲名称")
                    return False
                    
                song_name = match.group(1).strip()
                if not song_name:
                    return False

                logger.info(f"开始搜索歌曲：{song_name}")
                # 搜索歌曲
                json_data = self.search_song(song_name)
                if not json_data:
                    logger.error("未获取到歌曲搜索结果")
                    return False

                logger.info(f"搜索结果：{json_data}")

                # 处理API返回数据
                if 'response' in json_data:  # 主API返回格式
                    result = json_data.get('response', {}).get('data', {}).get('song', {}).get('list', [])
                    if not result:
                        logger.error("主API未返回歌曲列表")
                        return False

                    song = result[0]
                    song_name = song.get('songname')
                    song_mid = song.get('songmid')
                    singer_name = song.get('singer', [{}])[0].get('name', '')
                    
                    logger.info(f"找到歌曲：{song_name} - {singer_name}")
                    
                    # 获取歌手图片
                    zhida_singer = json_data.get('response', {}).get('data', {}).get('zhida', {}).get('zhida_singer', {})
                    singer_pic = zhida_singer.get('singerPic') if zhida_singer else None
                    
                    # 获取播放链接
                    logger.info("开始获取播放链接")
                    music_data = self.get_play_url(song_mid, song_name)
                    if not music_data:
                        logger.error("未获取到播放链接数据")
                        return False

                    if 'data' in music_data:  # 主API播放链接格式
                        play_url = music_data.get('data', {}).get('playUrl', {}).get(song_mid, {}).get('url')
                        if not play_url:  # 如果主API没有返回播放链接，尝试使用备用API的数据
                            play_url = music_data.get('music_url')
                            data_url = music_data.get('link')
                            singer_pic = music_data.get('cover')
                            song_name = music_data.get('title')
                            singer_name = music_data.get('singer')
                        else:
                            data_url = f"https://y.qq.com/n/ryqq/songDetail/{song_mid}"
                    else:  # 备用API格式
                        play_url = music_data.get('music_url')
                        data_url = music_data.get('link')
                        singer_pic = music_data.get('cover')
                        song_name = music_data.get('title')
                        singer_name = music_data.get('singer')

                else:  # 备用API返回格式
                    play_url = json_data.get('music_url')
                    data_url = json_data.get('link')
                    singer_pic = json_data.get('cover')
                    song_name = json_data.get('title')
                    singer_name = json_data.get('singer')

                if not play_url:
                    logger.error("未获取到音乐播放链接")
                    return False

                logger.info(f"成功获取播放链接：{play_url}")

                # 生成XML消息
                xml_message = self.generate_xml_message(
                    song_name, singer_name, data_url, play_url, singer_pic or ""
                )

                # 压缩XML消息
                text_bytes = xml_message.encode('utf-8')
                compressed_data = lb.compress(text_bytes, store_size=False)
                compressed_data_hex = compressed_data.hex()

                # 更新数据库并转发消息
                data = self.wcf.query_sql('MSG0.db', "SELECT * FROM MSG where type = 49 limit 1")
                if not data:
                    logger.error("未找到合适的消息模板")
                    return False

                self.wcf.query_sql(
                    'MSG0.db',
                    f"UPDATE MSG SET CompressContent = x'{compressed_data_hex}', BytesExtra=x'',type=49,SubType=3,IsSender=0,TalkerId=2 WHERE MsgSvrID={data[0]['MsgSvrID']}"
                )
                
                result = self.wcf.forward_msg(data[0]["MsgSvrID"], room_id)
                logger.info(f"点歌发送结果: {result}")
                # 发送飞书通知，点歌成功
                if self.feishu_bot:
                    self.feishu_bot.notify("点歌成功", room_id, song_name, room_id, False)
                return True

            return False

        except Exception as e:
            logger.error(f"处理点歌命令时发生错误：{e}")
            return False 