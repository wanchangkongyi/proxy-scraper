#!/usr/bin/env python3
"""
北极光代理（proxy-socks5.com）第 1 页代理抓取脚本。

登录方式（二选一，优先 Cookie）：
  A. Cookie 登录（推荐）：设置 SITE_COOKIE 环境变量为浏览器登录后
     Network 面板里请求头的完整 Cookie 值，脚本直接带上这个 Cookie
     访问代理列表页，不走登录表单。
  B. 账号密码登录：未设置 SITE_COOKIE 时，用 SITE_USERNAME /
     SITE_PASSWORD 自动解析并提交登录表单（详见 login()）。

流程：
  1. 建立已认证的 session（Cookie 或 表单登录二选一）。
  2. 请求代理列表第 1 页（PROXY_LIST_URL）。
  3. 解析表格，得到 ip:port（以及类型、地理信息等附加字段）。
  4. 写入 proxies/ 目录：
       - proxies/latest.json / proxies/latest.txt   最新一次结果
       - proxies/YYYY-MM-DD.json / .txt             当日归档快照

注意：未登录状态下网站会把 IP 打码（例如 37.9.X.127），此时正则
无法匹配出合法 IP，因此如果本次抓取结果为空，大概率是 Cookie 已过期
或账号密码 / 登录表单有问题。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LOGIN_URL = os.environ.get("LOGIN_URL", "https://proxy-socks5.com/login")
PROXY_LIST_URL = os.environ.get("PROXY_LIST_URL", "https://proxy-socks5.com/proxy_list?page=1")
SITE_COOKIE = os.environ.get("SITE_COOKIE")  # 例如 "session=xxxx; other=yyy"
SITE_USERNAME = os.environ.get("SITE_USERNAME")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD")

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "proxies")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30

IP_PORT_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\s*[:：]\s*(\d{2,5})\b")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# 表头关键字 -> 输出字段名（同时兼容中英文表头）
COLUMN_ALIASES = {
    "type": ("type", "protocol", "类型"),
    "country": ("country", "地理信息", "地区", "位置"),
    "anonymity": ("anonymity", "匿名度", "匿名"),
    "added_at": ("last_checked", "last checked", "入库", "更新时间"),
}


def _headers():
    return {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


def apply_cookie(session: requests.Session, raw_cookie: str) -> bool:
    """
    把浏览器复制出来的原始 Cookie 字符串（如 "a=1; b=2"）灌进 session，
    然后请求代理列表页验证是否真的处于登录状态。
    """
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

    # 有的站点登录后会重定向，登录响应本身不含"退出登录"，再访问列表页确认一次
    check_resp = session.get(PROXY_LIST_URL, headers=_headers(), timeout=REQUEST_TIMEOUT)
    return "退出登录" in check_resp.text


def _match_column(header_cells, keywords):
    for i, h in enumerate(header_cells):
        if any(k in h for k in keywords):
            return i
    return None


def parse_table(html: str):
    soup = BeautifulSoup(html, "html.parser")
    proxies = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        ip_idx = _match_column(header_cells, ("ip",))
        if ip_idx is None:
            continue

        extra_idx = {}
        for field, keywords in COLUMN_ALIASES.items():
            idx = _match_column(header_cells, keywords)
            if idx is not None:
                extra_idx[field] = idx

        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if not cells:
                continue

            # 该站点的 IP 列本身就是 "ip:port"（有时还带类型徽标），
            # 所以统一用正则从整行文本里提取，比按下标取值更稳。
            m = IP_PORT_RE.search(" ".join(cells))
            if not m:
                continue
            ip, port = m.group(1), m.group(2)
            if not (IP_RE.match(ip) and port.isdigit()):
                continue

            entry = {"ip": ip, "port": port}
            for field, idx in extra_idx.items():
                if idx < len(cells) and cells[idx]:
                    entry[field] = cells[idx]

            proxies.append(entry)

        if proxies:
            return proxies

    # 兜底：整页纯文本正则扫描（注意：未登录时 IP 会被打码成 X，
    # 正则匹配不到，天然就是一个"是否登录成功"的信号）
    text = soup.get_text(" ")
    for m in IP_PORT_RE.finditer(text):
        proxies.append({"ip": m.group(1), "port": m.group(2)})

    return proxies


def dedupe(proxies):
    seen = set()
    result = []
    for p in proxies:
        key = f"{p['ip']}:{p['port']}"
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def write_outputs(proxies, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    payload = {
        "source": PROXY_LIST_URL,
        "scraped_at": now.isoformat(),
        "count": len(proxies),
        "proxies": proxies,
    }

    for prefix in (date_str, "latest"):
        json_path = os.path.join(output_dir, f"{prefix}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        txt_path = os.path.join(output_dir, f"{prefix}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            for p in proxies:
                f.write(f"{p['ip']}:{p['port']}\n")

    return os.path.join(output_dir, "latest.json"), os.path.join(output_dir, "latest.txt")


def main():
    session = requests.Session()

    if SITE_COOKIE:
        print("检测到 SITE_COOKIE，使用 Cookie 登录方式 ...")
        try:
            ok = apply_cookie(session, SITE_COOKIE)
        except requests.RequestException as e:
            print(f"ERROR: 用 Cookie 访问代理列表失败: {e}", file=sys.stderr)
            sys.exit(1)

        if not ok:
            print(
                "ERROR: Cookie 似乎已失效（响应里没有找到'退出登录'字样）。"
                "请重新登录网站，从浏览器 Network 面板复制最新的 Cookie 并更新 SITE_COOKIE。",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Cookie 有效，已登录。")

    elif SITE_USERNAME and SITE_PASSWORD:
        print(f"未设置 SITE_COOKIE，改用账号密码登录 {LOGIN_URL} ...")
        try:
            ok = login(session, LOGIN_URL, SITE_USERNAME, SITE_PASSWORD)
        except requests.RequestException as e:
            print(f"ERROR: 登录请求失败: {e}", file=sys.stderr)
            sys.exit(1)

        if not ok:
            print(
                "ERROR: 登录似乎失败了（响应里没有找到'退出登录'字样）。"
                "请检查账号密码，或登录表单结构是否变化。",
                file=sys.stderr,
            )
            sys.exit(1)
        print("登录成功。")

    else:
        print(
            "ERROR: 请设置 SITE_COOKIE（推荐），或同时设置 SITE_USERNAME 和 SITE_PASSWORD。",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"正在抓取 {PROXY_LIST_URL} ...")
    try:
        resp = session.get(PROXY_LIST_URL, headers=_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: 抓取代理列表失败: {e}", file=sys.stderr)
        sys.exit(1)

    proxies = dedupe(parse_table(resp.text))
    print(f"解析到 {len(proxies)} 条代理。")

    if not proxies:
        print(
            "WARNING: 未解析到任何代理。若确实已登录，IP 不应该被打码，"
            "多半是页面结构变化导致解析失败，请检查 HTML 并调整 "
            "parse_table() 的表头关键字；如果怀疑是登录/Cookie 失效，"
            "重新检查 SITE_COOKIE 或 SITE_USERNAME/SITE_PASSWORD。",
            file=sys.stderr,
        )

    latest_json, latest_txt = write_outputs(proxies, OUTPUT_DIR)
    print(f"已写入 {latest_json} 和 {latest_txt}")


if __name__ == "__main__":
    main()
