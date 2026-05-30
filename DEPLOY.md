# OfficeLego 公网部署说明

OfficeLego 的**录制和回放**必须在安装了 macOS（或 Windows）的那台电脑上执行，需要系统「辅助功能」权限。  
普通 Linux 云服务器（Vercel、Render 等）**不能**代替你的 Mac 去点击 WPS / Excel / Gmail。

公网网站的正确用法是：**在你自己的 Mac 上跑服务，再把网页暴露到公网**（你自己或同事用浏览器远程操作这台 Mac 上的自动化）。

---

## 方式一：Cloudflare Tunnel（推荐，免费 HTTPS）

1. 在本机安装依赖并设置访问令牌：

```bash
pip install -r requirements.txt
export OFFICELEGO_AUTH_TOKEN="$(openssl rand -hex 16)"
echo "Token: $OFFICELEGO_AUTH_TOKEN"   # 发给需要访问的人
```

2. 启动公网模式（监听所有网卡，必须带令牌）：

```bash
python main.py --web --public --no-browser
```

3. 另开一个终端，把本地端口暴露到公网：

```bash
chmod +x scripts/public_tunnel.sh
./scripts/public_tunnel.sh 5757
```

终端里会出现 `https://xxxx.trycloudflare.com` 地址，用浏览器打开，在登录页粘贴上面的 **Token**。

4. 在本机 Mac 上授予 Terminal / Python「辅助功能」和「输入监控」权限。

---

## 方式二：局域网 / 公网 IP（路由器端口转发）

```bash
export OFFICELEGO_AUTH_TOKEN="your-long-secret"
python main.py --web --public --port 5757 --no-browser
```

- 同事访问：`http://你的局域网IP:5757` 或路由器映射后的公网 IP  
- **务必**设置 `OFFICELEGO_AUTH_TOKEN`，否则任何人都能控制你的电脑  

---

## 方式三：生产进程（Mac 上常驻）

```bash
export OFFICELEGO_AUTH_TOKEN="..."
export OFFICELEGO_HOST=0.0.0.0
export OFFICELEGO_PORT=5757
export OFFICELEGO_PUBLIC=1
pip install waitress
waitress-serve --listen=0.0.0.0:5757 'web_app:application'
```

需要先设置环境变量并确保 `web_app.application` 可用（见 `web_app.py`）。

---

## 环境变量

| 变量 | 说明 |
|------|------|
| `OFFICELEGO_AUTH_TOKEN` | API 访问令牌（公网模式强烈必填） |
| `OFFICELEGO_PUBLIC=1` | 等同 `--public` |
| `OFFICELEGO_HOST` | 默认公网 `0.0.0.0`，本地 `127.0.0.1` |
| `OFFICELEGO_PORT` | 端口，默认 `5757` |
| `OFFICELEGO_BASE_URL` | 可选，对外显示的完整 URL（元数据用） |

---

## 不能把什么部署到纯云端？

- 不能把「录制鼠标键盘」部署到 **无桌面的 Linux Docker** 并期望控制你家里的 WPS。  
- 若需要团队共用，每台操作员各自 Mac 跑 `python main.py --web --public` + Tunnel，或一台专用 Mac 作为自动化服务器。

---

## 桌面版（不暴露公网）

```bash
python main.py          # Tk 图形界面
python main.py --web    # 仅本机 http://127.0.0.1:5757
```
