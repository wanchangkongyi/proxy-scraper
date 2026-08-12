#!/usr/bin/env python3
"""
将 proxies/latest.txt 和 proxies/latest.json 上传（更新）到指定 Gist。

需要的环境变量 / GitHub Secrets：
  GIST_TOKEN  一个具有 'gist' 权限的 GitHub Personal Access Token
  GIST_ID     一个已存在的 Gist 的 id（先手动在 https://gist.github.com/ 创建一个，
              随便写点占位内容即可，之后由脚本持续更新）

用法（本地测试）：
  export GIST_TOKEN=xxxx
  export GIST_ID=xxxx
  python upload_gist.py
"""

import json
import os
import sys

import requests

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "proxies")
REQUEST_TIMEOUT = 30

# gist 中的文件名 -> 本地文件路径
FILES_TO_UPLOAD = {
    "proxies_latest.txt": os.path.join(OUTPUT_DIR, "latest.txt"),
    "proxies_latest.json": os.path.join(OUTPUT_DIR, "latest.json"),
}


def main():
    if not GIST_TOKEN or not GIST_ID:
        print(
            "ERROR: 请设置环境变量 / Secrets GIST_TOKEN 和 GIST_ID。",
            file=sys.stderr,
        )
        sys.exit(1)

    files_payload = {}
    for gist_filename, local_path in FILES_TO_UPLOAD.items():
        if not os.path.exists(local_path):
            print(f"WARNING: 未找到 {local_path}，跳过。", file=sys.stderr)
            continue
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            content = "# 本次运行未解析到任何代理\n"
        files_payload[gist_filename] = {"content": content}

    if not files_payload:
        print("ERROR: 没有可上传的文件。", file=sys.stderr)
        sys.exit(1)

    resp = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={
            "Authorization": f"token {GIST_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        data=json.dumps({"files": files_payload}),
        timeout=REQUEST_TIMEOUT,
    )

    if resp.status_code != 200:
        print(f"ERROR: 更新 Gist 失败 ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    print(f"Gist 已更新: {resp.json().get('html_url')}")


if __name__ == "__main__":
    main()
