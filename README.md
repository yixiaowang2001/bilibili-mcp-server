# Bilibili MCP Server

基于[bilibili-api](https://github.com/nemo2011/bilibili-api)和Playwright的B站MCP Server，关注于数据获取，支持多种相关操作。

## 工具列表

- **search_videos**: 搜索视频，支持关键词搜索，可指定返回数量和方法（API/网页抓取）
- **search_articles**: 搜索专栏文章，使用网页抓取方式获取真实数据
- **get_video_info**: 获取视频详细信息，包括统计数据、UP主信息、标签等
- **get_danmaku**: 获取视频弹幕信息，返回XML格式数据
- **get_comments**: 获取视频评论，支持嵌套回复和数量控制（需要cookies）
- **get_article**: 获取专栏文章详细内容和相关数据

## 环境要求

- Python 3.8+
- pip 包管理器

## 使用方法

1. clone 本项目

```bash
git clone <repository-url>
cd bilibili-mcp-server
```

2. 使用 pip 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

3. 在任意 mcp client 中配置本 Server

```json
{
  "mcpServers": {
    "bilibili": {
      "command": "python",
      "args": ["/your-project-path/bilibili-mcp-server/bilibili_mcp_server.py"]
    }
  }
}
```

4. 在 client 中使用

## 快速测试

使用 MCP Inspector 进行测试：

```bash
# 安装 MCP Inspector
npm install -g @modelcontextprotocol/inspector

# 启动测试
mcp-inspector -- python bilibili_mcp_server.py
```

## 使用示例

### 搜索视频
```json
{
  "keyword": "Python教程",
  "topk": 10,
  "method": "api"
}
```

### 获取视频信息
```json
{
  "bvid": "BV1xx411c7mu",
  "method": "api"
}
```

### 获取评论
```json
{
  "bvid": "BV1xx411c7mu",
  "topk": 20,
  "include_replies": true,
  "reply_count": 5
}
```

## 配置Cookies

如果需要获取评论功能，需要配置用户cookies：

```bash
python cookies_tool.py
```

按照提示操作即可自动保存cookies。

## 注意事项

- **请求频率**: 已添加请求延迟，避免触发反爬机制
- **Cookies**: 获取评论功能需要有效的用户cookies
- **网络环境**: 确保网络连接稳定
- **API限制**: 遵循B站API使用规范，避免过度请求

## 故障排除

1. **412错误**: 请求被拒绝
   - 解决方案：检查cookies是否有效，尝试使用script方法

2. **超时错误**: 请求超时
   - 解决方案：检查网络连接，减少请求数量

3. **Playwright错误**: 专栏搜索失败
   - 解决方案：运行 `playwright install chromium` 安装浏览器

## 项目结构

```
bili-mcp_backup/
├── bilibili_mcp_server.py    # MCP服务器主文件
├── bilibili_client.py         # B站API客户端
├── bilibili_cookies.json     # 用户cookies配置
├── mcp_config.json           # MCP配置文件
├── cookies_tool.py           # Cookies管理工具
├── requirements.txt          # 依赖包
├── README.md                # 项目说明
└── 开发日志.md              # 开发日志
```