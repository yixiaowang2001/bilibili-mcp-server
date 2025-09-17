import json
from pathlib import Path

from playwright.sync_api import sync_playwright

# B站cookies配置
BILIBILI_CONFIG = {
    "site_domain": ".bilibili.com",
    "site_url": "https://www.bilibili.com/",
    "cookie_path": "bilibili_cookies.json",
    "timeout": 60000
}


def save_bilibili_cookies():
    """保存B站cookies"""
    site_domain = BILIBILI_CONFIG["site_domain"]
    site_url = BILIBILI_CONFIG["site_url"]
    cookie_path = BILIBILI_CONFIG["cookie_path"]
    timeout = BILIBILI_CONFIG["timeout"]

    # 在当前目录保存cookies文件
    file_path = Path(__file__).parent / cookie_path

    print("正在启动浏览器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"正在打开B站: {site_url}")
        print("请手动登录B站，登录完成后按回车键保存cookies...")

        try:
            page.goto(site_url, timeout=timeout)
            page.wait_for_load_state('networkidle')

            # 等待用户手动登录
            input("登录完成后请按回车键继续...")

            # 获取cookies
            cookies = context.cookies()
            cookies = _sanitize_cookies(cookies)

            # 设置正确的域名
            for cookie in cookies:
                cookie["domain"] = site_domain

            # 保存cookies到文件
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)

            print(f"B站cookies已保存到: {file_path}")
            print("登录成功！")

        except Exception as e:
            print(f"保存cookies时出错: {str(e)}")
        finally:
            browser.close()


def _sanitize_cookies(raw):
    cleaned, seen = [], set()
    for c in raw or []:
        if not c.get("name"):
            continue
        if c.get("value", "") == "":
            continue
        c = c.copy()
        key = (c["name"], c.get("domain"), c.get("path", "/"))
        if key in seen:
            continue
        seen.add(key)
        if "expires" in c:
            if c["expires"] <= 0:
                c.pop("expires")
            else:
                c["expires"] = int(c["expires"])
        if c.get("sameSite") == "None" and not c.get("secure", False):
            c["secure"] = True
        cleaned.append(c)
    return cleaned


if __name__ == "__main__":
    print("=== B站Cookies保存工具 ===")
    print("此工具将帮助您保存B站登录cookies")
    print("请确保您已准备好登录B站账号")

    save_bilibili_cookies()
