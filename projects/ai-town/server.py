"""仅用 Python 标准库提供本地教学网页；刷新页面不会重置世界。"""

import argparse
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

from model import DeepSeekDecider, ModelError
from town import get_npc, load_world, snapshot, step


WEB_DIR = Path(__file__).with_name("web")


class TownServer(ThreadingHTTPServer):
    def __init__(self, address, model_decider=None):
        self.model_decider = model_decider
        self.world = self.new_world()
        self.world_lock = threading.Lock()
        super().__init__(address, TownHandler)

    def new_world(self):
        world = load_world()
        if self.model_decider is not None:
            lin = get_npc(world, "lin")
            world["mode"] = "mixed"
            lin.update(controller="model", model=self.model_decider.model)
        return world

    def state(self):
        state = snapshot(self.world)
        if self.model_decider is not None:
            state["model_runtime"] = self.model_decider.public_status()
        return state


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
                state = self.server.state()
            return self.send_json(200, state)
        if path == "/api/health":
            return self.send_json(200, {"status": "ok", "mode": self.server.world["mode"]})
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
                    self.server.world = self.server.new_world()
                else:
                    step(self.server.world, self.server.model_decider)
                state = self.server.state()
        except ModelError as error:
            return self.send_json(502, {"error": str(error)})
        except (ValueError, OSError) as error:
            return self.send_json(400, {"error": f"操作未完成：{error}"})
        self.send_json(200, state)


def main():
    parser = argparse.ArgumentParser(description="启动晨光小镇的本地可视化网页。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="在运行程序的这台电脑上自动打开浏览器")
    parser.add_argument("--mode", choices=("rules", "deepseek"), default="rules")
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL"), help="官方文档中的模型 ID")
    parser.add_argument("--prompt-key", action="store_true", help="在本机终端隐藏输入密钥，不保存到文件")
    parser.add_argument("--max-model-calls", type=int, default=5, help="单次启动允许的模型请求次数（含失败）")
    args = parser.parse_args()
    try:
        decider = None
        if args.mode == "deepseek":
            model_name = args.model
            if not model_name and args.prompt_key:
                model_name = input("请输入官方 Flash 模型 ID（model）：").strip()
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key and args.prompt_key:
                if not os.isatty(0):
                    raise ModelError("隐藏输入密钥需要交互式终端，请用终端启动。")
                print("密钥只用于本次运行，不会显示或写入文件。")
                api_key = getpass.getpass("DeepSeek API Key（粘贴后按回车，屏幕不会显示字符）：")
            decider = DeepSeekDecider(api_key, model_name, max_calls=args.max_model_calls)
        server = TownServer((args.host, args.port), decider)
    except (OSError, ValueError, ModelError, EOFError) as error:
        parser.exit(1, f"启动失败：{error}\n")
    port = server.server_address[1]
    browser_host = "127.0.0.1" if args.host in ("127.0.0.1", "0.0.0.0", "localhost") else args.host
    browser_url = f"http://{browser_host}:{port}"
    mode_label = (f"小林使用 DeepSeek / {decider.model}，其余居民使用规则；本次最多{decider.max_calls}次模型请求"
                  if decider else "规则演示，无模型调用")
    print(f"晨光小镇已启动，监听 {args.host}:{port}（{mode_label}）。", flush=True)
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
