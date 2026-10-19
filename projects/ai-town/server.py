"""仅用 Python 标准库提供本地教学网页；刷新页面不会重置世界。"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

from town import load_world, snapshot, step


WEB_DIR = Path(__file__).with_name("web")


class TownServer(ThreadingHTTPServer):
    def __init__(self, address):
        self.world = load_world()
        self.world_lock = threading.Lock()
        super().__init__(address, TownHandler)


class TownHandler(BaseHTTPRequestHandler):
    def send_data(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_data(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            with self.server.world_lock:
                state = snapshot(self.server.world)
            return self.send_json(200, state)
        if path == "/api/health":
            return self.send_json(200, {"status": "ok", "mode": "rules"})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in files:
            return self.send_json(404, {"error": "没有这个页面或接口。"})
        name, mime = files[path]
        try:
            data = (WEB_DIR / name).read_bytes()
        except OSError:
            return self.send_json(500, {"error": "网页文件缺失，请检查 web 目录。"})
        self.send_data(200, data, mime)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/step", "/api/reset"):
            return self.send_json(404, {"error": "没有这个操作。"})
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.send_json(403, {"error": "请从小镇页面执行操作。"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1024:
                return self.send_json(413, {"error": "请求过大。"})
            body = self.rfile.read(length)
            if body and json.loads(body) != {}:
                return self.send_json(400, {"error": "此接口仅接收空对象。"})
            with self.server.world_lock:
                if path == "/api/reset":
                    self.server.world = load_world()
                else:
                    step(self.server.world)
                state = snapshot(self.server.world)
        except (ValueError, OSError) as error:
            return self.send_json(400, {"error": f"操作未完成：{error}"})
        self.send_json(200, state)


def main():
    parser = argparse.ArgumentParser(description="启动晨光小镇的本地可视化网页。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="在运行程序的这台电脑上自动打开浏览器")
    args = parser.parse_args()
    try:
        server = TownServer((args.host, args.port))
    except (OSError, ValueError) as error:
        parser.exit(1, f"启动失败：{error}\n")
    port = server.server_address[1]
    browser_host = "127.0.0.1" if args.host in ("127.0.0.1", "0.0.0.0", "localhost") else args.host
    browser_url = f"http://{browser_host}:{port}"
    print(f"晨光小镇已启动，监听 {args.host}:{port}（规则演示，无模型调用）。", flush=True)
    print(f"在运行程序的这台电脑上打开：{browser_url}", flush=True)
    if args.open_browser:
        opener = threading.Timer(0.4, webbrowser.open, args=(browser_url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n小镇已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
