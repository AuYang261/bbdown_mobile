# BBDown Mobile

手机浏览器访问的 B站 视频/音频下载工具。在 B站 App 复制链接 → 粘贴到网页 → 服务器下载 → 保存到手机。

## 架构

```
手机浏览器 ──HTTPS──▶ 云服务器 (Flask) ──长轮询──▶ 内网服务器 (BBDown + ffmpeg)
```

- **云服务器**（2C4G 即可）：提供网页、接收任务、中转文件，无需 ffmpeg
- **内网服务器**（高性能）：执行 BBDown 下载 + ffmpeg 合成，上传结果

## 快速开始

### 云服务器

```bash
vim deploy/start-server.sh   # 修改脚本顶部的用户名、密码、密钥
./deploy/start-server.sh
```

### 内网 Worker

```bash
vim deploy/start-worker.sh   # 修改脚本顶部的域名、密钥
./deploy/start-worker.sh
```

### 停止

```bash
./deploy/stop.sh
```

## 使用

1. 手机浏览器打开 `https://your-domain.com`
2. 登录（管理员可管理其他用户）
3. 在 B站 App 中搜索 → 复制链接 → 粘贴到网页 → 选音频/视频 → 下载
4. 下载完成后点「保存文件」存到手机

> 详细部署指南见 [deploy/README.md](deploy/README.md)
