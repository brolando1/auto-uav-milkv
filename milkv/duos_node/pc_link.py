# TCP server on the Duo S that the PC ground station connects to over the
# wired link. Outgoing frames go through latest-wins slots so a slow/blocked
# wire never backs up the inference loop.

import socket
import threading

from common import protocol


class PCLink:
    def __init__(self, host="0.0.0.0", port=5800, on_command=None):
        self.host = host
        self.port = port
        self.on_command = on_command    # on_command(dict)
        self._running = True
        self._client = None
        self._client_lock = threading.Lock()
        self._slots = {}                # frame_type -> payload (latest wins)
        self._slot_cond = threading.Condition()

    def start(self):
        threading.Thread(name="PCLinkAccept", target=self._accept_loop, daemon=True).start()
        threading.Thread(name="PCLinkSender", target=self._send_loop, daemon=True).start()

    def stop(self):
        self._running = False
        with self._slot_cond:
            self._slot_cond.notify_all()

    def publish(self, frame_type, payload):
        with self._slot_cond:
            self._slots[frame_type] = payload
            self._slot_cond.notify()

    def client_connected(self):
        with self._client_lock:
            return self._client is not None

    def _accept_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(1)
        print(f"[PCLINK] Listening on {self.host}:{self.port}")
        while self._running:
            try:
                client, addr = server.accept()
            except OSError:
                break
            print(f"[PCLINK] PC connected from {addr}")
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._client_lock:
                old = self._client
                self._client = client
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            threading.Thread(name="PCLinkRx", target=self._recv_loop, args=(client,), daemon=True).start()

    def _recv_loop(self, client):
        try:
            while self._running:
                frame_type, payload = protocol.recv_frame(client)
                if frame_type == protocol.FRAME_CMD and self.on_command is not None:
                    try:
                        self.on_command(protocol.decode_json(payload))
                    except Exception as e:
                        print(f"[PCLINK] Bad command: {e}")
        except (OSError, ConnectionError):
            pass
        finally:
            self._drop_client(client)

    def _send_loop(self):
        while self._running:
            with self._slot_cond:
                while self._running and not self._slots:
                    self._slot_cond.wait(timeout=0.5)
                pending = list(self._slots.items())
                self._slots.clear()

            with self._client_lock:
                client = self._client
            if client is None:
                continue

            try:
                for frame_type, payload in pending:
                    protocol.send_frame(client, frame_type, payload)
            except (OSError, ConnectionError):
                self._drop_client(client)

    def _drop_client(self, client):
        with self._client_lock:
            if self._client is client:
                self._client = None
                print("[PCLINK] PC disconnected")
        try:
            client.close()
        except Exception:
            pass
