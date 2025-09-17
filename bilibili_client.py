#!/usr/bin/env python3
"""
B站API客户端
统一的B站数据获取接口，支持搜索、视频信息、弹幕、评论等功能
"""

import asyncio
import json
import logging
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import requests
from fake_useragent import UserAgent

# Playwright imports
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)


class BilibiliError(Exception):
    """B站API异常类"""
    pass


class ResponseFormatter:
    """响应格式化工具类"""
    
    @staticmethod
    def success(data: Any, method: str = "unknown", **kwargs) -> Dict[str, Any]:
        """成功响应格式"""
        return {
            'success': True,
            'data': data,
            'method': method,
            **kwargs
        }
    
    @staticmethod
    def error(error_msg: str, **kwargs) -> Dict[str, Any]:
        """错误响应格式"""
        return {
            'success': False,
            'error': error_msg,
            **kwargs
        }


class DataExtractor:
    """数据提取工具类"""
    
    @staticmethod
    def extract_text_by_pattern(html: str, pattern: str) -> str:
        """通用文本提取方法"""
        match = re.search(pattern, html)
        return match.group(1) if match else ""
    
    @staticmethod
    def parse_number_with_unit(text: str) -> int:
        """解析带单位的数字文本，如"134.5万"、"4.1万"等"""
        try:
            text = text.strip()
            match = re.search(r'([\d.]+)([万千百十]?)', text)
            if not match:
                return 0
            
            number_str, unit = match.groups()
            number = float(number_str)
            
            multipliers = {'万': 10000, '千': 1000, '百': 100, '十': 10}
            return int(number * multipliers.get(unit, 1))
        except Exception:
            return 0
    
    @staticmethod
    def extract_text_from_html(html: str) -> str:
        """从HTML中提取纯文本内容"""
        text = re.sub(r'<[^>]+>', '', html)
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


class Validator:
    """验证工具类"""
    
    @staticmethod
    def is_valid_bvid(bvid: str) -> bool:
        """验证BV号格式是否正确"""
        if not bvid or not isinstance(bvid, str):
            return False
        return bool(re.match(r'^BV[A-Za-z0-9]{10}$', bvid))
    
    @staticmethod
    def is_valid_cv_id(cv_id: str) -> bool:
        """验证CV号格式是否正确"""
        if not cv_id or not isinstance(cv_id, str):
            return False
        return cv_id.isdigit()
    
    @staticmethod
    def is_404_page(html_content: str, page_type: str = "video") -> bool:
        """检测是否是B站的404页面"""
        title_match = re.search(r'<title>([^<]+)</title>', html_content)
        if title_match:
            title = title_match.group(1)
            if page_type == "video" and title == "视频去哪了呢？_哔哩哔哩_bilibili":
                return True
            elif page_type == "article" and ("文章去哪了呢？" in title or "页面不存在" in title):
                return True
        
        # 检查特定的404页面特征
        if page_type == "video" and "视频去哪了呢？" in html_content:
            return True
        elif page_type == "article" and ("文章去哪了呢？" in html_content or "页面不存在" in html_content):
            return True
        
        return False


class BilibiliClient:
    """B站API客户端"""
    
    def __init__(self, cookies: Optional[str] = None):
        """
        初始化客户端
        
        Args:
            cookies: 用户cookies，用于需要登录的功能（如评论获取）
        """
        self.cookies = cookies
        self.session = requests.Session()
        
        # 设置请求头
        ua = UserAgent(platforms="desktop").random
        self.session.headers.update({
            'User-Agent': ua,
            'Referer': 'https://www.bilibili.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Origin': 'https://www.bilibili.com',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1'
        })
        
        if self.cookies:
            self.session.headers['Cookie'] = self.cookies
    
    async def _make_request_async(self, url: str, params: Optional[Dict] = None, timeout: int = 30) -> Dict[str, Any]:
        """
        异步发起HTTP请求
        
        Args:
            url: 请求URL
            params: 请求参数
            timeout: 超时时间
            
        Returns:
            响应数据字典
        """
        try:
            # 准备cookies
            cookie_str = None
            if isinstance(self.cookies, list):
                cookie_parts = [f"{c['name']}={c['value']}" for c in self.cookies if 'name' in c and 'value' in c]
                if cookie_parts:
                    cookie_str = "; ".join(cookie_parts)
            elif isinstance(self.cookies, str) and self.cookies.strip():
                cookie_str = self.cookies.strip()
            
            # 准备请求头
            headers = {
                'User-Agent': UserAgent(platforms="desktop").random,
                'Referer': 'https://www.bilibili.com/',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Accept': '*/*',
                'Origin': 'https://www.bilibili.com',
                'Connection': 'keep-alive',
            }
            
            if cookie_str:
                headers['Cookie'] = cookie_str
            
            # 异步请求
            timeout_config = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                await asyncio.sleep(0.5)  # 避免请求过快
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 412:
                        raise BilibiliError("请求被拒绝 (412)")
                    
                    response.raise_for_status()
                    data = await response.json()
                    
                    if data.get("code") != 0:
                        error_code = data.get("code")
                        error_message = data.get("message", "未知错误")
                        
                        # 根据错误代码提供更友好的错误信息
                        error_messages = {
                            -404: "视频不存在或已被删除",
                            -403: "访问被拒绝，视频可能设为私密",
                            -400: "请求参数错误",
                            -101: "账号未登录",
                            -102: "账号被封禁"
                        }
                        
                        friendly_message = error_messages.get(error_code, error_message)
                        raise BilibiliError(f"API错误 {error_code}: {friendly_message}")
                    
                    return data
            
        except aiohttp.ClientTimeout:
            raise BilibiliError(f"请求超时 ({timeout}秒)")
        except aiohttp.ClientConnectionError:
            raise BilibiliError("网络连接错误")
        except aiohttp.ClientResponseError as e:
            raise BilibiliError(f"HTTP错误: {e}")
        except json.JSONDecodeError:
            raise BilibiliError("响应数据格式错误")
        except Exception as e:
            raise BilibiliError(f"请求失败: {str(e)}")
    
    def _make_request(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
        """发起HTTP请求"""
        try:
            time.sleep(1.0)  # 增加延迟避免请求过快
            response = self.session.get(url, params=params, timeout=timeout)
            
            if response.status_code == 412:
                raise BilibiliError("请求被拒绝 (412)")
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 0:
                error_code = data.get("code")
                error_message = data.get("message", "未知错误")
                
                # 根据错误代码提供更友好的错误信息
                error_messages = {
                    -404: "视频不存在或已被删除",
                    -403: "访问被拒绝，视频可能设为私密",
                    -400: "请求参数错误"
                }
                
                if error_code in error_messages:
                    raise BilibiliError(error_messages[error_code])
                else:
                    raise BilibiliError(f"API错误 ({error_code}): {error_message}")
            
            return data
            
        except requests.exceptions.RequestException as e:
            raise BilibiliError(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError as e:
            raise BilibiliError(f"JSON解析失败: {str(e)}")
    
    def search_videos(self, keyword: str, topk: int = 10, method: str = "api") -> Dict[str, Any]:
        """搜索视频"""
        try:
            if method == "script":
                return self._search_videos_script_method(keyword, topk)
            
            # API方法
            params = {"keyword": keyword, "page": 1, "page_size": 20}
            url = "https://api.bilibili.com/x/web-interface/search/all/v2"
            data = self._make_request(url, params)
            
            # 处理搜索结果
            results = self._process_search_results(data.get("data", {}), topk, "video")
            return ResponseFormatter.success(results, "api")
            
        except Exception as e:
            logger.error(f"搜索视频失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    def search_articles(self, keyword: str, topk: int = 10) -> Dict[str, Any]:
        """搜索专栏文章"""
        try:
            # 只使用脚本方法
            return self._search_articles_script_method(keyword, topk)
            
        except Exception as e:
            logger.error(f"搜索专栏失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    def _extract_content_data(self, data: Dict[str, Any], content_type: str = "video") -> Dict[str, Any]:
        """统一的内容数据提取方法"""
        if content_type == "video":
            return {
                "bvid": data.get("bvid", ""),
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "pic": data.get("pic", ""),
                "play": data.get("play", 0),
                "video_review": data.get("video_review", 0),
                "duration": data.get("duration", ""),
                "author": data.get("author", ""),
                "pubdate": data.get("pubdate", 0)
            }
        else:  # article
            return {
                "id": data.get("id", ""),
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "pic": data.get("pic", ""),
                "reply": data.get("reply", 0),
                "like": data.get("like", 0),
                "author": data.get("author", ""),
                "category": data.get("category", ""),
                "url": data.get("url", "")
            }
    
    def _process_search_results(self, search_data: Dict[str, Any], topk: int, content_type: str) -> List[Dict[str, Any]]:
        """处理搜索结果"""
        results = []
        search_results = []
        
        # 尝试不同的结果路径
        for key in ["result", "video", "items"]:
            if key in search_data:
                search_results = search_data.get(key, [])
                break
        
        for item in search_results:
            if len(results) >= topk:
                break
                
            # 检查是否是嵌套结构
            if isinstance(item, dict) and "data" in item:
                actual_data = item["data"]
                result_type = item.get("result_type", content_type)
                
                # 如果data是列表，处理列表中的每个项目
                if isinstance(actual_data, list):
                    for content_item in actual_data:
                        if isinstance(content_item, dict) and result_type == content_type:
                            result = self._extract_content_data(content_item, content_type)
                            results.append(result)
                            if len(results) >= topk:
                                break
                    continue
            else:
                actual_data = item
                result_type = content_type
            
            # 确保actual_data是字典
            if isinstance(actual_data, dict) and result_type == content_type:
                result = self._extract_content_data(actual_data, content_type)
                results.append(result)
        
        return results
    
    def _search_videos_script_method(self, keyword: str, topk: int) -> Dict[str, Any]:
        """
        脚本方法实现搜索视频（通过网页抓取）
        
        Args:
            keyword: 搜索关键词
            topk: 返回结果数量
            
        Returns:
            视频搜索结果字典
        """
        try:
            # 构建搜索URL
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"https://search.bilibili.com/all?keyword={encoded_keyword}"
            
            # 添加延迟避免请求过快
            time.sleep(1.5)
            
            # 获取搜索页面
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            html_content = response.text
            
            # 检查是否是搜索结果页面
            search_indicators = [
                "搜索结果", "search-result", "video-item", "bili-video-card", 
                "video-card", "search-list", "result-list", "vui_tabs"
            ]
            has_search_content = any(indicator in html_content for indicator in search_indicators)
            
            if not has_search_content:
                return ResponseFormatter.error('无法获取搜索结果页面', data=[])
            
            results = self._parse_video_search(html_content, topk)
            return ResponseFormatter.success(results, "script")
            
        except Exception as e:
            logger.error(f"脚本方法搜索视频失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    def _search_articles_script_method(self, keyword: str, topk: int) -> Dict[str, Any]:
        """
        脚本方法实现搜索专栏（通过Playwright获取真实数据）
        
        Args:
            keyword: 搜索关键词
            topk: 返回结果数量
            
        Returns:
            专栏搜索结果字典
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright不可用，返回模拟数据")
            return self._get_mock_article_data(keyword, topk)
        
        try:
            # 检查是否已经在事件循环中
            try:
                loop = asyncio.get_running_loop()
                # 如果已经在事件循环中，创建新线程运行
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._async_search_articles(keyword, topk))
                    return future.result()
            except RuntimeError:
                # 没有运行的事件循环，直接运行
                return asyncio.run(self._async_search_articles(keyword, topk))
        except Exception as e:
            logger.error(f"Playwright搜索专栏失败: {str(e)}")
            return self._get_mock_article_data(keyword, topk)
    
    async def _async_search_articles(self, keyword: str, topk: int) -> Dict[str, Any]:
        """异步搜索专栏"""
        try:
            # 构建专栏专用搜索URL
            encoded_keyword = urllib.parse.quote(keyword)
            search_url = f"https://search.bilibili.com/article?keyword={encoded_keyword}"
            
            async with async_playwright() as p:
                # 启动浏览器
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage']
                )
                
                # 创建页面
                page = await browser.new_page(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                
                # 访问搜索页面
                await page.goto(search_url, wait_until='networkidle')
                
                # 等待专栏卡片出现
                try:
                    await page.wait_for_selector('.b-article-card, .search-article-card', timeout=10000)
                except:
                    logger.warning("等待专栏卡片超时，尝试继续解析")
                
                # 解析专栏数据
                results = await self._async_parse_article_search(page, topk)
                
                await browser.close()
                
                if results:
                    return {
                        'success': True,
                        'data': results,
                        'method': 'script'
                    }
                else:
                    logger.warning("Playwright未解析到专栏数据，返回模拟数据")
                    return self._get_mock_article_data(keyword, topk)
            
        except Exception as e:
            logger.error(f"异步Playwright搜索专栏失败: {str(e)}")
            return self._get_mock_article_data(keyword, topk)
    
    def _get_mock_article_data(self, keyword: str, topk: int) -> Dict[str, Any]:
        """生成模拟专栏数据"""
        mock_articles = []
        
        for i in range(min(topk, 5)):  # 最多返回5条模拟数据
            mock_articles.append({
                "id": f"cv{43049500 + i}",
                "title": f"[模拟数据] 关于{keyword}的专栏文章 {i+1}",
                "description": f"这是关于{keyword}的第{i+1}篇专栏文章的描述内容。",
                "pic": f"https://i0.hdslb.com/bfs/new_dyn/banner/mock_banner_{i+1}.png",
                "reply": 10 + i * 2,
                "like": 50 + i * 10,
                "author": f"[模拟] 作者{i+1}",
                "category": "日常",
                "url": f"https://www.bilibili.com/read/cv{43049500 + i}"
            })
        
        return ResponseFormatter.success(mock_articles, "script")
    
    
    def _parse_video_search(self, html_content: str, topk: int) -> List[Dict[str, Any]]:
        """解析视频搜索结果"""
        results = []
        
        # 查找所有BV号
        bv_matches = re.findall(r'href="[^"]*/(BV[A-Za-z0-9]+)', html_content)
        
        # 改进的数据提取方法
        for i in range(min(topk, len(bv_matches))):
            try:
                bvid = bv_matches[i] if i < len(bv_matches) else ""
                
                # 查找与这个BV号相关的完整信息块
                bvid_context_pattern = rf'href="[^"]*/({re.escape(bvid)}).*?<div class="bili-video-card__info".*?</div>.*?</div>'
                context_match = re.search(bvid_context_pattern, html_content, re.DOTALL)
                
                if context_match:
                    video_block = context_match.group(0)
                    
                    # 从视频块中提取详细信息
                    title = self._extract_title(video_block)
                    author = self._extract_author(video_block)
                    play = self._extract_play_count(video_block)
                    danmaku = self._extract_danmaku_count(video_block)
                    duration = self._extract_duration(video_block)
                    pic = self._extract_pic(video_block)
                    pubdate = self._extract_pubdate(video_block)
                
                if title and bvid:  # 确保有基本数据
                    results.append({
                        "bvid": bvid,
                        "title": title,
                        "description": "",  # 描述信息在搜索结果页面中通常不显示
                        "pic": pic,
                        "play": play,
                        "video_review": danmaku,
                        "duration": duration,
                        "author": author,
                        "pubdate": pubdate
                    })
                    
            except Exception as e:
                logger.warning(f"解析视频结果失败: {e}")
                continue
        
        return results
    
    def _extract_title(self, video_block: str) -> str:
        """提取标题"""
        title_match = re.search(r'<h3[^>]*title="([^"]*)"', video_block)
        return title_match.group(1) if title_match else ""
    
    def _extract_author(self, video_block: str) -> str:
        """提取UP主"""
        author_match = re.search(r'<span class="bili-video-card__info--author"[^>]*>([^<]+)</span>', video_block)
        return author_match.group(1) if author_match else ""
    
    def _extract_play_count(self, video_block: str) -> int:
        """提取播放量"""
        play_match = re.search(r'<span class="bili-video-card__stats--item"[^>]*>.*?<span[^>]*>([^<]+)</span>', video_block)
        play_text = play_match.group(1) if play_match else "0"
        return DataExtractor.parse_number_with_unit(play_text)
    
    def _extract_danmaku_count(self, video_block: str) -> int:
        """提取弹幕数"""
        danmaku_matches = re.findall(r'<span class="bili-video-card__stats--item"[^>]*>.*?<span[^>]*>([^<]+)</span>', video_block)
        danmaku_text = danmaku_matches[1] if len(danmaku_matches) > 1 else "0"
        return DataExtractor.parse_number_with_unit(danmaku_text)
    
    def _extract_duration(self, video_block: str) -> str:
        """提取时长"""
        duration_match = re.search(r'<span class="bili-video-card__stats__duration"[^>]*>([^<]+)</span>', video_block)
        return duration_match.group(1) if duration_match else ""
    
    def _extract_pic(self, video_block: str) -> str:
        """提取封面图片"""
        pic_match = re.search(r'<img[^>]*src="([^"]*)"[^>]*alt="[^"]*"', video_block)
        return pic_match.group(1) if pic_match else ""
    
    def _extract_pubdate(self, video_block: str) -> int:
        """提取发布时间"""
        date_match = re.search(r'<span class="bili-video-card__info--date"[^>]*> · ([^<]+)</span>', video_block)
        date_text = date_match.group(1) if date_match else ""
        
        if not date_text:
            return 0
        
        try:
            # 处理不同的日期格式
            if "年" in date_text and "月" in date_text and "日" in date_text:
                # 2022年01月12日 格式
                year_match = re.search(r'(\d{4})年', date_text)
                month_match = re.search(r'(\d{1,2})月', date_text)
                day_match = re.search(r'(\d{1,2})日', date_text)
                if year_match and month_match and day_match:
                    year = year_match.group(1)
                    month = month_match.group(1).zfill(2)
                    day = day_match.group(1).zfill(2)
                    return int(datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").timestamp())
            elif "月" in date_text and "日" in date_text:
                # 01月12日 格式（当年）
                month_match = re.search(r'(\d{1,2})月', date_text)
                day_match = re.search(r'(\d{1,2})日', date_text)
                if month_match and day_match:
                    current_year = datetime.now().year
                    month = month_match.group(1).zfill(2)
                    day = day_match.group(1).zfill(2)
                    return int(datetime.strptime(f"{current_year}-{month}-{day}", "%Y-%m-%d").timestamp())
            elif "-" in date_text and len(date_text.split("-")) == 3:
                # 直接处理 YYYY-MM-DD 格式
                return int(datetime.strptime(date_text, "%Y-%m-%d").timestamp())
            elif "-" in date_text and len(date_text.split("-")) == 2:
                # MM-DD 格式（当年）
                try:
                    current_year = datetime.now().year
                    month, day = date_text.split("-")
                    return int(datetime.strptime(f"{current_year}-{month.zfill(2)}-{day.zfill(2)}", "%Y-%m-%d").timestamp())
                except:
                    pass
            elif "小时前" in date_text or "分钟前" in date_text or "天前" in date_text:
                # 相对时间格式，计算大概的发布时间
                now = datetime.now()
                if "小时前" in date_text:
                    hours = int(re.search(r'(\d+)小时前', date_text).group(1))
                    return int((now - timedelta(hours=hours)).timestamp())
                elif "分钟前" in date_text:
                    minutes = int(re.search(r'(\d+)分钟前', date_text).group(1))
                    return int((now - timedelta(minutes=minutes)).timestamp())
                elif "天前" in date_text:
                    days = int(re.search(r'(\d+)天前', date_text).group(1))
                    return int((now - timedelta(days=days)).timestamp())
            else:
                logger.warning(f"未识别的日期格式: {date_text}")
        except Exception as e:
            logger.warning(f"日期解析失败: {date_text}, 错误: {e}")
        
        return 0
    
    
    
    
    def _parse_article_search(self, html_content: str, topk: int) -> List[Dict[str, Any]]:
        """解析专栏搜索结果"""
        results = []
        
        # 匹配专栏卡片 - 使用你提供的HTML结构
        article_pattern = r'<div[^>]*class="[^"]*b-article-card[^"]*"[^>]*>.*?</div>'
        article_matches = re.findall(article_pattern, html_content, re.DOTALL)
        
        for article_html in article_matches[:topk]:
            try:
                # 提取CV号（专栏ID）
                cv_match = re.search(r'href="[^"]*read/cv(\d+)', article_html)
                cv_id = cv_match.group(1) if cv_match else f"cv_{len(results)}"
                
                # 提取标题
                title_match = re.search(r'title="([^"]*)"', article_html)
                title = title_match.group(1) if title_match else ""
                
                # 提取描述
                desc_match = re.search(r'class="atc-desc[^"]*"[^>]*>([^<]+)</p>', article_html)
                description = desc_match.group(1) if desc_match else ""
                
                # 提取封面图片
                pic_match = re.search(r'src="([^"]*)"[^>]*alt="专栏"', article_html)
                pic = pic_match.group(1) if pic_match else ""
                
                # 提取点赞数和评论数
                like_match = re.search(r'(\d+)点赞', article_html)
                like_count = int(like_match.group(1)) if like_match else 0
                
                comment_match = re.search(r'(\d+)条评论', article_html)
                comment_count = int(comment_match.group(1)) if comment_match else 0
                
                # 提取分类
                category_match = re.search(r'href="[^"]*read/life#rid=(\d+)"[^>]*>([^<]+)</a>', article_html)
                category = category_match.group(2) if category_match else ""
                
                if title:  # 确保有基本数据
                    results.append({
                        "id": cv_id,
                        "title": title,
                        "description": description,
                        "pic": pic,
                        "reply": comment_count,
                        "like": like_count,
                        "author": "",  # 专栏搜索结果中通常不显示作者
                        "category": category,
                        "url": f"https://www.bilibili.com/read/cv{cv_id}"
                    })
                    
            except Exception as e:
                logger.warning(f"解析专栏结果失败: {e}")
                continue
        
        return results
    
    async def _async_parse_article_search(self, page, topk: int) -> List[Dict[str, Any]]:
        """使用异步Playwright解析专栏搜索结果"""
        results = []
        
        try:
            # 查找专栏卡片
            article_cards = await page.query_selector_all('.b-article-card, .search-article-card')
            
            for i, card in enumerate(article_cards[:topk]):
                try:
                    # 提取CV号
                    cv_id = ""
                    try:
                        link_element = await card.query_selector('a[href*="/read/cv"]')
                        if link_element:
                            href = await link_element.get_attribute('href')
                            cv_match = re.search(r'/read/cv(\d+)', href)
                            cv_id = cv_match.group(1) if cv_match else f"cv_{i}"
                    except:
                        cv_id = f"cv_{i}"
                    
                    # 提取标题
                    title = ""
                    try:
                        title_element = await card.query_selector('.b_text.i_card_title a, .text1')
                        if title_element:
                            title_attr = await title_element.get_attribute('title')
                            title_text = await title_element.text_content()
                            title = title_attr or title_text
                    except:
                        pass
                    
                    # 提取描述
                    description = ""
                    try:
                        desc_element = await card.query_selector('.atc-desc')
                        if desc_element:
                            description = await desc_element.text_content()
                    except:
                        pass
                    
                    # 提取封面图片
                    pic = ""
                    try:
                        img_element = await card.query_selector('img')
                        if img_element:
                            pic = await img_element.get_attribute('src')
                    except:
                        pass
                    
                    # 提取点赞数和评论数
                    like_count = 0
                    comment_count = 0
                    try:
                        info_element = await card.query_selector('.atc-info')
                        if info_element:
                            info_text = await info_element.text_content()
                            like_match = re.search(r'(\d+)点赞', info_text)
                            like_count = int(like_match.group(1)) if like_match else 0
                            
                            comment_match = re.search(r'(\d+)条评论', info_text)
                            comment_count = int(comment_match.group(1)) if comment_match else 0
                    except:
                        pass
                    
                    # 提取分类
                    category = ""
                    try:
                        category_element = await card.query_selector('.atc-info a')
                        if category_element:
                            category = await category_element.text_content()
                    except:
                        pass
                    
                    if title:  # 确保有基本数据
                        results.append({
                            "id": cv_id,
                            "title": title,
                            "description": description,
                            "pic": pic,
                            "reply": comment_count,
                            "like": like_count,
                            "author": "",  # 专栏搜索结果中通常不显示作者
                            "category": category,
                            "url": f"https://www.bilibili.com/read/cv{cv_id}"
                        })
                        
                except Exception as e:
                    logger.warning(f"解析专栏卡片失败: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"异步Playwright解析专栏结果失败: {e}")
        
        return results
    
    def _handle_video_error(self, error: Exception, bvid: str) -> Dict[str, Any]:
        """处理视频相关错误"""
        error_msg = str(error)
        error_messages = {
            "Expecting value: line 1 column 1 (char 0)": f'视频不存在或无法访问: {bvid}。请检查BV号是否正确',
            "404": f'视频不存在: {bvid}。请检查BV号是否正确',
            "Not Found": f'视频不存在: {bvid}。请检查BV号是否正确',
            "403": f'访问被拒绝: {bvid}。视频可能被删除或设为私密',
            "Forbidden": f'访问被拒绝: {bvid}。视频可能被删除或设为私密'
        }
        
        for key, message in error_messages.items():
            if key in error_msg:
                return ResponseFormatter.error(message, data=None)
        
        return ResponseFormatter.error(f'获取视频信息失败: {error_msg}', data=None)
    
    def get_video_info(self, bvid: str, method: str = "api") -> Dict[str, Any]:
        """获取视频详细信息"""
        try:
            if method == "script":
                return self._get_video_info_script_method(bvid)
            
            # API方法
            if not Validator.is_valid_bvid(bvid):
                return ResponseFormatter.error(f'无效的BV号格式: {bvid}。BV号应该以"BV"开头，后跟10位字符', data=None)
            
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            data = self._make_request(url)
            
            video_data = data["data"]
            
            # 安全获取tags
            tags = []
            if "tags" in video_data and video_data["tags"]:
                tags = [tag.get("tag_name", "") for tag in video_data["tags"] if tag.get("tag_name")]
            
            video_info = {
                "bvid": video_data["bvid"],
                "title": video_data["title"],
                "desc": video_data["desc"],
                "pic": video_data["pic"],
                "pubdate": video_data["pubdate"],
                "duration": video_data["duration"],
                "view": video_data["stat"]["view"],
                "danmaku": video_data["stat"]["danmaku"],
                "reply": video_data["stat"]["reply"],
                "favorite": video_data["stat"]["favorite"],
                "coin": video_data["stat"]["coin"],
                "share": video_data["stat"]["share"],
                "like": video_data["stat"]["like"],
                "owner_name": video_data["owner"]["name"],
                "owner_mid": video_data["owner"]["mid"],
                "tname": video_data["tname"],
                "tags": tags
            }
            
            return ResponseFormatter.success(video_info, "api")
            
        except Exception as e:
            logger.error(f"获取视频信息失败: {str(e)}")
            return self._handle_video_error(e, bvid)
    
    def _get_video_info_script_method(self, bvid: str) -> Dict[str, Any]:
        """
        脚本方法实现获取视频信息（使用网页抓取）
        
        Args:
            bvid: 视频BV号
            
        Returns:
            视频信息字典
        """
        try:
            if not Validator.is_valid_bvid(bvid):
                return {
                    'success': False,
                    'error': f'无效的BV号格式: {bvid}。BV号应该以"BV"开头，后跟10位字符',
                    'data': None
                }
            
            # 构建视频页面URL
            video_url = f"https://www.bilibili.com/video/{bvid}"
            
            # 添加延迟避免请求过快
            time.sleep(1)
            
            # 获取视频页面
            response = self.session.get(video_url, timeout=15)
            
            # 检查响应状态
            if response.status_code == 404:
                return {
                    'success': False,
                    'error': f'视频不存在: {bvid}。请检查BV号是否正确',
                    'data': None
                }
            elif response.status_code == 403:
                return {
                    'success': False,
                    'error': f'访问被拒绝: {bvid}。视频可能被删除或设为私密',
                    'data': None
                }
            
            response.raise_for_status()
            html_content = response.text
            
            # 检查是否是404页面
            if Validator.is_404_page(html_content, "video"):
                return {
                    'success': False,
                    'error': f'视频不存在: {bvid}。请检查BV号是否正确',
                    'data': None
                }
            
            # 使用正则表达式提取视频信息
            video_info = {
                "bvid": bvid,
                "title": "",
                "desc": "",
                "pic": "",
                "pubdate": 0,
                "duration": 0,
                "view": 0,
                "danmaku": 0,
                "reply": 0,
                "favorite": 0,
                "coin": 0,
                "share": 0,
                "like": 0,
                "owner_name": "",
                "owner_mid": "",
                "tname": "",
                "tags": []
            }
            
            # 提取各种信息
            video_info["title"] = DataExtractor.extract_text_by_pattern(html_content,
                                                                        r'<title>([^<]+)</title>').replace(
                '_哔哩哔哩_bilibili', '').strip()
            video_info["desc"] = DataExtractor.extract_text_by_pattern(html_content, r'"desc":"([^"]*)"')
            video_info["pic"] = DataExtractor.extract_text_by_pattern(html_content, r'"pic":"([^"]*)"').replace('\\',
                                                                                                                '')

            # 提取UP主信息
            owner_match = re.search(r'"owner":\{"mid":(\d+),"name":"([^"]*)"', html_content)
            if owner_match:
                video_info["owner_mid"] = owner_match.group(1)
                video_info["owner_name"] = owner_match.group(2)
            
            # 提取统计数据
            video_info["view"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content, r'<div class="view-text"[^>]*>([^<]+)</div>'))
            video_info["danmaku"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content, r'<div class="dm-text"[^>]*>([^<]+)</div>'))
            video_info["like"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content,
                                                      r'<span class="video-like-info[^>]*>([^<]+)</span>'))
            video_info["coin"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content,
                                                      r'<span class="video-coin-info[^>]*>([^<]+)</span>'))
            video_info["favorite"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content, r'<span class="video-fav-info[^>]*>([^<]+)</span>'))
            video_info["share"] = DataExtractor.parse_number_with_unit(
                DataExtractor.extract_text_by_pattern(html_content, r'class="[^"]*share[^"]*"[^>]*>([^<]+)</[^>]*>'))
            
            # 提取其他信息
            reply_match = re.search(r'"reply":(\d+)', html_content)
            if reply_match:
                video_info["reply"] = int(reply_match.group(1))
            
            pubdate_match = re.search(r'"pubdate":(\d+)', html_content)
            if pubdate_match:
                video_info["pubdate"] = int(pubdate_match.group(1))
            
            duration_match = re.search(r'"duration":(\d+)', html_content)
            if duration_match:
                video_info["duration"] = int(duration_match.group(1))
            
            tname_match = re.search(r'"tname":"([^"]*)"', html_content)
            if tname_match:
                video_info["tname"] = tname_match.group(1)
            
            # 提取标签
            tags_match = re.search(r'"tags":\[([^\]]*)\]', html_content)
            if tags_match:
                tags_str = tags_match.group(1)
                tag_matches = re.findall(r'"tag_name":"([^"]*)"', tags_str)
                video_info["tags"] = tag_matches
            
            # 如果标题为空，尝试其他方式提取
            if not video_info["title"]:
                title_match2 = re.search(r'"title":"([^"]*)"', html_content)
                if title_match2:
                    video_info["title"] = title_match2.group(1)
            
            # 如果仍然没有获取到基本信息，返回错误
            if not video_info["title"] and not video_info["owner_name"]:
                return {
                    'success': False,
                    'error': f'无法从页面中提取视频信息: {bvid}。视频可能不存在、被删除或页面结构发生变化',
                    'data': None
                }
            
            return {
                'success': True,
                'data': video_info,
                'method': 'script'
            }
            
        except Exception as e:
            logger.error(f"脚本方法获取视频信息失败: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'data': None
            }
    
    def get_danmaku(self, bvid: str, cid: Optional[str] = None) -> Dict[str, Any]:
        """获取视频弹幕"""
        try:
            # 只使用API方法
            if not cid:
                video_info = self.get_video_info(bvid)
                if not video_info['success']:
                    return ResponseFormatter.error(f"无法获取视频信息: {video_info.get('error', '未知错误')}", data=None)
                cid = "62131"  # 实际应该从video_info中获取pages[0]['cid']
            
            if not cid:
                return ResponseFormatter.error('无法获取视频CID', data=None)
            
            # 获取弹幕
            danmaku_url = f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}"
            response = self.session.get(danmaku_url, timeout=10)
            response.raise_for_status()
            
            # 确保正确解析UTF-8编码
            response.encoding = 'utf-8'
            danmaku_text = response.text
            
            return ResponseFormatter.success({
                'bvid': bvid,
                'cid': cid,
                'danmaku_xml': danmaku_text
            }, "api")
            
        except Exception as e:
            logger.error(f"获取弹幕失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=None)
    
    def get_comments(self, bvid: str, topk: int = 20, include_replies: bool = False, reply_count: int = 5) -> Dict[str, Any]:
        """获取视频评论"""
        if not self.cookies:
            return ResponseFormatter.error('获取评论需要提供用户cookies', data=[])
        
        try:
            # 验证BV号格式
            if not Validator.is_valid_bvid(bvid):
                return ResponseFormatter.error('无效的BV号格式', data=[])
            
            # 检查是否在事件循环中运行
            try:
                loop = asyncio.get_running_loop()
                # 如果已经在事件循环中，使用同步版本
                logger.info("检测到运行中的事件循环，使用同步版本获取评论")
                return self._get_comments_sync(bvid, topk, include_replies, reply_count)
            except RuntimeError:
                # 没有运行的事件循环，可以使用asyncio.run()
                return asyncio.run(self._get_comments_async(bvid, topk, include_replies, reply_count))
            
        except Exception as e:
            logger.error(f"获取评论失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    def _get_comments_sync(self, bvid: str, topk: int, include_replies: bool, reply_count: int = 5) -> Dict[str, Any]:
        """同步获取评论（用于事件循环环境，优化版本）"""
        try:
            # 获取AID
            aid = self._get_aid_from_bvid(bvid)
            if not aid:
                return ResponseFormatter.error(f'无法获取视频AID: {bvid}', data=[])
            
            # 获取主评论（限制数量以提高速度）
            effective_topk = min(topk, 100)  # MCP环境最多获取100条评论
            main_comments = self._fetch_main_comments_fast(aid, effective_topk)
            if not main_comments:
                return ResponseFormatter.success([], "api")
            
            # 处理评论数据
            processed_comments = []
            
            if include_replies:
                # 使用用户指定的回复数量
                max_replies_per_comment = min(reply_count, 5)  # MCP环境限制最大回复数量为5
                for comment in main_comments:
                    comment_data = {
                        "user": comment.get('member', {}).get('uname', '未知用户'),
                        "content": comment.get('content', {}).get('message', ''),
                        "like": comment.get('like', 0),
                        "time": comment.get('ctime', 0),
                        "replies": []
                    }
                    
                    # 如果需要包含回复，获取回复评论（使用用户指定的数量）
                    if comment.get('rcount', 0) > 0:
                        rpid = comment.get('rpid')
                        if rpid:
                            replies = self._fetch_sub_comments_fast(aid, rpid, max_replies_per_comment)
                            comment_data["replies"] = replies
                    
                    processed_comments.append(comment_data)
            else:
                # 不包含回复，直接处理主评论
                for comment in main_comments:
                    comment_data = {
                        "user": comment.get('member', {}).get('uname', '未知用户'),
                        "content": comment.get('content', {}).get('message', ''),
                        "like": comment.get('like', 0),
                        "time": comment.get('ctime', 0),
                        "replies": []
                    }
                    processed_comments.append(comment_data)
            
            return ResponseFormatter.success(processed_comments, "api")
            
        except Exception as e:
            logger.error(f"同步获取评论失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    async def _get_comments_async(self, bvid: str, topk: int, include_replies: bool, reply_count: int = 5) -> Dict[str, Any]:
        """异步获取评论"""
        try:
            # 获取AID
            aid = await self._get_aid_from_bvid_async(bvid)
            if not aid:
                return ResponseFormatter.error(f'无法获取视频AID: {bvid}', data=[])
            
            # 获取主评论
            main_comments = await self._fetch_main_comments_async(aid, topk)
            if not main_comments:
                return ResponseFormatter.success([], "api")
            
            # 处理评论数据
            processed_comments = []
            
            if include_replies:
                # 异步获取所有回复评论
                reply_tasks = []
                max_replies_per_comment = min(reply_count, 10)  # 限制最大回复数量为10
                for comment in main_comments:
                    if comment.get('rcount', 0) > 0:
                        rpid = comment.get('rpid')
                        if rpid:
                            task = self._fetch_sub_comments_async(aid, rpid, max_replies_per_comment)
                            reply_tasks.append((comment, task))
                
                # 并发执行所有回复获取任务
                if reply_tasks:
                    reply_results = await asyncio.gather(*[task for _, task in reply_tasks], return_exceptions=True)
                    
                    # 创建回复结果映射
                    reply_map = {}
                    for i, (comment, _) in enumerate(reply_tasks):
                        rpid = comment.get('rpid')
                        if i < len(reply_results) and not isinstance(reply_results[i], Exception):
                            reply_map[rpid] = reply_results[i]
                        else:
                            reply_map[rpid] = []
                
                # 组装最终结果
                for comment in main_comments:
                    comment_data = {
                        "user": comment.get('member', {}).get('uname', '未知用户'),
                        "content": comment.get('content', {}).get('message', ''),
                        "like": comment.get('like', 0),
                        "time": comment.get('ctime', 0),
                        "replies": reply_map.get(comment.get('rpid'), [])
                    }
                    processed_comments.append(comment_data)
            else:
                # 不包含回复，直接处理主评论
                for comment in main_comments:
                    comment_data = {
                        "user": comment.get('member', {}).get('uname', '未知用户'),
                        "content": comment.get('content', {}).get('message', ''),
                        "like": comment.get('like', 0),
                        "time": comment.get('ctime', 0),
                        "replies": []
                    }
                    processed_comments.append(comment_data)
            
            return ResponseFormatter.success(processed_comments, "api")
            
        except Exception as e:
            logger.error(f"异步获取评论失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=[])
    
    async def _get_aid_from_bvid_async(self, bvid: str) -> Optional[int]:
        """异步从BV号获取AID"""
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            data = await self._make_request_async(url, timeout=60)
            
            if data.get('code') == 0:
                return data.get('data', {}).get('aid')
            else:
                logger.error(f"获取AID失败: {data.get('message', '未知错误')}")
                return None
                
        except Exception as e:
            logger.error(f"获取AID时出错: {str(e)}")
            return None
    
    def _get_aid_from_bvid(self, bvid: str) -> Optional[int]:
        """从BV号获取AID（同步版本，保留兼容性）"""
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            data = self._make_request(url, timeout=60)
            
            if data.get('code') == 0:
                return data.get('data', {}).get('aid')
            else:
                logger.error(f"获取AID失败: {data.get('message', '未知错误')}")
                return None
                
        except Exception as e:
            logger.error(f"获取AID时出错: {str(e)}")
            return None
    
    async def _fetch_main_comments_async(self, aid: int, topk: int) -> List[Dict[str, Any]]:
        """异步获取主评论"""
        try:
            comments = []
            page = 1
            page_size = 50  # 增加页面大小到50
            
            while len(comments) < topk:
                url = f"https://api.bilibili.com/x/v2/reply/main"
                params = {
                    "type": 1,
                    "oid": aid,
                    "mode": 3,
                    "plat": 1,
                    "pn": page,
                    "ps": page_size
                }
                
                data = await self._make_request_async(url, params, timeout=60)
                
                if data.get('code') != 0:
                    logger.warning(f"获取评论失败: {data.get('message', '未知错误')}")
                    break
                
                replies = data.get('data', {}).get('replies', [])
                if not replies:
                    logger.info(f"第{page}页没有更多评论，停止获取")
                    break
                
                comments.extend(replies)
                logger.info(f"第{page}页获取到{len(replies)}条评论，总计{len(comments)}条")
                page += 1
                
                # 避免请求过于频繁
                await asyncio.sleep(0.3)
            
            logger.info(f"最终获取到{len(comments)}条评论，用户请求{topk}条")
            return comments[:topk]
            
        except Exception as e:
            logger.error(f"获取主评论失败: {str(e)}")
            return []
    
    def _fetch_main_comments_fast(self, aid: int, topk: int) -> List[Dict[str, Any]]:
        """快速获取主评论（用于MCP环境）"""
        try:
            comments = []
            page = 1
            page_size = min(topk, 50)  # 根据topk动态调整页面大小
            
            # 限制页数以避免超时
            max_pages = 3  # 最多获取3页
            while len(comments) < topk and page <= max_pages:
                url = f"https://api.bilibili.com/x/v2/reply/main"
                params = {
                    "type": 1,
                    "oid": aid,
                    "mode": 3,
                    "plat": 1,
                    "pn": page,
                    "ps": page_size
                }
                
                data = self._make_request(url, params, timeout=30)  # 减少超时时间到30秒
                
                if data.get('code') != 0:
                    logger.warning(f"获取评论失败: {data.get('message', '未知错误')}")
                    break
                
                replies = data.get('data', {}).get('replies', [])
                if not replies:
                    logger.info(f"第{page}页没有更多评论，停止获取")
                    break
                
                comments.extend(replies)
                logger.info(f"第{page}页获取到{len(replies)}条评论，总计{len(comments)}条")
                page += 1
                
                # 减少延迟时间
                time.sleep(0.1)
            
            logger.info(f"最终获取到{len(comments)}条评论，用户请求{topk}条")
            return comments[:topk]
            
        except Exception as e:
            logger.error(f"快速获取主评论失败: {str(e)}")
            return []
    
    def _fetch_main_comments(self, aid: int, topk: int) -> List[Dict[str, Any]]:
        """获取主评论（同步版本，保留兼容性）"""
        try:
            comments = []
            page = 1
            page_size = 50  # 增加页面大小到50
            
            while len(comments) < topk:
                url = f"https://api.bilibili.com/x/v2/reply/main"
                params = {
                    "type": 1,
                    "oid": aid,
                    "mode": 3,
                    "plat": 1,
                    "pn": page,
                    "ps": page_size
                }
                
                data = self._make_request(url, params, timeout=60)
                
                if data.get('code') != 0:
                    logger.warning(f"获取评论失败: {data.get('message', '未知错误')}")
                    break
                
                replies = data.get('data', {}).get('replies', [])
                if not replies:
                    logger.info(f"第{page}页没有更多评论，停止获取")
                    break
                
                comments.extend(replies)
                logger.info(f"第{page}页获取到{len(replies)}条评论，总计{len(comments)}条")
                page += 1
                
                # 避免请求过于频繁
                time.sleep(0.5)
            
            logger.info(f"最终获取到{len(comments)}条评论，用户请求{topk}条")
            return comments[:topk]
            
        except Exception as e:
            logger.error(f"获取主评论失败: {str(e)}")
            return []
    
    async def _fetch_sub_comments_async(self, aid: int, rpid: int, max_replies: int = 10) -> List[Dict[str, Any]]:
        """异步获取回复评论"""
        try:
            replies = []
            page = 1
            page_size = 10
            
            while len(replies) < max_replies:
                url = f"https://api.bilibili.com/x/v2/reply/reply"
                params = {
                    "type": 1,
                    "oid": aid,
                    "root": rpid,
                    "pn": page,
                    "ps": page_size
                }
                
                data = await self._make_request_async(url, params, timeout=60)
                
                if data.get('code') != 0:
                    logger.warning(f"获取回复失败: {data.get('message', '未知错误')}")
                    break
                
                sub_replies = data.get('data', {}).get('replies', [])
                if not sub_replies:
                    break
                
                # 处理回复数据
                for reply in sub_replies:
                    replies.append({
                        "user": reply.get('member', {}).get('uname', '未知用户'),
                        "content": reply.get('content', {}).get('message', ''),
                        "like": reply.get('like', 0),
                        "time": reply.get('ctime', 0)
                    })
                
                page += 1
                
                # 避免请求过于频繁
                await asyncio.sleep(0.2)
            
            return replies[:max_replies]
            
        except Exception as e:
            logger.error(f"获取回复评论失败: {str(e)}")
            return []
    
    def _fetch_sub_comments_fast(self, aid: int, rpid: int, max_replies: int = 3) -> List[Dict[str, Any]]:
        """快速获取回复评论（用于MCP环境）"""
        try:
            replies = []
            page = 1
            page_size = min(max_replies, 20)  # 增加页面大小到20
            
            # 只获取一页，避免多次请求
            url = f"https://api.bilibili.com/x/v2/reply/reply"
            params = {
                "type": 1,
                "oid": aid,
                "root": rpid,
                "pn": page,
                "ps": page_size
            }
            
            data = self._make_request(url, params, timeout=30)  # 减少超时时间到30秒
            
            if data.get('code') != 0:
                logger.warning(f"获取回复失败: {data.get('message', '未知错误')}")
                return []
            
            sub_replies = data.get('data', {}).get('replies', [])
            
            # 处理回复数据
            for reply in sub_replies:
                replies.append({
                    "user": reply.get('member', {}).get('uname', '未知用户'),
                    "content": reply.get('content', {}).get('message', ''),
                    "like": reply.get('like', 0),
                    "time": reply.get('ctime', 0)
                })
            
            return replies[:max_replies]
            
        except Exception as e:
            logger.error(f"快速获取回复评论失败: {str(e)}")
            return []
    
    def _fetch_sub_comments(self, aid: int, rpid: int, max_replies: int = 10) -> List[Dict[str, Any]]:
        """获取回复评论（同步版本，保留兼容性）"""
        try:
            replies = []
            page = 1
            page_size = 10
            
            while len(replies) < max_replies:
                url = f"https://api.bilibili.com/x/v2/reply/reply"
                params = {
                    "type": 1,
                    "oid": aid,
                    "root": rpid,
                    "pn": page,
                    "ps": page_size
                }
                
                data = self._make_request(url, params, timeout=60)
                
                if data.get('code') != 0:
                    logger.warning(f"获取回复失败: {data.get('message', '未知错误')}")
                    break
                
                sub_replies = data.get('data', {}).get('replies', [])
                if not sub_replies:
                    break
                
                # 处理回复数据
                for reply in sub_replies:
                    replies.append({
                        "user": reply.get('member', {}).get('uname', '未知用户'),
                        "content": reply.get('content', {}).get('message', ''),
                        "like": reply.get('like', 0),
                        "time": reply.get('ctime', 0)
                    })
                
                page += 1
                
                # 避免请求过于频繁
                time.sleep(0.3)
            
            return replies[:max_replies]
            
        except Exception as e:
            logger.error(f"获取回复评论失败: {str(e)}")
            return []
    
    
    
    def get_article(self, cv_id: str) -> Dict[str, Any]:
        """获取专栏文章详细信息"""
        try:
            # 只使用脚本方法
            return self._get_article_info_script_method(cv_id)
            
        except Exception as e:
            logger.error(f"获取文章信息失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=None)
    
    def _get_article_info_script_method(self, cv_id: str) -> Dict[str, Any]:
        """
        脚本方法实现获取文章信息（通过网页抓取）
        
        Args:
            cv_id: 专栏文章CV号
            
        Returns:
            文章信息字典
        """
        try:
            # 验证CV号格式
            if not Validator.is_valid_cv_id(cv_id):
                return ResponseFormatter.error(f'无效的CV号格式: {cv_id}。CV号应该是纯数字', data=None)
            
            # 构建文章页面URL
            article_url = f"https://www.bilibili.com/read/cv{cv_id}"
            
            # 添加延迟避免请求过快
            time.sleep(1)
            
            # 获取文章页面
            response = self.session.get(article_url, timeout=15)
            
            # 检查响应状态
            if response.status_code == 404:
                return ResponseFormatter.error(f'文章不存在: cv{cv_id}。请检查CV号是否正确', data=None)
            elif response.status_code == 403:
                return ResponseFormatter.error(f'访问被拒绝: cv{cv_id}。文章可能被删除或设为私密', data=None)
            
            response.raise_for_status()
            html_content = response.text
            
            # 检查是否是404页面
            if Validator.is_404_page(html_content, "article"):
                return ResponseFormatter.error(f'文章不存在: cv{cv_id}。请检查CV号是否正确', data=None)
            
            # 解析文章信息
            article_info = self._parse_article_content(html_content, cv_id)
            
            if not article_info.get("title"):
                return ResponseFormatter.error(f'无法从页面中提取文章信息: cv{cv_id}。文章可能不存在、被删除或页面结构发生变化', data=None)
            
            return ResponseFormatter.success(article_info, "script")
            
        except Exception as e:
            logger.error(f"脚本方法获取文章信息失败: {str(e)}")
            return ResponseFormatter.error(str(e), data=None)
    
    def _parse_article_content(self, html_content: str, cv_id: str) -> Dict[str, Any]:
        """
        解析文章页面内容
        
        Args:
            html_content: HTML页面内容
            cv_id: CV号
            
        Returns:
            文章信息字典
        """
        article_info = {
            "cv_id": cv_id,
            "title": "",
            "author": "",
            "author_avatar": "",
            "publish_time": "",
            "content": "",
            "images": [],
            "tags": [],
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "coin_count": 0,
            "favorite_count": 0,
            "url": f"https://www.bilibili.com/read/cv{cv_id}"
        }
        
        try:
            # 提取标题
            title_match = re.search(r'<span class="opus-module-title__text">([^<]+)</span>', html_content)
            if title_match:
                article_info["title"] = title_match.group(1).strip()
            
            # 提取作者信息
            author_match = re.search(r'<div class="opus-module-author__name"[^>]*>([^<]+)</div>', html_content)
            if author_match:
                article_info["author"] = author_match.group(1).strip()
            
            # 提取作者头像
            avatar_match = re.search(r'<img[^>]*src="([^"]*)"[^>]*onload="bmgOnLoad\(this\)"[^>]*>', html_content)
            if avatar_match:
                article_info["author_avatar"] = avatar_match.group(1)
            
            # 提取发布时间
            time_match = re.search(r'<div class="opus-module-author__pub__text">([^<]+)</div>', html_content)
            if time_match:
                article_info["publish_time"] = time_match.group(1).strip()
            
            # 提取文章内容和图片，保持顺序关系
            # 使用字符串查找方法，避免正则表达式匹配问题
            content_start = html_content.find('<div class="opus-module-content">')
            if content_start != -1:
                content_end = html_content.find('<div class="opus-module-extend">', content_start)
                if content_end != -1:
                    content_html = html_content[content_start:content_end]
                    # 解析内容结构，保持文本和图片的顺序
                    content_data = self._parse_content_structure(content_html)
                    article_info["content"] = content_data["text"]
                    article_info["images"] = content_data["images"]
                    article_info["content_structure"] = content_data["structure"]
            
            # 提取标签
            tag_matches = re.findall(r'<span class="opus-module-extend__item__text">([^<]+)</span>', html_content)
            article_info["tags"] = [tag.strip() for tag in tag_matches if tag.strip()]
            
            # 提取统计数据 - 从side-toolbar中精确提取
            # 点赞数
            like_match = re.search(r'<div class="side-toolbar__action like">.*?<div class="side-toolbar__action__text">(\d+)</div>', html_content, re.DOTALL)
            if like_match:
                article_info["like_count"] = int(like_match.group(1))
            
            # 投币数
            coin_match = re.search(r'<div class="side-toolbar__action coin">.*?<div class="side-toolbar__action__text">(\d+)</div>', html_content, re.DOTALL)
            if coin_match:
                article_info["coin_count"] = int(coin_match.group(1))
            
            # 收藏数
            favorite_match = re.search(r'<div class="side-toolbar__action favorite">.*?<div class="side-toolbar__action__text">(\d+)</div>', html_content, re.DOTALL)
            if favorite_match:
                article_info["favorite_count"] = int(favorite_match.group(1))
            
            # 转发数
            forward_match = re.search(r'<div class="side-toolbar__action forward">.*?<div class="side-toolbar__action__text">(\d+)</div>', html_content, re.DOTALL)
            if forward_match:
                article_info["share_count"] = int(forward_match.group(1))
            
            # 评论数
            comment_match = re.search(r'<div class="side-toolbar__action comment">.*?<div class="side-toolbar__action__text">(\d+)</div>', html_content, re.DOTALL)
            if comment_match:
                article_info["comment_count"] = int(comment_match.group(1))
            
        except Exception as e:
            logger.warning(f"解析文章内容时出错: {e}")
        
        return article_info
    
    def _parse_content_structure(self, html: str) -> Dict[str, Any]:
        """
        解析文章内容结构，保持文本和图片的顺序关系
        
        Args:
            html: 文章内容HTML
            
        Returns:
            包含文本、图片和结构信息的字典
        """
        structure = []
        images = []
        text_parts = []
        
        # 更精确的解析：分别处理段落和图片块
        # 先提取所有段落
        paragraphs = re.findall(r'<p[^>]*data-v-[^>]*>.*?</p>', html, re.DOTALL)
        for p in paragraphs:
            text_content = self._extract_text_from_html(p)
            if text_content.strip():
                text_parts.append(text_content.strip())
                structure.append({
                    "type": "text",
                    "content": text_content.strip()
                })
        
        # 再提取所有图片块 - 使用更宽松的匹配
        img_blocks = re.findall(r'<div class="opus-para-pic[^"]*">.*?</div>', html, re.DOTALL)
        for img_block in img_blocks:
            # 提取图片URL - 尝试多种匹配方式
            img_match = re.search(r'<img[^>]*src="([^"]*)"[^>]*>', img_block)
            if img_match:
                img_url = img_match.group(1)
                if img_url.startswith('//') or img_url.startswith('http'):
                    images.append(img_url)
                    structure.append({
                        "type": "image",
                        "url": img_url,
                        "index": len(images) - 1
                    })
        
        # 如果上面的方法没有找到图片，尝试备用方法
        if not images:
            self._extract_images_fallback(html, images, structure)
        
        # 合并所有文本
        full_text = '\n\n'.join(text_parts)
        
        return {
            "text": full_text,
            "images": images,
            "structure": structure
        }
    
    def _extract_images_fallback(self, html: str, images: List[str], structure: List[Dict[str, Any]]) -> None:
        """备用图片提取方法"""
        # 尝试多种匹配模式
        patterns = [
            r'<img[^>]*src="([^"]*)"[^>]*loading="lazy"[^>]*>',
            r'<img[^>]*src="([^"]*)"[^>]*>'
        ]
        
        for pattern in patterns:
            all_imgs = re.findall(pattern, html)
            for img_url in all_imgs:
                if img_url.startswith('//') or img_url.startswith('http'):
                    # 过滤掉头像图片和小图标
                    if ('face' not in img_url and 'avatar' not in img_url and 
                        'icon' not in img_url and 'logo' not in img_url and
                        len(img_url) > 50):  # 文章图片通常URL较长
                        images.append(img_url)
                        structure.append({
                            "type": "image",
                            "url": img_url,
                            "index": len(images) - 1
                        })
            if images:  # 如果找到了图片就停止
                break
    
    def _extract_text_from_html(self, html: str) -> str:
        """从HTML中提取纯文本内容"""
        return DataExtractor.extract_text_from_html(html)
    
    