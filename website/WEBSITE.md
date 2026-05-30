# OfficeLego 产品官网（可被搜索到的介绍站）

`website/` 目录是**纯静态**产品介绍页，给投资人、用户、搜索引擎用。  
与 `python main.py --web` 的**本地控制面板**无关——后者仍须在本机运行。

---

## 本地预览

```bash
cd website
python3 -m http.server 8080
```

浏览器打开 http://127.0.0.1:8080

- 中文版：`index.html`
- 英文版：`index-en.html`
- 导航栏 **中文 | EN** 切换，会记住选择（下次自动打开对应语言）

---

## 发布到公网（任选一种）

### 1. GitHub Pages（免费）

1. 把仓库推到 GitHub（可新建 `officelego` 仓库）。
2. 仓库 **Settings → Pages → Build and deployment**：
   - Source: **Deploy from a branch**
   - Branch: `main`，文件夹 **`/website`**（若 GitHub 只支持 `/root` 或 `/docs`，见下条）。
3. 若只能选 `/docs`：把 `website/*` 复制到 `docs/`，或改 Pages 为 GitHub Actions 部署 `website` 目录。
4. 得到地址：`https://你的用户名.github.io/仓库名/`
5. **自定义域名**（可选）：买 `officelego.app`，DNS CNAME 到 `xxx.github.io`，并在仓库放 `website/CNAME` 文件，内容一行：`officelego.app`
6. 把 `index.html` 里 `canonical`、`sitemap.xml` 的 `https://officelego.app` 改成你的真实域名。

### 2. Cloudflare Pages（免费 HTTPS）

1. [Cloudflare Dashboard](https://dash.cloudflare.com) → Pages → Create project → 连接 GitHub。
2. Build command: 留空；Output directory: `website`。
3. 绑定自定义域名。

### 3. Vercel / Netlify

- Root directory: `website`
- 无需构建命令

---

## SEO 上线检查清单

- [x] 联系邮箱：iamliuqichen@icloud.com
- [ ] 将下载链接 `#download` 中的 `github.com` 换成 Releases 真实地址
- [ ] 更新 `canonical`、`sitemap.xml`、`robots.txt` 里的域名为正式域名
- [ ] 在 Google [Search Console](https://search.google.com/search-console) 提交 sitemap
- [ ] 百度/Google 搜索「OfficeLego」前，确保页面标题含品牌词

---

## 与控制面板的关系

| 站点 | 用途 |
|------|------|
| `website/` 静态页 | 产品介绍、投资叙事、下载引导 |
| `python main.py --web` | 本机录制/回放控制台 |
| `DEPLOY.md` | 如何把控制台暴露给远程同事 |

投资人看到的应是 **官网**；员工日常用的是 **桌面版或本机 Web 控制台**。
