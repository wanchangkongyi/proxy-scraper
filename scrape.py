#!/usr/bin/env python3
"""
北极光代理（proxy-socks5.com）第 1 页代理抓取脚本（单文件版）。

依赖：requests, beautifulsoup4
    pip install requests beautifulsoup4

登录方式（可以同时配置，Cookie 优先，失效自动 fallback）：
  A. Cookie 登录（推荐，优先尝试）：设置 SITE_COOKIE 环境变量为浏览器
     登录后 Network 面板里请求头的完整 Cookie 值，脚本直接带上这个
     Cookie 访问代理列表页，不走登录表单。
  B. 账号密码登录：如果 SITE_COOKIE 未设置，或设置了但已失效，会用
     SITE_USERNAME / SITE_PASSWORD 自动解析并提交登录表单（详见 login()）。
     两种方式可以同时配置：Cookie 有效时优先用 Cookie（更快、更省请求），
     Cookie 过期后自动切换到账号密码，不需要人工干预更新 Cookie。

流程：
  1. 建立已认证的 session（Cookie 或 表单登录二选一）。
  2. 请求代理列表第 1 页（PROXY_LIST_URL）。
  3. 解析表格，得到 协议://ip:端口。
  4. 写入 proxies/latest.txt（每次覆盖，只保留最新一份结果，
     不再生成按日期归档的文件）。
  5. 如果配置了 GIST_TOKEN + GIST_ID，把 latest.txt 的内容同步更新到 Gist。

注意：未登录状态下网站会把 IP 打码（例如 37.9.X.127），此时正则
无法匹配出合法 IP，因此如果本次抓取结果为空，大概率是 Cookie 已过期
或账号密码 / 登录表单有问题。
"""

import json
import os
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LOGIN_URL = os.environ.get("LOGIN_URL", "https://proxy-socks5.com/login")
PROXY_LIST_URL = os.environ.get("PROXY_LIST_URL", "https://proxy-socks5.com/proxy_list?page=1")
SITE_COOKIE = os.environ.get("SITE_COOKIE")  # 例如 "session=xxxx; other=yyy"
SITE_USERNAME = os.environ.get("SITE_USERNAME")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD")

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "proxies")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "latest.txt")

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = os.environ.get("GIST_FILENAME", "proxies_latest.txt")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30

# 匹配 "socks5 1.2.3.4:1080" / "http 1.2.3.4:1080" 这种 "协议 + ip:port" 组合文本
PROXY_RE = re.compile(
    r"\b(socks5|socks4|http|https)\s+(\d{1,3}(?:\.\d{1,3}){3})\s*[:：]\s*(\d{2,5})\b",
    re.IGNORECASE,
)
# 兜底：只匹配 ip:port，协议未知时标记为 unknown
IP_PORT_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\s*[:：]\s*(\d{2,5})\b")


def _headers():
    return {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


def apply_cookie(session: requests.Session, raw_cookie: str) -> bool:
    """把浏览器复制出来的原始 Cookie 字符串灌进 session，并验证是否登录成功。"""
    for part in raw_cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        session.cookies.set(name.strip(), value.strip())

    resp = session.get(PROXY_LIST_URL, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return "退出登录" in resp.text


def login(session: requests.Session, login_url: str, username: str, password: str) -> bool:
    """
    自动解析登录页的 <form>：
      - type="password" 的 input 当密码字段
      - 第一个非 hidden 的文本类 input 当用户名字段
      - 其余 hidden input（如 csrf token）原样带上
    然后向表单的 action 提交登录请求。
    """
    resp = session.get(login_url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    form = soup.find("form")
    if form is None:
        print("ERROR: 登录页面里没有找到 <form>，网站结构可能已变化。", file=sys.stderr)
        return False

    action = form.get("action") or login_url
    post_url = urljoin(login_url, action)
    method = (form.get("method") or "post").strip().lower()

    data = {}
    username_field = None
    password_field = None

    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()

        if itype == "password":
            password_field = name
            continue
        if itype == "hidden":
            data[name] = inp.get("value", "")
            continue
        if itype in ("submit", "button", "checkbox", "radio"):
            continue
        if username_field is None:
            username_field = name

    if username_field is None or password_field is None:
        print(
            "ERROR: 未能自动识别用户名/密码输入框，请检查登录表单 HTML，"
            "并按需在 login() 里手动指定字段名。",
            file=sys.stderr,
        )
        return False

    data[username_field] = username
    data[password_field] = password

    if method == "get":
        login_resp = session.get(post_url, params=data, headers=_headers(), timeout=REQUEST_TIMEOUT)
    else:
        login_resp = session.post(post_url, data=data, headers=_headers(), timeout=REQUEST_TIMEOUT)
    login_resp.raise_for_status()

    if "退出登录" in login_resp.text:
        return True

    check_resp = session.get(PROXY_LIST_URL, headers=_headers(), timeout=REQUEST_TIMEOUT)
    return "退出登录" in check_resp.text


def parse_proxies(html: str):
    """
    解析代理列表表格，返回 "协议://ip:端口" 字符串列表。
    优先匹配 "协议 + ip:port" 组合文本（该站点表格就是这种格式），
    找不到协议前缀时退化为 unknown://ip:port。
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if not any("ip" in h for h in header_cells):
            continue

        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if not cells:
                continue
            row_text = " ".join(cells)

            m = PROXY_RE.search(row_text)
            if m:
                protocol, ip, port = m.group(1).lower(), m.group(2), m.group(3)
            else:
                m2 = IP_PORT_RE.search(row_text)
                if not m2:
                    continue
                protocol, ip, port = "unknown", m2.group(1), m2.group(2)

            key = f"{protocol}://{ip}:{port}"
            if key in seen:
                continue
            seen.add(key)
            results.append(key)

        if results:
            return results

    # 兜底：整页纯文本正则扫描
    text = soup.get_text(" ")
    for m in PROXY_RE.finditer(text):
        key = f"{m.group(1).lower()}://{m.group(2)}:{m.group(3)}"
        if key not in seen:
            seen.add(key)
            results.append(key)

    return results


def write_output(proxies):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for line in proxies:
            f.write(line + "\n")
    return OUTPUT_FILE


def upload_gist(proxies):
    if not GIST_TOKEN or not GIST_ID:
        print("未配置 GIST_TOKEN / GIST_ID，跳过 Gist 同步。")
        return

    content = "\n".join(proxies) + "\n" if proxies else "# 本次运行未解析到任何代理\n"
    resp = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={
            "Authorization": f"token {GIST_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        data=json.dumps({"files": {GIST_FILENAME: {"content": content}}}),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"ERROR: 更新 Gist 失败 ({resp.status_code}): {resp.text}", file=sys.stderr)
        return
    print(f"Gist 已更新: {resp.json().get('html_url')}")


def authenticate(session: requests.Session) -> bool:
    """
    认证优先级：
      1. 如果配置了 SITE_COOKIE，先尝试 Cookie 登录。
         - 成功：直接返回 True。
         - 失败（Cookie 过期/无效）：如果同时配置了账号密码，自动
           fallback 到表单登录；否则直接失败。
      2. 没配置 SITE_COOKIE，直接走账号密码登录。
    """
    if SITE_COOKIE:
        print("检测到 SITE_COOKIE，优先尝试 Cookie 登录 ...")
        try:
            if apply_cookie(session, SITE_COOKIE):
                print("Cookie 有效，已登录。")
                return True
            print("Cookie 已失效（未找到'退出登录'字样）。", file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: 用 Cookie 访问代理列表失败: {e}", file=sys.stderr)

        if not (SITE_USERNAME and SITE_PASSWORD):
            print(
                "ERROR: Cookie 失效，且未配置 SITE_USERNAME/SITE_PASSWORD 作为备用，"
                "请重新登录网站更新 SITE_COOKIE，或补充账号密码。",
                file=sys.stderr,
            )
            return False

        print(f"Cookie 失效，自动改用账号密码登录 {LOGIN_URL} ...")
        # Cookie 尝试失败后，session 里可能残留了失效的 cookie，清空重来
        session.cookies.clear()

    elif not (SITE_USERNAME and SITE_PASSWORD):
        print(
            "ERROR: 请设置 SITE_COOKIE，或设置 SITE_USERNAME + SITE_PASSWORD（可以两者都配，"
            "Cookie 失效时会自动 fallback 到账号密码）。",
            file=sys.stderr,
        )
        return False

    try:
        ok = login(session, LOGIN_URL, SITE_USERNAME, SITE_PASSWORD)
    except requests.RequestException as e:
        print(f"ERROR: 登录请求失败: {e}", file=sys.stderr)
        return False

    if not ok:
        print(
            "ERROR: 账号密码登录也失败了（响应里没有找到'退出登录'字样）。"
            "请检查账号密码，或登录表单结构是否变化。",
            file=sys.stderr,
        )
        return False

    print("账号密码登录成功。")
    return True


def main():
    session = requests.Session()

    if not authenticate(session):
        sys.exit(1)

    print(f"正在抓取 {PROXY_LIST_URL} ...")
    try:
        resp = session.get(PROXY_LIST_URL, headers=_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: 抓取代理列表失败: {e}", file=sys.stderr)
        sys.exit(1)

    proxies = parse_proxies(resp.text)
    print(f"解析到 {len(proxies)} 条代理。")

    if not proxies:
        print(
            "WARNING: 未解析到任何代理。若确实已登录，IP 不应该被打码，"
            "多半是页面结构变化导致解析失败；如果怀疑是登录/Cookie 失效，"
            "重新检查 SITE_COOKIE 或 SITE_USERNAME/SITE_PASSWORD。",
            file=sys.stderr,
        )

    output_path = write_output(proxies)
    print(f"已写入 {output_path}")

    upload_gist(proxies)


if __name__ == "__main__":
    main()
