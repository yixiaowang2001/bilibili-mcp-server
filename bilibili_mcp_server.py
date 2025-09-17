#!/usr/bin/env python3
"""
B站MCP服务器
提供B站数据获取功能的Model Context Protocol服务器
"""

import json
import os
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from bilibili_client import BilibiliClient

# 创建MCP服务器实例
mcp = FastMCP("Bilibili MCP Server")


class CookieManager:
    """Cookie管理类"""
    
    @staticmethod
    def load_cookies() -> Optional[str]:
        """从文件加载cookies"""
        try:
            cookies_file = os.path.join(os.path.dirname(__file__), 'bilibili_cookies.json')
            if not os.path.exists(cookies_file):
                return None
                
            with open(cookies_file, 'r', encoding='utf-8') as f:
                cookies_data = json.load(f)
                
                # 如果是数组格式，转换为字符串格式
                if isinstance(cookies_data, list):
                    cookie_pairs = []
                    for cookie in cookies_data:
                        if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                            cookie_pairs.append(f"{cookie['name']}={cookie['value']}")
                    return '; '.join(cookie_pairs)
                
                # 如果是对象格式，直接返回cookies字段
                elif isinstance(cookies_data, dict):
                    return cookies_data.get('cookies')
                
                # 如果是字符串格式，直接返回
                elif isinstance(cookies_data, str):
                    return cookies_data
                    
        except Exception as e:
            print(f"加载cookies失败: {e}")
        return None


def _format_response(result: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """格式化响应结果"""
    if result['success']:
        response = {
            "success": True,
            "method": result.get('method', 'unknown'),
            "total": len(result['data']) if isinstance(result['data'], list) else 1,
            "data": result['data']
        }
        response.update(kwargs)
        return response
    else:
        response = {
            "success": False,
            "error": result.get('error', '操作失败')
        }
        response.update(kwargs)
        return response


def _handle_error(error: Exception, **kwargs) -> Dict[str, Any]:
    """处理错误响应"""
    response = {
        "success": False,
        "error": str(error)
    }
    response.update(kwargs)
    return response


def _create_client() -> BilibiliClient:
    """创建BilibiliClient实例"""
    cookies = CookieManager.load_cookies()
    return BilibiliClient(cookies=cookies)


def _execute_tool(client_method, *args, **kwargs) -> Dict[str, Any]:
    """通用工具执行函数，减少重复代码"""
    try:
        client = _create_client()
        result = client_method(client, *args)
        return _format_response(result, **kwargs)
    except Exception as e:
        return _handle_error(e, **kwargs)


@mcp.tool()
def search_videos(keyword: str, topk: int = 10, method: str = "api") -> Dict[str, Any]:
    """
    搜索B站视频
    
    Args:
        keyword: 搜索关键词
        topk: 返回结果数量，默认为10
        method: 获取方法，默认为"api"，可选："api", "script"
        
    Returns:
        包含视频搜索结果的字典数据
    """
    return _execute_tool(
        lambda client: client.search_videos(keyword, topk, method),
        keyword=keyword, search_type="video"
    )


@mcp.tool()
def search_articles(keyword: str, topk: int = 10) -> Dict[str, Any]:
    """
    搜索B站专栏文章
    
    Args:
        keyword: 搜索关键词
        topk: 返回结果数量，默认为10
        
    Returns:
        包含专栏搜索结果的字典数据
    """
    return _execute_tool(
        lambda client: client.search_articles(keyword, topk),
        keyword=keyword, search_type="article"
    )


@mcp.tool()
def get_video_info(bvid: str, method: str = "api") -> Dict[str, Any]:
    """
    获取视频详细信息
    
    Args:
        bvid: 视频BV号
        method: 获取方法，默认为"api"，可选："api", "script"
        
    Returns:
        包含视频详细信息的字典数据
    """
    return _execute_tool(
        lambda client: client.get_video_info(bvid, method),
        bvid=bvid
    )


@mcp.tool()
def get_danmaku(bvid: str, cid: Optional[str] = None) -> Dict[str, Any]:
    """
    获取视频弹幕
    
    Args:
        bvid: 视频BV号
        cid: 视频分P的CID，如果不提供会自动获取
        
    Returns:
        包含弹幕数据的字典
    """
    return _execute_tool(
        lambda client: client.get_danmaku(bvid, cid),
        bvid=bvid, cid=cid
    )


@mcp.tool()
def get_comments(bvid: str, topk: int = 20, include_replies: bool = False, reply_count: int = 5) -> Dict[str, Any]:
    """
    获取视频评论
    
    Args:
        bvid: 视频BV号
        topk: 返回评论数量，默认为20
        include_replies: 是否包含嵌套评论，默认为False
        reply_count: 每个评论的回复数量，默认为5
        
    Returns:
        包含评论数据的字典
    """
    return _execute_tool(
        lambda client: client.get_comments(bvid, topk, include_replies, reply_count),
        bvid=bvid
    )


@mcp.tool()
def get_article(cv_id: str) -> Dict[str, Any]:
    """
    获取专栏文章详细信息
    
    Args:
        cv_id: 专栏文章CV号（如：12411259）
        
    Returns:
        包含文章详细信息的字典数据
    """
    return _execute_tool(
        lambda client: client.get_article(cv_id),
        cv_id=cv_id
    )




if __name__ == "__main__":
    # 运行MCP服务器
    mcp.run()