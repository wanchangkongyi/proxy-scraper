# proxy-scraper

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

## 免责声明

抓取到的是北极光网站提供的代理，稳定性和安全性无法保证，请自行甄别用途，遵守目标网站的服务条款及当地法律法规，仅用于合法用途。
