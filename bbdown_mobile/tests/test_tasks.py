import sys
import time
sys.path.insert(0, '.')
from tasks import TaskQueue


def test_add_download_task():
    tq = TaskQueue()
    tid = tq.add_download(url="BV123", mode="audio", username="alice")
    task = tq.get(tid)
    assert task is not None
    assert task["type"] == "download"
    assert task["url"] == "BV123"
    assert task["mode"] == "audio"
    assert task["username"] == "alice"
    assert task["status"] == "pending"


def test_add_login_task():
    tq = TaskQueue()
    tid = tq.add_login()
    task = tq.get(tid)
    assert task["type"] == "login"
    assert task["status"] == "pending"


def test_pop_pending_returns_oldest():
    tq = TaskQueue()
    tid1 = tq.add_download(url="BV1", mode="audio", username="a")
    time.sleep(0.01)
    tid2 = tq.add_download(url="BV2", mode="video", username="b")
    popped = tq.pop_pending()
    assert popped["id"] == tid1


def test_pop_pending_returns_none_when_empty():
    tq = TaskQueue()
    assert tq.pop_pending() is None


def test_update_task():
    tq = TaskQueue()
    tid = tq.add_download(url="BV123", mode="audio", username="a")
    tq.update(tid, status="downloading", title="Test Video", progress=0.5, speed="2 MB/s")
    task = tq.get(tid)
    assert task["status"] == "downloading"
    assert task["title"] == "Test Video"
    assert task["progress"] == 0.5


def test_list_all():
    tq = TaskQueue()
    tq.add_download(url="BV1", mode="audio", username="a")
    tq.add_download(url="BV2", mode="video", username="b")
    assert len(tq.list_all()) == 2


def test_pending_count():
    tq = TaskQueue()
    tq.add_download(url="BV1", mode="audio", username="a")
    assert tq.pending_count() == 1
    tq.pop_pending()
    assert tq.pending_count() == 0
