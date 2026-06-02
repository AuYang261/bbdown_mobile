# BBDown Mobile 部署指南

## 云服务器部署 (2C4G Ubuntu)

### 1. 安装依赖
```bash
sudo apt update && sudo apt install -y python3 python3-pip nginx certbot python3-certbot-nginx ffmpeg

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.cargo/env

# Clone & install
cd /opt
git clone <your-repo-url> bbdown_mobile
cd bbdown_mobile/bbdown_mobile
uv sync
```

### 2. 配置
```bash
cd /opt/bbdown_mobile/bbdown_mobile
uv sync

# 修改start-worker.sh
export ADMIN_USERNAME="<管理员用户名>"
export ADMIN_PASSWORD="<管理员密码>"
export APP_SESSION_SECRET="<随机字符串，至少32字符>"
export SECRET_TOKEN="<与 Worker 约定的一致>"
export PORT="5001"
```

### 3. Nginx + HTTPS
```bash
# 获取SSL证书 (需要域名已解析到本机)
sudo certbot --nginx -d your-domain.com

# 复制nginx配置
sudo cp ../deploy/nginx-bbdown.conf /etc/nginx/sites-available/bbdown
sudo nano /etc/nginx/sites-available/bbdown  # 修改 server_name
sudo ln -sf /etc/nginx/sites-available/bbdown /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 4. 启动

```bash
./start-server.sh
```

或通过 systemd:
```ini
# /etc/systemd/system/bbdown.service
[Unit]
Description=BBDown Mobile Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/bbdown_mobile/bbdown_mobile
EnvironmentFile=/opt/bbdown_mobile/bbdown_mobile/.env
ExecStart=/root/.cargo/bin/uv run python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bbdown
```

---

## 内网服务器部署 (高性能)

### 1. 准备
- 下载 BBDown: https://github.com/nilaoda/BBDown/releases (选 linux-x64)
- 安装 ffmpeg: `sudo apt install -y ffmpeg`

### 2. 配置
```bash
cd /opt/bbdown_mobile/worker
uv sync

# 修改start-worker.sh
export CLOUD_URL=https://your-domain.com
export SECRET_TOKEN=<same-as-cloud-server>
export BBDOWN_SOURCE=./BBDown   # BBDown 二进制(相对于worker/目录)
```

### 3. 提前放好 BBDown 模板
```bash
# 把 BBDown 可执行文件放到 worker/ 目录
cp /path/to/BBDown worker/
chmod +x worker/BBDown
```

### 4. 启动 Worker
```bash
./start-worker.sh
```

或通过 systemd:
```ini
[Unit]
Description=BBDown Worker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bbdown_mobile/worker
Environment="CLOUD_URL=https://your-domain.com"
Environment="SECRET_TOKEN=<token>"
Environment="BBDOWN_SOURCE=/opt/bbdown_mobile/worker/BBDown"
ExecStart=/root/.cargo/bin/uv run python worker.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 环境变量参考

### 云服务器
| 变量 | 必须 | 说明 |
|---|---|---|
| ADMIN_USERNAME | 是 | 管理员用户名 |
| ADMIN_PASSWORD | 是 | 管理员密码 |
| APP_SESSION_SECRET | 是 | Session签名密钥 (≥32字符) |
| SECRET_TOKEN | 是 | Worker认证token |

### 内网 Worker
| 变量 | 必须 | 说明 |
|---|---|---|
| CLOUD_URL | 是 | 云服务器地址 (含https://) |
| SECRET_TOKEN | 是 | 与云服务器一致 |
| BBDOWN_SOURCE | 否 | BBDown模板二进制 (默认 worker/BBDown)，worker会按用户复制 |


---

## 故障排查

- **无法访问**: 检查 nginx 状态 `systemctl status nginx`，证书 `certbot certificates`
- **Worker连接失败**: 检查 CLOUD_URL 和 SECRET_TOKEN 是否与云服务器一致
- **下载失败**: 检查内网服务器是否能访问外网，BBDown 版本是否兼容
- **端口占用**: `lsof -ti:5001 | xargs kill`
