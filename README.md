# proxy-scraper

每天通过 GitHub Actions 自动登录 [北极光代理](https://proxy-socks5.com/)，
抓取代理列表**第 1 页**（30 条），结果写入仓库 `proxies/` 目录，并同步更新到一个 GitHub Gist。

## 目录结构

```
.
├── scrape.py                     # 登录 + 抓取 + 解析 + 写文件
├── upload_gist.py                # 把最新结果同步到 Gist
├── requirements.txt
├── proxies/                      # 抓取结果输出目录（脚本自动生成）
│   ├── latest.txt                # ip:port 每行一条，始终是最新结果
│   ├── latest.json                # 结构化最新结果（含类型、地理信息、抓取时间等）
│   ├── 2026-08-12.txt             # 每日归档快照
│   └── 2026-08-12.json
└── .github/workflows/scrape.yml  # 定时任务
```

## 抓取逻辑说明

该网站未登录时会把 IP 打码（例如 `37.9.X.127`），登录后才显示完整 IP。
脚本支持两种登录方式，**优先使用 Cookie**：

- **方式 A：Cookie（推荐）** —— 设置 `SITE_COOKIE`，脚本直接把这个
  Cookie 灌进请求session，不走登录表单，最稳定、不受表单结构变化影响。
- **方式 B：账号密码** —— 未设置 `SITE_COOKIE` 时，用 `SITE_USERNAME` /
  `SITE_PASSWORD` 自动解析并提交登录页的 `<form>`（自动识别哪个输入框
  是用户名、哪个是密码，不需要写死字段名）。

登录（或 Cookie 验证）成功后，请求
`https://proxy-socks5.com/proxy_list?page=1`，解析表格，用正则从每一行
提取 `ip:port`（该站点 IP 列本身就是"类型 + ip:port"的组合文本，正则比
按列下标取值更稳），附加字段（类型 / 地理信息等）按表头关键字对齐。

**天然的登录状态自检**：如果 Cookie 过期或登录失败，页面上的 IP 仍然是
打码状态（带字母 `X`），正则无法匹配出合法 IP，最终 `proxies/latest.txt`
会是空的，脚本也会打印警告 —— 空结果基本就意味着没登录成功。

### 怎么拿 Cookie

1. 浏览器登录 https://proxy-socks5.com/ 。
2. 打开开发者工具 F12 → Network（网络）标签。
3. 刷新一下代理列表页，随便点开一个请求（比如 `proxy_list`）。
4. 在请求头（Request Headers）里找到 `Cookie:` 那一整行，复制冒号后面
   的完整内容（形如 `session=xxxx; other=yyy`）。
5. 存到 GitHub Secret `SITE_COOKIE` 里。

> 注意：Cookie 通常有过期时间（几天到几十天不等，取决于网站设置）。
> 如果某天脚本突然抓不到数据了，大概率是 Cookie 过期，重新登录复制一次
> 新的 Cookie、更新 Secret 即可。如果嫌手动更新麻烦，可以改用方式 B
> （账号密码），密码不会过期，缺点是依赖登录表单结构不变。

## 快速开始

### 1. 建仓库

把这些文件推到一个新的 GitHub 仓库（public 或 private 都可以）。

### 2. 创建一个用于存放结果的 Gist

去 https://gist.github.com/ 手动创建一个 Gist（内容随便写，比如 `placeholder`），
创建后从地址栏拿到 gist id，例如：

```
https://gist.github.com/your-name/1234567890abcdef1234567890abcdef
                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 这一段就是 GIST_ID
```

### 3. 创建 Gist 用的 Personal Access Token

GitHub → Settings → Developer settings → Personal access tokens：
- classic token：只勾选 `gist` 权限即可。
- fine-grained token：需要能访问 Gist 的写权限。

### 4. 配置仓库 Secrets

在你的仓库 Settings → Secrets and variables → Actions 里添加：

| Secret 名       | 值                                                    |
|-----------------|-------------------------------------------------------|
| `SITE_COOKIE`   | 登录后从浏览器复制的完整 Cookie（推荐，见上方说明）    |
| `SITE_USERNAME` | 备用方式：登录用户名（不用 Cookie 时才需要）           |
| `SITE_PASSWORD` | 备用方式：对应的密码（不用 Cookie 时才需要）           |
| `GIST_TOKEN`    | 第 3 步生成的 token                                    |
| `GIST_ID`       | 第 2 步拿到的 gist id                                  |

> 向仓库自身提交代码用的是 GitHub 自动提供的 `GITHUB_TOKEN`
> （已在 `permissions: contents: write` 里授权），不需要额外配置。
> 上面几个 secret 是另外单独配的凭据；`SITE_COOKIE` 和
> `SITE_USERNAME`/`SITE_PASSWORD` 只需二选一。

### 5. 触发运行

- 默认每天 UTC 02:00（北京时间约 10:00）自动运行，可在
  `.github/workflows/scrape.yml` 里修改 `cron` 表达式调整时间。
- 也可以在仓库 Actions 页面手动点击 "Run workflow" 立即测试。

## 本地测试

```bash
pip install -r requirements.txt

# 方式 A：Cookie（推荐）
export SITE_COOKIE="session=xxxx; other=yyy"

# 方式 B：账号密码（二选一，不需要两个都设）
# export SITE_USERNAME=your_username
# export SITE_PASSWORD=your_password

python scrape.py
cat proxies/latest.txt

# 测试上传 Gist（可选）
export GIST_TOKEN=xxxx
export GIST_ID=xxxx
python upload_gist.py
```

## 如果抓取结果为空

按下面顺序排查：

1. **先确认 Cookie 没过期**：自己在浏览器里手动访问代理列表页，
   看是否还是登录状态；如果需要重新登录，说明 Cookie 已失效，
   重新登录复制新的 Cookie 更新 Secret。
2. **（用账号密码方式时）登录表单是否变了**：如果网站改版导致自动
   识别用户名/密码字段失败，运行时会在日志里报错
   `未能自动识别用户名/密码输入框`，此时需要打开登录页查看源代码
   （浏览器里 `Ctrl+U` 或右键"查看网页源代码"），找到 `<form>` 里两个
   `<input>` 的 `name` 属性，告知开发者手动指定，或者直接修改
   `scrape.py` 里 `login()` 函数硬编码字段名。
3. **表格结构是否变了**：如果确认已登录但依然没解析到数据，说明
   `proxy_list` 页面的表格结构变了，需要打开页面查看实际 HTML，
   调整 `scrape.py` 里 `parse_table()` 的表头关键字（`COLUMN_ALIASES`）。

## 免责声明

抓取到的是该网站提供的代理，稳定性和安全性无法保证，请自行甄别用途，
遵守目标网站的服务条款及当地法律法规，仅用于合法用途，不要公开分享
需要付费/会员权限才能查看的数据。
