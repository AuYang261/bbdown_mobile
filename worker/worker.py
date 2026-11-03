"""BBDown worker — long-polls cloud server for tasks, executes BBDown, reports back."""

import os
import sys
import shutil
import time
import subprocess
import re
import logging
from urllib.parse import parse_qs, urlsplit
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
WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# Path to the admin/template BBDown binary — copied into each user's directory
script_dir = os.path.dirname(os.path.abspath(__file__))
BBDOWN_SOURCE = os.environ.get("BBDOWN_SOURCE", os.path.join(script_dir, "BBDown"))

os.makedirs(WORK_DIR, exist_ok=True)

HEADERS = {"Authorization": f"Bearer {SECRET_TOKEN}"}

# Known media extensions BBDown can produce
MEDIA_EXTENSIONS = {
    ".mp4", ".m4a", ".mkv", ".flv", ".mp3", ".aac",
    ".wav", ".webm", ".mov", ".ts", ".avi", ".wmv", ".flac",
}


class MultipleMediaFilesError(RuntimeError):
    """Raised when a single-file task produced a collection of media files."""


def user_dir(username: str) -> str:
    """Return per-user directory, creating it if needed."""
    d = os.path.join(WORK_DIR, username)
    os.makedirs(d, exist_ok=True)
    return d


def ensure_user_bbdown(username: str) -> str:
    """Copy the BBDown binary into *username*'s directory if missing.
    Returns the path to the user's BBDown binary.
    """
    ud = user_dir(username)
    dest = os.path.join(ud, "BBDown")
    if not os.path.exists(dest):
        if not os.path.exists(BBDOWN_SOURCE):
            raise FileNotFoundError(
                f"BBDown source binary not found: {BBDOWN_SOURCE} related to ({os.getcwd()}). "
                f"Place the BBDown binary there or set BBDOWN_SOURCE env var."
            )
        shutil.copy2(BBDOWN_SOURCE, dest)
        os.chmod(dest, 0o755)
        logger.info(f"复制 BBDown → {username}/ ({dest})")
    return dest


def cookie_available_for(username: str) -> bool:
    """Check if a specific user has BBDown.data."""
    data = os.path.join(user_dir(username), "BBDown.data")
    return os.path.exists(data) and os.path.getsize(data) > 0


def scan_logged_in_users() -> list[str]:
    """Return list of usernames who have a valid BBDown.data."""
    users: list[str] = []
    try:
        for name in os.listdir(WORK_DIR):
            ud = os.path.join(WORK_DIR, name)
            if not os.path.isdir(ud):
                continue
            data = os.path.join(ud, "BBDown.data")
            if os.path.exists(data) and os.path.getsize(data) > 0:
                users.append(name)
    except Exception:
        pass
    return users


# ==========================================================================
#  download helpers
# ==========================================================================

def _execute_bbdown(args: list[str], cwd: str, tid: str, url: str):
    """Run BBDown, streaming progress to cloud. Returns (returncode, output_lines).
    returncode is None when the process timed out (killed by us)."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
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
                        json={
                            "title": last_title or url,
                            "progress": progress,
                            "speed": speed,
                        },
                        headers=HEADERS,
                        timeout=10,
                    )
                except Exception as e:
                    logger.warning(f"上报进度失败: {e}")

        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        return None, output_lines

    return proc.returncode, output_lines


def _resolve_download_url(url: str) -> str:
    """Resolve B站 share links so a selected page in the final URL is retained."""
    host = (urlsplit(url).hostname or "").lower()
    if host not in {"b23.tv", "bili2233.cn"}:
        return url

    try:
        with requests.get(
            url,
            allow_redirects=True,
            stream=True,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as response:
            response.raise_for_status()
            return response.url
    except requests.RequestException as e:
        logger.warning(f"解析短链接失败，继续使用原链接: {e}")
        return url


def _build_bbdown_args(
    bbdown: str,
    url: str,
    mode: str,
    *,
    use_tv: bool,
    resolved_url: str | None = None,
) -> list[str]:
    """Build BBDown arguments for the exact page selected in the browser URL."""
    selected_url = resolved_url or _resolve_download_url(url)
    page = parse_qs(urlsplit(selected_url).query).get("p", ["1"])[0]
    if page.upper() in {"ALL", "LAST", "LATEST"}:
        page = page.upper()
    elif not page.isdigit() or int(page) < 1:
        page = "1"

    args = [bbdown]
    if use_tv:
        args.append("-tv")
    args.extend(["-p", page, url])
    if mode == "audio":
        args.append("--audio-only")
    return args


def _pick_file_from_dir(directory: str) -> str | None:
    """Return a media file found in *directory* (expected to be a per-task temp dir)."""
    media_files = []
    fallback_files = []
    try:
        for root, _, files in os.walk(directory):
            for name in files:
                fp = os.path.join(root, name)
                if os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS:
                    media_files.append(fp)
                elif "BBDown" not in name:
                    fallback_files.append(fp)
    except Exception:
        return None

    for files in (media_files, fallback_files):
        if files:
            if len(files) > 1:
                raise MultipleMediaFilesError(
                    f"本次下载生成 {len(files)} 个文件，当前任务只能上传一个；"
                    "请使用带 p= 参数的单集链接"
                )
            return max(files, key=os.path.getsize)

    return None


# ==========================================================================
#  download
# ==========================================================================
def run_bbdown_download(task: dict):
    tid = task["id"]
    url = task["url"]
    mode = task.get("mode", "video")
    username = task.get("username", "unknown")

    ud = user_dir(username)
    bbdown = ensure_user_bbdown(username)

    # Per-task temp directory — isolates each download completely.
    # BBDown writes output to cwd, BBDown.data is alongside the binary in ud.
    task_dir = os.path.join(ud, tid)
    os.makedirs(task_dir, exist_ok=True)
    resolved_url = _resolve_download_url(url)

    try:
        # ---- Attempt 1: with -tv (TV API) ----
        args = _build_bbdown_args(
            bbdown, url, mode, use_tv=True, resolved_url=resolved_url
        )

        logger.info(f"开始下载 {tid} user={username} url={url} mode={mode} (try -tv)")
        rc, output_lines = _execute_bbdown(args, task_dir, tid, url)

        # ---- Timeout on first try ----
        if rc is None:
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": "下载超时"},
                headers=HEADERS,
            )
            logger.error(f"下载超时 {tid}")
            return

        try:
            downloaded = _pick_file_from_dir(task_dir)
        except MultipleMediaFilesError as e:
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": str(e)},
                headers=HEADERS,
            )
            logger.error(f"下载失败 {tid} — {e}")
            return

        # ---- Attempt 2: fallback without -tv ----
        # BBDown may exit 0 even when -tv fails on unsupported videos,
        # so we check whether a file actually appeared.
        if not downloaded:
            logger.warning(f"-tv 未生成下载文件 {tid} (exit={rc})，回退不带 -tv 重试")
            args = _build_bbdown_args(
                bbdown, url, mode, use_tv=False, resolved_url=resolved_url
            )
            rc, output_lines = _execute_bbdown(args, task_dir, tid, url)

            if rc is None:
                requests.post(
                    f"{CLOUD_URL}/api/worker/fail/{tid}",
                    json={"error": "下载超时"},
                    headers=HEADERS,
                )
                logger.error(f"重试下载超时 {tid}")
                return

            try:
                downloaded = _pick_file_from_dir(task_dir)
            except MultipleMediaFilesError as e:
                requests.post(
                    f"{CLOUD_URL}/api/worker/fail/{tid}",
                    json={"error": str(e)},
                    headers=HEADERS,
                )
                logger.error(f"下载失败 {tid} — {e}")
                return

        # ---- Final failure (both attempts produced no file) ----
        if not downloaded:
            error_msg = (
                "\n".join(output_lines[-10:]) if output_lines else "下载完成但未生成文件"
            )
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": error_msg},
                headers=HEADERS,
            )
            logger.error(f"下载失败 {tid} — 未生成文件")
            return

        # ---- Upload downloaded file ----
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
            else:
                raise Exception(f"Server returned {resp.status_code}")
        except Exception as e:
            logger.error(f"上传失败 {tid}: {e}")
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": f"上传失败: {e}"},
                headers=HEADERS,
            )
    finally:
        # Always clean up the per-task temp directory
        shutil.rmtree(task_dir, ignore_errors=True)


# ==========================================================================
#  login
# ==========================================================================
def run_bbdown_login(task: dict):
    """Start B站 login in a background thread — non-blocking for the worker."""
    import base64
    import threading as _threading

    tid = task["id"]
    username = task.get("username", "unknown")

    def _login_thread():
        logger.info(f"开始B站登录流程 {tid} user={username}")

        ud = user_dir(username)
        bbdown = ensure_user_bbdown(username)
        watch_dir = ud  # only watch the user's own directory

        proc = subprocess.Popen(
            [bbdown, "login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=ud,
        )

        qr_sent = False

        # ---- Phase 1: wait for qrcode.png ----
        qr_deadline = time.time() + 120
        while not qr_sent and proc.poll() is None and time.time() < qr_deadline:
            fpath = os.path.join(watch_dir, "qrcode.png")
            if os.path.isfile(fpath):
                try:
                    time.sleep(0.3)
                    with open(fpath, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    requests.post(
                        f"{CLOUD_URL}/api/worker/qrcode/{tid}",
                        json={
                            "qrcode": "[QR图片]",
                            "image": f"data:image/png;base64,{b64}",
                        },
                        headers=HEADERS,
                        timeout=10,
                    )
                    os.remove(fpath)
                    qr_sent = True
                    logger.info(f"二维码已上报并删除 {tid}")
                    break
                except Exception as e:
                    logger.warning(f"处理二维码失败: {e}")
            time.sleep(1)

        if not qr_sent:
            proc.kill()
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": "等待二维码超时"},
                headers=HEADERS,
            )
            logger.error(f"二维码超时 {tid}")
            return

        # ---- Phase 2: wait for user to scan ----
        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": "登录超时（扫码超时）"},
                headers=HEADERS,
            )
            logger.error(f"登录超时 {tid}")
            return

        if proc.returncode == 0 and cookie_available_for(username):
            requests.post(
                f"{CLOUD_URL}/api/worker/login-success/{tid}",
                headers=HEADERS,
                timeout=10,
            )
            logger.info(f"B站登录成功 {tid} user={username}")
        else:
            requests.post(
                f"{CLOUD_URL}/api/worker/fail/{tid}",
                json={"error": f"登录失败，退出码 {proc.returncode}"},
                headers=HEADERS,
            )
            logger.error(f"B站登录失败 {tid} user={username} exit={proc.returncode}")

    t = _threading.Thread(target=_login_thread, daemon=True)
    t.start()


# ==========================================================================
#  main loop
# ==========================================================================
def main():
    logger.info(f"Worker 启动, cloud={CLOUD_URL}, work_dir={WORK_DIR}")
    logger.info(f"BBDown source: {BBDOWN_SOURCE}")

    consecutive_errors = 0

    while True:
        try:
            params = {"logged_in_users": ",".join(scan_logged_in_users())}
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
            elif task.get("type") == "bilibili_logout":
                username = task.get("username", "")
                if username:
                    data_file = os.path.join(user_dir(username), "BBDown.data")
                    if os.path.exists(data_file):
                        os.remove(data_file)
                        logger.info(f"已删除 BBDown.data user={username}")
                else:
                    logger.warning("bilibili_logout task missing username")
            # "wait" type naturally loops back to poll
        except requests.exceptions.ReadTimeout:
            continue
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
