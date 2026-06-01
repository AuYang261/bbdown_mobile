"""BBDown worker — long-polls cloud server for tasks, executes BBDown, reports back."""
import os
import sys
import json
import time
import subprocess
import re
import logging
import glob as _glob
import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

CLOUD_URL = os.environ.get("CLOUD_URL", "http://127.0.0.1:5001")
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "")
BBDOWN_BIN = os.environ.get("BBDOWN_BIN", "BBDown")
BBDOWN_COOKIE_FILE = os.environ.get(
    "BBDOWN_COOKIE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bbdown_cookie.txt"),
)
WORK_DIR = os.environ.get(
    "WORK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads"),
)

os.makedirs(WORK_DIR, exist_ok=True)

HEADERS = {"Authorization": f"Bearer {SECRET_TOKEN}"}


def cookie_available() -> bool:
    return os.path.exists(BBDOWN_COOKIE_FILE) and os.path.getsize(BBDOWN_COOKIE_FILE) > 0


def make_cookie_args() -> list[str]:
    if cookie_available():
        with open(BBDOWN_COOKIE_FILE) as f:
            cookie = f.read().strip()
        if cookie:
            return ["-c", cookie]
    return []


def run_bbdown_download(task: dict):
    tid = task["id"]
    url = task["url"]
    mode = task.get("mode", "video")

    args = [BBDOWN_BIN, "-tv", url, "--work-dir", WORK_DIR]
    if mode == "audio":
        args.append("--audio-only")
    args.extend(make_cookie_args())

    logger.info(f"开始下载 {tid} {url} mode={mode}")
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, cwd=WORK_DIR,
    )

    last_title = ""
    last_progress = 0.0
    last_speed = ""
    output_lines: list[str] = []
    progress_re = re.compile(r"(\d+\.?\d*)%")
    speed_re = re.compile(r"(\d+\.?\d*\s*[KMGT]?B/s)")

    try:
        for line in proc.stdout:
            line = line.rstrip()
            output_lines.append(line)

            pm = progress_re.search(line)
            sm = speed_re.search(line)
            progress = float(pm.group(1)) / 100.0 if pm else last_progress
            speed = sm.group(1) if sm else last_speed

            if progress != last_progress or speed != last_speed:
                last_progress = progress
                last_speed = speed
                try:
                    requests.post(
                        f"{CLOUD_URL}/api/worker/progress/{tid}",
                        json={"title": last_title or url, "progress": progress, "speed": speed},
                        headers=HEADERS, timeout=10,
                    )
                except Exception as e:
                    logger.warning(f"上报进度失败: {e}")

        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}", json={"error": "下载超时"}, headers=HEADERS)
        logger.error(f"下载超时 {tid}")
        return

    if proc.returncode != 0:
        error_msg = "\n".join(output_lines[-10:]) if output_lines else "BBDown 返回非零退出码"
        requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}", json={"error": error_msg}, headers=HEADERS)
        logger.error(f"下载失败 {tid} code={proc.returncode}")
        return

    # Find downloaded file
    files = sorted(_glob.glob(os.path.join(WORK_DIR, "*")), key=os.path.getmtime, reverse=True)
    downloaded = None
    for f in files:
        if os.path.isfile(f) and not f.endswith(".txt") and not f.endswith(".config"):
            downloaded = f
            break

    if not downloaded:
        requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}", json={"error": "下载完成但找不到输出文件"}, headers=HEADERS)
        return

    fname = os.path.basename(downloaded)
    fsize_mb = os.path.getsize(downloaded) / 1024 / 1024
    logger.info(f"上传文件 {tid} {fname} ({fsize_mb:.1f}MB)")
    try:
        with open(downloaded, "rb") as f:
            resp = requests.post(
                f"{CLOUD_URL}/api/worker/complete/{tid}",
                files={"file": (fname, f)},
                headers=HEADERS,
                timeout=600,
            )
        if resp.ok:
            logger.info(f"上传完成 {tid}")
            os.remove(downloaded)
        else:
            raise Exception(f"Server returned {resp.status_code}")
    except Exception as e:
        logger.error(f"上传失败 {tid}: {e}")
        requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}", json={"error": f"上传失败: {e}"}, headers=HEADERS)


def run_bbdown_login(task: dict):
    tid = task["id"]
    logger.info(f"开始B站登录流程 {tid}")

    import base64
    import threading as _threading

    # Record existing files so we can detect new ones (e.g. QR PNG)
    existing_files = set(os.listdir(WORK_DIR))

    args = [BBDOWN_BIN, "login"]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    qr_sent = False
    qr_lock = _threading.Lock()
    output_all = ""
    qrcode_lines: list[str] = []
    in_qr = False

    # ------------------------------------------------------------------
    # helper: send QR to cloud server (idempotent — only first call wins)
    # ------------------------------------------------------------------
    def send_qr(qr_text: str = "", image_data: str = ""):
        nonlocal qr_sent
        with qr_lock:
            if qr_sent:
                return
            qr_sent = True
        payload: dict = {"qrcode": qr_text or "[QR图片]"}
        if image_data:
            payload["image"] = image_data
        try:
            requests.post(
                f"{CLOUD_URL}/api/worker/qrcode/{tid}",
                json=payload, headers=HEADERS, timeout=10,
            )
            logger.info(f"二维码已上报 {tid}")
        except Exception as e:
            logger.warning(f"上报二维码失败: {e}")

    # ------------------------------------------------------------------
    # background: read BBDown stdout (may contain block-char QR or nothing at all)
    # ------------------------------------------------------------------
    def read_stdout():
        nonlocal output_all, qrcode_lines, in_qr
        try:
            for line in proc.stdout:
                output_all += line
                with qr_lock:
                    if qr_sent:
                        continue
                if any(ch in line for ch in ("█", "▀", "▄", "▌", "▐", "░", "▒", "▓", "■", "□")):
                    in_qr = True
                    qrcode_lines.append(line.rstrip())
                elif in_qr and line.strip():
                    qrcode_lines.append(line.rstrip())
                elif in_qr and not line.strip():
                    if qrcode_lines:
                        send_qr(qr_text="\n".join(qrcode_lines))
                        qrcode_lines = []
                        in_qr = False
        except Exception:
            pass

    stdout_thread = _threading.Thread(target=read_stdout, daemon=True)
    stdout_thread.start()

    # ------------------------------------------------------------------
    # main loop: poll for new PNG QR file while BBDown waits for scan
    # ------------------------------------------------------------------
    deadline = time.time() + 120
    try:
        while proc.poll() is None and time.time() < deadline:
            if not qr_sent:
                try:
                    current = set(os.listdir(WORK_DIR))
                    for fname in sorted(current - existing_files):
                        if fname.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                            fpath = os.path.join(WORK_DIR, fname)
                            # Give BBDown a moment to finish writing
                            time.sleep(0.3)
                            with open(fpath, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("ascii")
                            ext = fname.rsplit(".", 1)[-1].lower()
                            mime = "png" if ext == "png" else "jpeg"
                            send_qr(image_data=f"data:image/{mime};base64,{b64}")
                            break
                except Exception as e:
                    logger.warning(f"检测二维码图片异常: {e}")
            time.sleep(1)

        if proc.poll() is None:
            proc.kill()
            requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}",
                          json={"error": "登录超时"}, headers=HEADERS)
            return
    except Exception:
        proc.kill()
        raise

    stdout_thread.join(timeout=5)

    # Flush any remaining text QR
    with qr_lock:
        if not qr_sent and qrcode_lines:
            send_qr(qr_text="\n".join(qrcode_lines))

    if proc.returncode == 0 and cookie_available():
        requests.post(f"{CLOUD_URL}/api/worker/login-success/{tid}", headers=HEADERS, timeout=10)
        logger.info("B站登录成功")
    else:
        tail = output_all[-200:] if output_all else "(无输出)"
        requests.post(f"{CLOUD_URL}/api/worker/fail/{tid}",
                      json={"error": f"登录失败: {tail}"}, headers=HEADERS)
        logger.error("B站登录失败")


def main():
    logger.info(f"Worker 启动, cloud={CLOUD_URL}, work_dir={WORK_DIR}")
    logger.info(f"BBDown cookie: {'可用' if cookie_available() else '不可用'}")

    consecutive_errors = 0

    while True:
        try:
            params = {"cookie_available": "true" if cookie_available() else "false"}
            resp = requests.get(
                f"{CLOUD_URL}/api/worker/poll",
                params=params,
                headers=HEADERS,
                timeout=90,
            )
            consecutive_errors = 0
            task = resp.json()

            if task.get("type") == "download":
                run_bbdown_download(task)
            elif task.get("type") == "login":
                run_bbdown_login(task)
            # "wait" type naturally loops back to poll
        except requests.exceptions.ReadTimeout:
            continue  # long poll timeout, re-poll
        except requests.exceptions.ConnectionError as e:
            consecutive_errors += 1
            wait = min(consecutive_errors * 5, 60)
            logger.warning(f"连接失败 ({e}), {wait}s 后重试")
            time.sleep(wait)
        except Exception as e:
            logger.error(f"Worker 异常: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
