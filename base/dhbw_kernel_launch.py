"""Entry point of the kernel spec "Python 3 (GPU)", for JupyterLab and for VS Code alike.

JupyterLab starts the kernel through the Jupyter server, whose KubernetesProvisioner fills in {kernel_id}, {response_address} and the rest and runs this script: it hands over to gateway_provisioners' launch_kubernetes.py, which creates the kernel pod on a GPU node, exactly as before.

VS Code (code-server) starts kernel specs on its own: it fills in only {connection_file} and expects a kernel on the ports in that file — it knows nothing about provisioners, so the GPU kernel never came up there. In that case — {kernel_id} still unfilled — this script is the kernel VS Code talks to: it binds the ports of the connection file, has the Jupyter server in the same pod start the real GPU kernel through its REST API (the provisioner path above, quota check and queue included), and passes the messages between VS Code's ZeroMQ channels and the kernel's websocket. To VS Code it looks like a local kernel; the GPU kernel runs as in JupyterLab.
"""
import asyncio
import json
import os
import signal
import sys
import urllib.request

DEBUG = bool(os.environ.get("DHBW_KERNEL_PROXY_DEBUG"))
LAUNCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch_kubernetes.py")


def provisioner_mode(argv):
    """The provisioner filled in the kernel id: drop our --connection-file and run the real launcher."""
    args = list(argv)
    if "--connection-file" in args:
        i = args.index("--connection-file")
        del args[i:i + 2]
    os.execv(sys.executable, [sys.executable, LAUNCHER] + args)


class Proxy:
    def __init__(self, connection_file):
        from jupyter_client.session import Session

        with open(connection_file) as f:
            self.conn = json.load(f)
        self.session = Session(key=self.conn["key"].encode(), signature_scheme=self.conn.get("signature_scheme", "hmac-sha256"))
        prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
        port = os.environ.get("JUPYTER_PORT", "8888")
        self.http = f"http://127.0.0.1:{port}{prefix}"
        self.ws_url = f"ws://127.0.0.1:{port}{prefix}"
        self.auth = {"Authorization": "token " + os.environ["JUPYTERHUB_API_TOKEN"]}
        self.kernel_id = None
        self.identities = {}  # channel -> ZeroMQ identity of the client (VS Code), for replies on ROUTER sockets
        self.done = asyncio.Event()

    def rest(self, method, path, body=None):
        headers = dict(self.auth, **({"Content-Type": "application/json"} if body is not None else {}))
        req = urllib.request.Request(self.http + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=900) as r:
            data = r.read()
            return json.loads(data) if data else None

    def address(self, name):
        return f"{self.conn.get('transport', 'tcp')}://{self.conn.get('ip', '127.0.0.1')}:{self.conn[name + '_port']}"

    async def run(self):
        import zmq.asyncio

        ctx = zmq.asyncio.Context()
        try:
            await self._serve(ctx)
        finally:
            # Closes every socket: without it the process would wait for its sockets on exit and never end.
            ctx.destroy(linger=0)

    async def _serve(self, ctx):
        import zmq
        from tornado.httpclient import HTTPRequest
        from tornado.websocket import websocket_connect

        sockets = {
            "shell": ctx.socket(zmq.ROUTER),
            "control": ctx.socket(zmq.ROUTER),
            "stdin": ctx.socket(zmq.ROUTER),
            "iopub": ctx.socket(zmq.PUB),
        }
        for name, sock in sockets.items():
            sock.linger = 0
            sock.bind(self.address(name))
        hb = ctx.socket(zmq.REP)
        hb.linger = 0
        hb.bind(self.address("hb"))

        async def heartbeat():
            while not self.done.is_set():
                msg = await hb.recv_multipart()
                await hb.send_multipart(msg)

        # Answer the heartbeat from the start: the GPU kernel may take a while (queue, image), and a client without a heartbeat takes the kernel for dead.
        beat = asyncio.ensure_future(heartbeat())

        # The real kernel: started by the Jupyter server, which applies the provisioner, the quota check and the queue. Waiting for a GPU happens here; VS Code shows the kernel as starting meanwhile.
        loop = asyncio.get_running_loop()
        kernel = await loop.run_in_executor(None, lambda: self.rest("POST", "api/kernels", {"name": "python3-gpu"}))
        self.kernel_id = kernel["id"]
        ws = await websocket_connect(HTTPRequest(f"{self.ws_url}api/kernels/{self.kernel_id}/channels", headers=self.auth))

        async def from_client(name):
            sock = sockets[name]
            while not self.done.is_set():
                frames = await sock.recv_multipart(copy=True)
                idents, rest = self.session.feed_identities(frames, copy=True)
                self.identities[name] = idents
                msg = self.session.deserialize(rest, content=True, copy=True)
                if DEBUG:
                    print(f"-> {name} {msg['header'].get('msg_type')}", file=sys.stderr, flush=True)
                out = {
                    "header": dict(msg["header"], date=str(msg["header"].get("date", ""))),
                    "parent_header": msg["parent_header"],
                    "metadata": msg["metadata"],
                    "content": msg["content"],
                    "channel": name,
                }
                if out["parent_header"]:
                    out["parent_header"] = dict(out["parent_header"], date=str(out["parent_header"].get("date", "")))
                await ws.write_message(json.dumps(out, default=str))

        async def from_kernel():
            while True:
                text = await ws.read_message()
                if text is None:
                    break
                if isinstance(text, bytes):
                    continue  # binary frames (buffers, e.g. widgets) are not passed on
                m = json.loads(text)
                channel = m.pop("channel", "iopub")
                if DEBUG:
                    print(f"<- {channel} {m.get('header', {}).get('msg_type')}", file=sys.stderr, flush=True)
                sock = sockets.get(channel)
                if sock is None:
                    continue
                msg = {"header": m["header"], "parent_header": m.get("parent_header") or {}, "metadata": m.get("metadata") or {}, "content": m.get("content") or {}, "msg_id": m["header"].get("msg_id"), "msg_type": m["header"].get("msg_type")}
                ident = self.identities.get(channel, []) if channel != "iopub" else [m["header"].get("msg_type", "").encode()]
                self.session.send(sock, msg, ident=ident)
                if channel in ("shell", "control") and msg["msg_type"] == "shutdown_reply" and not (msg["content"] or {}).get("restart"):
                    break
            self.done.set()

        def failed(task):
            # A broken channel ends the kernel visibly instead of leaving VS Code waiting.
            if not task.cancelled() and task.exception() is not None:
                print(f"dhbw_kernel_launch: {task.exception()!r}", file=sys.stderr, flush=True)
                self.done.set()

        tasks = [beat] + [asyncio.ensure_future(t) for t in (from_client("shell"), from_client("control"), from_client("stdin"), from_kernel())]
        for t in tasks:
            t.add_done_callback(failed)
        await self.done.wait()
        await asyncio.sleep(0.5)  # let the last replies go out
        for t in tasks:
            t.cancel()
        ws.close()
        self.shutdown()

    def interrupt(self):
        if self.kernel_id:
            try:
                self.rest("POST", f"api/kernels/{self.kernel_id}/interrupt")
            except Exception:
                pass

    def shutdown(self):
        if self.kernel_id:
            try:
                self.rest("DELETE", f"api/kernels/{self.kernel_id}")
            except Exception:
                pass
            self.kernel_id = None


def proxy_mode(connection_file):
    proxy = Proxy(connection_file)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # VS Code interrupts a kernel with SIGINT and ends it with SIGTERM: pass both on to the real kernel.
    loop.add_signal_handler(signal.SIGINT, proxy.interrupt)
    loop.add_signal_handler(signal.SIGTERM, proxy.done.set)
    try:
        loop.run_until_complete(proxy.run())
    finally:
        proxy.shutdown()


def main(argv):
    if "--connection-file" in argv:
        connection_file = argv[argv.index("--connection-file") + 1]
        kernel_id = argv[argv.index("--kernel-id") + 1] if "--kernel-id" in argv else "{kernel_id}"
        if kernel_id == "{kernel_id}" or not kernel_id:
            proxy_mode(connection_file)
            return
    provisioner_mode(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
