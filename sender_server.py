"""B站弹幕同传助手 —— 本地小服务

监听 LiveTranslate 的转录文件（transcripts/*_translation.txt），
把新出现的译文排队，供浏览器里的脚本（油猴 / F12 控制台）取用。

transcript_dir 留空时自动搜索 LiveTranslate 的 transcripts 目录；
也可以由 config.json 或 --transcript-dir 手动指定。

只依赖 Python 标准库。默认监听 127.0.0.1:8770，仅本机可访问。

启动后只会处理"启动之后新写入"的译文，不会补发历史记录。
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"

DEFAULT_CONFIG = {
    "port": 8770,
    # 留空 = 自动搜索 LiveTranslate 的 transcripts 目录；也可以填绝对路径。
    "transcript_dir": "",
    "prefix": "【",
    "suffix": "】",
    # B站上限是 80 个「字符」，而一个汉字/全角标点算 2 字符 → 实际只有 40 字。
    # 含【】后正文最多 38 字。设 0 = 完全不限（会被B站截断）
    "max_length": 40,
    "min_length": 2,
    "strip_period": True,  # 删掉译文末尾的句号（句中句号与其他标点保留）
    "split_interval": 2.0,  # 超长译文分段的发送间隔（秒）
    "stale_seconds": 60,
    "dedupe_seconds": 15,
    "poll_interval": 0.5,
}

# [21:35:33] 车坏了，糟透了。
LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.+?)\s*$")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[warn] config.json 读取失败，使用默认配置: {e}", flush=True)
    return cfg


# 自动搜索 LiveTranslate 时跳过这些目录，避免扫 Windows / 模型 / 缓存。
SKIP_DIR_NAMES = {
    "$recycle.bin",
    ".git",
    ".venv",
    "__pycache__",
    "appdata",
    "models",
    "node_modules",
    "site-packages",
    "system volume information",
    "temp",
    "venv",
    "windows",
    "windowsapps",
    "winsxs",
}
TRANSCRIPT_GLOB = "*_translation.txt"


def _max_translation_mtime(directory: Path) -> float:
    """目录里最新译文文件的修改时间；没有译文返回 0。"""
    try:
        files = list(Path(directory).glob(TRANSCRIPT_GLOB))
    except OSError:
        return 0.0
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return newest


def _search_roots() -> list[Path]:
    """常见安装位置 + 所有盘符根目录；去重后返回。"""
    home = Path.home()
    roots = [
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "OneDrive",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Documents",
        Path.cwd(),
    ]
    for key in ("LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{drive}:/")
        try:
            if root.exists():
                roots.append(root)
        except OSError:
            pass

    unique = []
    seen = set()
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _common_candidates(roots: list[Path]):
    """先看最常见的 LiveTranslate/LiveTranslate/transcripts 结构。"""
    names = ("LiveTranslate", "livetranslate", "live_translate")
    subdirs = (
        "",
        "Program Files",
        "Program Files (x86)",
        "Programs",
        "Apps",
        "Tools",
        "Desktop",
        "Documents",
        "Downloads",
        "OneDrive",
        "OneDrive/Desktop",
        "OneDrive/Documents",
    )
    for root in roots:
        for sub in subdirs:
            base = root if not sub else root / sub
            for name in names:
                yield base / name / "transcripts"


def _scan_root(root: Path, max_depth: int = 3, deadline: float | None = None):
    """浅层扫描，找名字叫 transcripts 且里面有 *_translation.txt 的目录。"""
    stack = [(Path(root), 0)]
    while stack:
        if deadline is not None and time.monotonic() > deadline:
            return
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    name = entry.name.lower()
                    if name in SKIP_DIR_NAMES:
                        continue
                    path = Path(entry.path)
                    if name == "transcripts":
                        if _max_translation_mtime(path) > 0:
                            yield path
                        continue
                    if depth < max_depth:
                        stack.append((path, depth + 1))
        except OSError:
            continue


def detect_transcript_dir(
    roots: list[Path] | None = None,
    timeout: float = 8.0,
) -> Path | None:
    """返回最近有译文写入的 transcripts 目录；找不到返回 None。"""
    roots = list(roots) if roots is not None else _search_roots()

    best = None
    best_mtime = 0.0
    for path in _common_candidates(roots):
        mtime = _max_translation_mtime(path)
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    if best is not None:
        return best

    deadline = time.monotonic() + max(0.5, timeout)
    for root in roots:
        try:
            if not root.exists():
                continue
        except OSError:
            continue
        for path in _scan_root(root, max_depth=3, deadline=deadline):
            mtime = _max_translation_mtime(path)
            if mtime > best_mtime:
                best, best_mtime = path, mtime
        if time.monotonic() > deadline:
            break
    return best


def resolve_transcript_dir(
    cfg: dict,
    cli_path: str | None = None,
    roots: list[Path] | None = None,
    timeout: float = 8.0,
) -> Path | None:
    """优先用命令行/配置里的目录；不存在时自动搜索。"""
    for raw in (cli_path, (cfg or {}).get("transcript_dir")):
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text)
        try:
            if path.is_dir():
                return path
        except OSError:
            pass
    return detect_transcript_dir(roots=roots, timeout=timeout)


# 末尾句号：只删结尾，句中的保留。
# 刻意不含半角「.」——那会把「等等...」这种省略号也一起删掉。
TRAILING_PERIODS = "。．"


def strip_trailing_period(text: str) -> str:
    """删掉末尾的句号（。／．）。句中的句号、感叹号、问号、逗号、省略号都不动。"""
    return text.rstrip(TRAILING_PERIODS).rstrip()


# 超长译文断句用的标点：优先句末标点，其次逗号类，都没有就硬切。
SPLIT_STRONG = "。！？!?；;…"
SPLIT_WEAK = "，,、"
# 标点后面紧跟的收尾符号，跟着前一段走（避免下一段以「」』开头）
CLOSERS = '」』）】》〉”’"\''


def _find_cut(text: str, budget: int) -> int:
    """在 text[:budget] 里找切点，返回切点下标（标点留在前一段）。"""
    window = text[:budget]
    for puncts in (SPLIT_STRONG, SPLIT_WEAK):
        idx = max(window.rfind(p) for p in puncts)
        if idx >= 0:
            cut = idx + 1
            while cut < len(text) and text[cut] in CLOSERS:
                cut += 1
            return cut
    return budget


def format_texts(cfg: dict, text: str):
    """加括号、超长时按标点断句。返回 list[str]；空列表表示这条不发。

    每段加上前后缀后都不超过 max_length。max_length=0 时不分段。
    """
    t = text.strip()
    if not t or len(t) < cfg["min_length"]:
        return []
    # 先过完长度门槛再剥句号：不改动"哪些译文会被发送"，只改发出的样子
    if cfg.get("strip_period", True):
        t = strip_trailing_period(t)
        if not t:
            return []
    prefix, suffix = cfg["prefix"], cfg["suffix"]
    maxlen = cfg["max_length"]
    budget = maxlen - len(prefix) - len(suffix) if maxlen else 0
    if not maxlen or budget < 1 or len(t) <= budget:
        return [prefix + t + suffix]

    parts = []
    rest = t
    while len(rest) > budget:
        cut = _find_cut(rest, budget)
        if cut <= 0:
            break
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return [prefix + p + suffix for p in parts]


class Queue:
    """待发送队列 + 统计。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._items = []  # [{"id","text","ts","batch","acked"}]
        self._next_id = 1
        self._next_batch = 1
        self._last_text = None
        self._last_text_ts = 0.0
        self.paused = False
        self._paused_latest = None  # 暂停期间最新一条的格式化结果（list[str]）
        self.stats = {"received": 0, "acked": 0, "dropped_stale": 0,
                      "dropped_dup": 0, "dropped_short": 0,
                      "dropped_paused": 0}
        self.last_sent = None  # 最近一条被 ack 的内容（给状态面板看）

    def _enqueue_locked(self, texts, now: float):
        """把一条译文（可能已断成多段）放进队列。调用方必须持锁。"""
        batch = self._next_batch
        self._next_batch += 1
        prev_id = None
        for i, text in enumerate(texts):
            self._items.append({
                "id": self._next_id,
                "text": text,
                "ts": now,
                # 第一段立刻可发；后续段落等上一段真正发完，再等 gap 秒
                "not_before": now if i == 0 else float("inf"),
                "after": prev_id,
                "batch": batch,
                "acked": False,
            })
            prev_id = self._next_id
            self._next_id += 1
        self.stats["received"] += len(texts)

    def push(self, raw_text: str):
        now = time.time()
        texts = format_texts(self.cfg, raw_text)
        with self._lock:
            if not texts:
                self.stats["dropped_short"] += 1
                return
            if self.paused:
                # 暂停期间不排队，只记住最新一条，恢复时发它
                self._paused_latest = texts
                self.stats["dropped_paused"] += 1
                return
            key = "\n".join(texts)
            if (self._last_text == key
                    and now - self._last_text_ts < self.cfg["dedupe_seconds"]):
                self.stats["dropped_dup"] += 1
                return
            self._last_text, self._last_text_ts = key, now
            self._enqueue_locked(texts, now)

    def set_paused(self, paused: bool) -> int:
        """切换暂停状态。

        暂停：清空已积压的待发项，之后新译文只记住最新一条，不排队。
        恢复：清空后只把最新的一条放回队列，返回放回的段数。
        """
        with self._lock:
            if paused:
                if not self.paused:
                    self.paused = True
                    # 暂停瞬间若还有没发完的，只留下最新那一条（含它的分段），
                    # 恢复时发它；更早的积压全部丢掉，避免恢复后刷屏。
                    pending = [it for it in self._items if not it["acked"]]
                    self._paused_latest = None
                    if pending:
                        newest = max(it["batch"] for it in pending)
                        self._paused_latest = [
                            it["text"] for it in pending if it["batch"] == newest
                        ]
                    self._items = []
                return 0
            # 不管之前是不是暂停状态，恢复时都清掉积压、只留最新一条。
            # 这样 run.bat 重启后暂停状态丢了、页面还停在暂停的情况也不会刷屏。
            pending = [it for it in self._items if not it["acked"]]
            latest = self._paused_latest
            if not latest and pending:
                newest = max(it["batch"] for it in pending)
                latest = [it["text"] for it in pending if it["batch"] == newest]
            self.paused = False
            self._items = []
            self._paused_latest = None
            if not latest:
                return 0
            now = time.time()
            self._last_text, self._last_text_ts = "\n".join(latest), now
            self._enqueue_locked(latest, now)
            return len(latest)

    def pending(self):
        now = time.time()
        out = []
        with self._lock:
            if self.paused:
                return []
            keep = []
            blocked = False
            released = set()
            for it in self._items:
                if it["acked"]:
                    continue
                if it["after"] in released:
                    # 上一段过期了，别把下一段卡死；过期计时也从现在重新算
                    it["not_before"] = now
                    it["after"] = None
                    it["ts"] = now
                if now - it["ts"] > self.cfg["stale_seconds"]:
                    self.stats["dropped_stale"] += 1
                    released.add(it["id"])
                    continue
                keep.append(it)
                # 保持顺序：还没到点的一段会挡住后面的，新译文不会插队
                if blocked or it["not_before"] > now:
                    blocked = True
                    continue
                out.append({"id": it["id"], "text": it["text"]})
            self._items = keep
        return out

    def ack(self, ids):
        n = 0
        now = time.time()
        gap = self.cfg.get("split_interval", 2.0)
        with self._lock:
            idset = set(ids)
            for it in self._items:
                if it["id"] in idset and not it["acked"]:
                    it["acked"] = True
                    n += 1
                    self.last_sent = it["text"]
                    self.stats["acked"] += 1
            # 被 ack 的那段，它的下一段从现在开始倒计时——间隔是按"发完"算的
            for it in self._items:
                if it["after"] in idset and not it["acked"]:
                    it["not_before"] = now + gap
                    it["after"] = None
                    it["ts"] = now  # 过期计时从真正轮到它时开始算
            self._items = [it for it in self._items if not it["acked"]]
        return n

    def snapshot(self):
        with self._lock:
            return (dict(self.stats),
                    len([i for i in self._items if not i["acked"]]),
                    self.paused)


class Watcher(threading.Thread):
    """盯住 transcripts 目录里最新的 _translation.txt，逐行读新内容。"""

    def __init__(self, cfg: dict, queue: Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.queue = queue
        self._stop = threading.Event()
        configured = str(cfg.get("transcript_dir") or "").strip()
        self.dir = (
            Path(configured)
            if configured and Path(configured).is_dir()
            else None
        )
        self._last_detect = time.monotonic()
        self.current = None
        self.pos = 0
        self._buf = ""
        self._first_file = True

    def stop(self):
        self._stop.set()

    def _newest_file(self):
        if self.dir is None:
            return None
        try:
            files = sorted(self.dir.glob(TRANSCRIPT_GLOB),
                           key=lambda p: p.stat().st_mtime)
        except OSError:
            return None
        return files[-1] if files else None

    def _switch_to(self, path: Path):
        """切换文件。启动时第一个文件跳到末尾（不补发历史），
        之后出现的新会话文件从头读。"""
        self.current = path
        self._buf = ""
        if self._first_file:
            try:
                self.pos = path.stat().st_size
            except OSError:
                self.pos = 0
            self._first_file = False
            print(f"[watcher] 开始监听: {path.name}（从末尾开始，不补发历史）", flush=True)
        else:
            self.pos = 0
            print(f"[watcher] 新会话文件: {path.name}", flush=True)

    def run(self):
        while not self._stop.wait(self.cfg["poll_interval"]):
            if self.dir is None:
                now = time.monotonic()
                if now - self._last_detect >= 15:
                    self._last_detect = now
                    found = resolve_transcript_dir(self.cfg)
                    if found is not None:
                        self.dir = found
                        self.cfg["transcript_dir"] = str(found)
                        print(
                            f"[watcher] 找到 LiveTranslate 译文目录: {found}",
                            flush=True,
                        )
                continue

            try:
                if not self.dir.is_dir():
                    print(
                        f"[watcher] 目录不存在，等待: {self.dir}",
                        flush=True,
                    )
                    self.dir = None
                    self.current = None
                    continue
            except OSError:
                self.dir = None
                self.current = None
                continue

            newest = self._newest_file()
            if newest is None:
                continue
            if newest != self.current:
                self._switch_to(newest)

            try:
                with open(self.current, "r", encoding="utf-8",
                          errors="replace") as f:
                    f.seek(self.pos)
                    chunk = f.read()
                    self.pos = f.tell()
            except OSError:
                # 文件被轮转/删除，下一轮重找
                self.current = None
                continue

            if not chunk:
                continue
            self._buf += chunk
            *lines, self._buf = self._buf.split("\n")
            for line in lines:
                m = LINE_RE.match(line)
                if not m:
                    continue
                self.queue.push(m.group(2))


class Handler(BaseHTTPRequestHandler):
    queue: Queue = None
    cfg: dict = None
    server_version = "BiliDanmakuBridge/1.2"

    def log_message(self, fmt, *args):
        pass  # 静音访问日志

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _send_script(self):
        """把油猴脚本发出去 —— 地址以 .user.js 结尾，Tampermonkey 会自动弹安装框。"""
        try:
            data = (BASE / "bilidanmaku.user.js").read_bytes()
        except OSError:
            self._send(404, {"ok": False, "error": "script not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _discard_body(self):
        """把请求体读掉，保持连接状态干净。"""
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass

    def do_GET(self):
        if self.path.startswith("/bilidanmaku.user.js"):
            self._send_script()
        elif self.path.startswith("/pending"):
            self._send(200, {"ok": True, "items": self.queue.pending()})
        elif self.path.startswith("/status"):
            stats, waiting, paused = self.queue.snapshot()
            self._send(200, {"ok": True, "waiting": waiting, "paused": paused,
                             "last_sent": self.queue.last_sent, "stats": stats,
                             "transcript_dir": (self.cfg or {}).get("transcript_dir") or ""})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.startswith("/ack"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
                ids = data.get("ids") or []
                done = self.queue.ack([int(i) for i in ids])
                self._send(200, {"ok": True, "acked": done})
            except Exception as e:
                self._send(400, {"ok": False, "error": str(e)})
        elif self.path.startswith("/pause"):
            self._discard_body()
            self.queue.set_paused(True)
            self._send(200, {"ok": True, "paused": True})
        elif self.path.startswith("/resume"):
            self._discard_body()
            queued = self.queue.set_paused(False)
            self._send(200, {"ok": True, "paused": False, "queued": queued})
        else:
            self._send(404, {"ok": False, "error": "not found"})


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="B站弹幕同传助手：读取 LiveTranslate 译文并发到直播间"
    )
    parser.add_argument(
        "--transcript-dir",
        default=None,
        help="LiveTranslate 的 transcripts 目录；留空则自动搜索",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.transcript_dir:
        cfg["transcript_dir"] = args.transcript_dir
    resolved = resolve_transcript_dir(cfg)
    if resolved is not None:
        cfg["transcript_dir"] = str(resolved)
        print(f"[detect] 使用译文目录: {resolved}", flush=True)
    else:
        print("", flush=True)
        print("[!] 没有找到 LiveTranslate 的译文目录。", flush=True)
        print("    先启动 LiveTranslate，确认它已经翻译出一句；", flush=True)
        print("    然后在 config.json 里设置：", flush=True)
        print(r'      "transcript_dir": "D:\\你的\\LiveTranslate\\transcripts"', flush=True)
        print("    或者启动时指定：", flush=True)
        print(r'      run.bat --transcript-dir "D:\你的\LiveTranslate\transcripts"', flush=True)
        print("    程序会继续运行，每 15 秒自动再找一次。", flush=True)
        print("", flush=True)

    queue = Queue(cfg)
    watcher = Watcher(cfg, queue)
    watcher.start()

    Handler.queue = queue
    Handler.cfg = cfg
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", cfg["port"]), Handler)
    except OSError:
        print(f"[!] 端口 {cfg['port']} 已被占用——可能已经有一个服务在跑了。", flush=True)
        print("    直接去浏览器里用就行。要重开的话，先把上一个窗口关掉。", flush=True)
        input("按回车退出…")
        return

    print("=" * 56, flush=True)
    print("  B站弹幕同传助手 · 本地服务已启动", flush=True)
    print(f"  监听:   http://127.0.0.1:{cfg['port']}", flush=True)
    print(f"  转录:   {cfg['transcript_dir'] or '（自动搜索中…）'}", flush=True)
    print(f"  格式:   {cfg['prefix']}译文{cfg['suffix']}  上限 {cfg['max_length']} 字"
          f"  末尾句号{'删除' if cfg.get('strip_period', True) else '保留'}",
          flush=True)
    if cfg["max_length"]:
        print(f"  超长:   超过 {cfg['max_length']} 字自动在标点处断句，分段发送，"
              f"间隔 {cfg.get('split_interval', 2.0):g} 秒", flush=True)
    print("  暂停:   面板暂停期间不累积，继续后只发最新一条", flush=True)
    print("  状态查看: http://127.0.0.1:%d/status" % cfg["port"], flush=True)
    print("  装油猴脚本: http://127.0.0.1:%d/bilidanmaku.user.js" % cfg["port"], flush=True)
    print("  按 Ctrl+C 退出", flush=True)
    print("=" * 56, flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[exit] 正在退出…", flush=True)
    finally:
        watcher.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
