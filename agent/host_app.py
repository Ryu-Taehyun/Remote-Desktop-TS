"""원격 데스크톱 호스트 앱 (Python tkinter GUI).

이 PC 의 화면을 서버로 전송하고, 원격 제어가 허용되면 뷰어의 입력을 재생한다.
실행:  python -m agent
"""
from __future__ import annotations

import json
import os
import platform
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from pydantic import ValidationError

from .client import ApiClient, ApiError
from .protocol import SessionOut, TokenResponse

DEFAULT_SERVER = os.getenv("RD_SERVER", "http://localhost:8000")
SETTINGS_PATH = Path(os.getenv("APPDATA") or Path.home() / ".config") / "RemoteDesktopHost" / "settings.json"


def load_settings() -> dict:
    """마지막으로 사용한 서버 주소/이메일 (비밀번호는 저장하지 않음)."""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in ("server", "email")}
    except (OSError, ValueError, AttributeError):
        return {}


def save_settings(**values: str) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(load_settings() | values, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class HostApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Remote Desktop Host")
        self.geometry("460x560")
        self.minsize(420, 520)

        self.api: ApiClient | None = None
        self.user: TokenResponse | None = None
        self.session: SessionOut | None = None
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []
        self.rt = None  # RealtimeHost (WebSocket 실시간 연결)
        self.ui_queue: queue.Queue = queue.Queue()  # 워커 스레드 → UI 스레드 메시지

        self.container = ttk.Frame(self, padding=16)
        self.container.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._drain_ui_queue)
        self.show_login()

    # ------------------------------------------------------------------ 공통
    def _clear(self) -> None:
        for w in self.container.winfo_children():
            w.destroy()

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                fn = self.ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def ui(self, fn) -> None:
        """워커 스레드에서 UI 를 안전하게 갱신."""
        self.ui_queue.put(fn)

    def run_bg(self, work, on_ok, on_err=None) -> None:
        def target():
            try:
                result = work()
            except (ApiError, ValidationError, OSError) as e:
                msg = str(e) if isinstance(e, ApiError) else f"{type(e).__name__}: {e}"
                self.ui(lambda: (on_err or self._error)(msg))
            except Exception as e:  # requests 예외 등
                self.ui(lambda: (on_err or self._error)(f"{type(e).__name__}: {e}"))
            else:
                self.ui(lambda: on_ok(result))

        threading.Thread(target=target, daemon=True).start()

    def _error(self, msg: str) -> None:
        messagebox.showerror("오류", msg, parent=self)

    # ------------------------------------------------------------------ 로그인 화면
    def show_login(self) -> None:
        self._clear()
        c = self.container
        mode = tk.StringVar(value="login")
        saved = load_settings()
        server = tk.StringVar(value=os.getenv("RD_SERVER") or saved.get("server") or DEFAULT_SERVER)
        email, username, password = tk.StringVar(value=saved.get("email", "")), tk.StringVar(), tk.StringVar()

        ttk.Label(c, text="원격 데스크톱 호스트", font=("", 16, "bold")).pack(anchor="w", pady=(0, 12))
        tabs = ttk.Frame(c)
        tabs.pack(fill="x", pady=(0, 12))
        ttk.Radiobutton(tabs, text="로그인", value="login", variable=mode).pack(side="left")
        ttk.Radiobutton(tabs, text="회원가입", value="signup", variable=mode).pack(side="left", padx=12)

        def field(label: str, var: tk.StringVar, show: str = "") -> ttk.Frame:
            f = ttk.Frame(c)
            ttk.Label(f, text=label).pack(anchor="w")
            ttk.Entry(f, textvariable=var, show=show).pack(fill="x", pady=(2, 8))
            f.pack(fill="x")
            return f

        field("서버 주소 (예: https://your-app.vercel.app)", server)
        field("이메일", email)
        name_row = field("이름", username)
        pw_row = field("비밀번호", password, show="•")
        btn = ttk.Button(c, text="로그인")
        btn.pack(fill="x", pady=8)

        def sync(*_):
            if mode.get() == "signup":
                name_row.pack(fill="x", before=pw_row)
                btn.config(text="가입하기")
            else:
                name_row.pack_forget()
                btn.config(text="로그인")

        mode.trace_add("write", sync)
        sync()

        def submit(*_):
            self.api = ApiClient(server.get().strip())
            api = self.api
            btn.state(["disabled"])
            if mode.get() == "signup":
                work = lambda: api.signup(email.get().strip(), username.get().strip(), password.get())
            else:
                work = lambda: api.login(email.get().strip(), password.get())

            def ok(t: TokenResponse):
                self.user = t
                save_settings(server=api.base_url, email=t.user.email)
                self.show_main()

            def err(msg: str):
                btn.state(["!disabled"])
                self._error(msg)

            self.run_bg(work, ok, err)

        btn.config(command=submit)
        self.bind("<Return>", submit)

    # ------------------------------------------------------------------ 메인 화면
    def show_main(self) -> None:
        self.unbind("<Return>")
        self._clear()
        c = self.container
        assert self.user is not None

        ttk.Label(c, text=f"{self.user.user.username} 님", font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(c, text=self.api.base_url if self.api else "", foreground="gray").pack(anchor="w", pady=(0, 12))

        self.name_var = tk.StringVar(value=platform.node() or "My PC")
        self.control_var = tk.BooleanVar(value=False)
        self.fps_var = tk.IntVar(value=15)
        self.quality_var = tk.IntVar(value=60)
        self.width_var = tk.StringVar(value="1280")

        f = ttk.LabelFrame(c, text="세션 설정", padding=10)
        f.pack(fill="x")
        ttk.Label(f, text="PC 이름").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(f, text="FPS").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, from_=1, to=30, textvariable=self.fps_var, width=6).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(f, text="JPEG 품질").grid(row=2, column=0, sticky="w")
        ttk.Scale(f, from_=20, to=90, variable=self.quality_var, orient="horizontal").grid(row=2, column=1, sticky="ew")
        ttk.Label(f, text="최대 너비(px)").grid(row=3, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.width_var, values=["800", "1024", "1280", "1600", "1920"], width=8,
                     state="readonly").grid(row=3, column=1, sticky="w", pady=2)
        ttk.Checkbutton(f, text="원격 제어 허용 (마우스/키보드)", variable=self.control_var,
                        command=self.toggle_control).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        f.columnconfigure(1, weight=1)

        code_box = ttk.LabelFrame(c, text="접속 코드", padding=10)
        code_box.pack(fill="x", pady=12)
        self.code_label = ttk.Label(code_box, text="—", font=("Courier", 22, "bold"))
        self.code_label.pack(side="left")
        ttk.Button(code_box, text="복사", command=self.copy_code).pack(side="right")

        btns = ttk.Frame(c)
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="공유 시작", command=self.start_sharing)
        self.start_btn.pack(side="left", expand=True, fill="x")
        self.stop_btn = ttk.Button(btns, text="일시 중지", command=self.stop_sharing, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=6)
        ttk.Button(btns, text="세션 종료", command=self.end_session).pack(side="left", expand=True, fill="x")

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(c, textvariable=self.status_var).pack(anchor="w", pady=(12, 4))
        self.log = tk.Text(c, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        ttk.Button(c, text="로그아웃", command=self.logout).pack(anchor="e", pady=(8, 0))

    def write_log(self, msg: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def copy_code(self) -> None:
        if self.session and self.session.access_code:
            self.clipboard_clear()
            self.clipboard_append(self.session.access_code)
            self.write_log("접속 코드를 클립보드에 복사했습니다")

    def toggle_control(self) -> None:
        if not (self.api and self.session):
            return
        api, sid, allow = self.api, self.session.id, self.control_var.get()
        if allow and not messagebox.askyesno(
            "원격 제어 허용", "접속 코드를 가진 사용자가 이 PC 의 마우스와 키보드를 조작할 수 있습니다.\n허용할까요?", parent=self
        ):
            self.control_var.set(False)
            return

        def ok(s: SessionOut):
            changed = not self.session or self.session.allow_control != s.allow_control
            self.session = s
            if changed:  # 서버 알림(_apply_control)이 먼저 처리했으면 중복 기록하지 않음
                self.write_log("원격 제어 " + ("허용" if s.allow_control else "차단"))

        self.run_bg(lambda: api.set_control(sid, allow), ok)

    # ------------------------------------------------------------------ 공유
    def start_sharing(self) -> None:
        assert self.api is not None
        api = self.api
        self.start_btn.state(["disabled"])

        def ok(s: SessionOut):
            self.session = s
            self.code_label.config(text=s.access_code or "—")
            self.write_log(f"세션 '{s.name}' 준비됨. 웹에서 접속 코드로 참여하세요.")
            self._start_workers()

        def err(msg: str):
            self.start_btn.state(["!disabled"])
            self._error(msg)

        if self.session:
            ok(self.session)
        else:
            if self.control_var.get() and not messagebox.askyesno(
                "원격 제어 허용", "원격 제어를 허용한 상태로 세션을 시작합니다. 계속할까요?", parent=self
            ):
                self.control_var.set(False)
            name, allow = self.name_var.get().strip() or "My PC", self.control_var.get()
            self.run_bg(lambda: api.create_session(name, allow), ok, err)

    def _start_workers(self) -> None:
        self.stop_event.clear()
        self.workers = [
            threading.Thread(target=self._frame_worker, daemon=True),
            threading.Thread(target=self._input_worker, daemon=True),
        ]
        for w in self.workers:
            w.start()
        self.stop_btn.state(["!disabled"])
        self.status_var.set("공유 중…")

    def stop_sharing(self) -> None:
        self.stop_event.set()
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.status_var.set("일시 중지됨")
        self.write_log("화면 공유를 일시 중지했습니다")

    def end_session(self) -> None:
        if not (self.api and self.session):
            return
        if not messagebox.askyesno("세션 종료", "세션을 종료하면 접속 코드가 무효화됩니다. 종료할까요?", parent=self):
            return
        self.stop_sharing()
        api, sid = self.api, self.session.id

        def ok(_):
            self.session = None
            self.code_label.config(text="—")
            self.write_log("세션을 종료했습니다")

        self.run_bg(lambda: api.end_session(sid), ok)

    def _session_gone(self, msg: str) -> None:
        self.stop_sharing()
        self.session = None
        self.code_label.config(text="—")
        self.write_log(msg)

    def _frame_worker(self) -> None:
        """화면 캡처 → 전송. WebSocket(실시간)을 먼저 시도하고, 안 되면 HTTP 로 보낸다."""
        from .capture import ScreenCapturer
        from .realtime import RealtimeHost

        assert self.api and self.session and self.user
        api, sid, token = self.api, self.session.id, self.user.access_token
        try:
            cap = ScreenCapturer()
        except Exception as e:
            self.ui(lambda: self._session_gone(f"화면 캡처 초기화 실패: {e}"))
            return
        self.monitor = cap.monitor
        frames, t0, errors, size = 0, time.monotonic(), 0, 0
        last_jpeg, last_sent, next_ws_try = b"", 0.0, 0.0
        try:
            while not self.stop_event.is_set():
                start = time.monotonic()
                if self.rt is None and start >= next_ws_try:
                    self.rt = RealtimeHost.connect(api.base_url, token, sid)
                    next_ws_try = start + 10  # 실패하면 10초 뒤 재시도 (그동안 HTTP)
                    mode = "실시간(WebSocket)" if self.rt else "호환 모드(HTTP)"
                    self.ui(lambda m=mode: self.write_log(f"전송 방식: {m}"))
                    if self.rt:
                        self._apply_control(self.rt.status.allow_control)
                rt = self.rt
                max_fps = 30 if rt else 10
                fps = max(1, min(max_fps, int(self.fps_var.get() or 1)))
                try:
                    jpeg, w, h = cap.grab_jpeg(max_width=int(self.width_var.get()), quality=int(self.quality_var.get()))
                    size = len(jpeg)
                    if rt is not None:
                        # 화면이 그대로면 보내지 않음 (1초마다 한 번은 보내서 연결 유지)
                        if jpeg != last_jpeg or start - last_sent > 1:
                            rt.send_frame(jpeg, w, h)
                            last_jpeg, last_sent = jpeg, start
                            frames += 1
                    else:
                        import base64

                        from .protocol import FrameUpload

                        ack = api.upload_frame(sid, FrameUpload(
                            width=w, height=h, mime="image/jpeg", data_b64=base64.b64encode(jpeg).decode()))
                        frames += 1
                        self._apply_control(ack.allow_control)
                    errors = 0
                except ApiError as e:
                    if e.status in (403, 404):
                        self.ui(lambda: self._session_gone("세션이 종료되었습니다"))
                        return
                    errors += 1
                    self.ui(lambda m=str(e): self.write_log(f"업로드 실패: {m}"))
                except Exception as e:
                    errors += 1
                    if rt is not None:  # WebSocket 이 끊김 → 곧바로 재연결 시도
                        rt.close()
                        self.rt, next_ws_try = None, 0.0
                        self.ui(lambda: self.write_log("실시간 연결이 끊겨 다시 연결합니다"))
                    else:
                        self.ui(lambda m=f"{type(e).__name__}: {e}": self.write_log(f"전송 오류: {m}"))
                if errors:
                    self.stop_event.wait(min(10, 2 ** errors))  # 지수 백오프
                    continue
                now = time.monotonic()
                if now - t0 >= 2:
                    rate = frames / (now - t0)
                    mode = "실시간" if self.rt else "HTTP"
                    self.ui(lambda r=rate, n=size, m=mode: self.status_var.set(
                        f"공유 중 · {m} · {r:.1f} fps · 프레임 {n // 1024} KB"))
                    frames, t0 = 0, now
                self.stop_event.wait(max(0.0, 1 / fps - (time.monotonic() - start)))
        finally:
            cap.close()
            if self.rt is not None:
                self.rt.close()
                self.rt = None

    def _apply_control(self, allow: bool) -> None:
        """서버/웹에서 바뀐 원격 제어 허용 여부를 UI 와 동기화."""
        if self.session and self.session.allow_control != allow:
            self.session = self.session.model_copy(update={"allow_control": allow})
            self.ui(lambda: (self.control_var.set(allow), self.write_log("원격 제어 " + ("허용" if allow else "차단"))))

    def _input_worker(self) -> None:
        """원격 입력 재생. 실시간 모드에서는 푸시로 즉시, HTTP 모드에서는 폴링으로 받는다."""
        from .protocol import WsError, WsInput, WsStatus

        assert self.api and self.session
        api, sid = self.api, self.session.id
        player = None

        def get_player():
            nonlocal player
            if player is None:
                while not hasattr(self, "monitor") and not self.stop_event.is_set():
                    self.stop_event.wait(0.1)
                from .input_control import InputPlayer

                player = InputPlayer(self.monitor)
            return player

        while not self.stop_event.is_set():
            rt = self.rt
            try:
                if rt is not None:
                    msg = rt.recv(timeout=0.5)
                    if isinstance(msg, WsInput) and self.session and self.session.allow_control:
                        p = get_player()
                        for ev in msg.events:
                            p.play(ev)
                    elif isinstance(msg, WsStatus):
                        self._apply_control(msg.allow_control)
                    elif isinstance(msg, WsError):
                        if "종료" in msg.detail:
                            self.ui(lambda: self._session_gone("세션이 종료되었습니다"))
                            return
                        self.ui(lambda d=msg.detail: self.write_log(f"서버: {d}"))
                    continue
                if not (self.session and self.session.allow_control):
                    self.stop_event.wait(0.3)
                    continue
                batch = api.drain_input(sid)
                p = get_player()
                for ev in batch.events:
                    p.play(ev)
                self.stop_event.wait(0.03 if batch.events else 0.1)
            except ApiError as e:
                if e.status in (403, 404):
                    return
                self.stop_event.wait(1)
            except Exception as e:
                if rt is not None:  # 연결 끊김 — 프레임 스레드가 재연결함
                    self.stop_event.wait(0.2)
                    continue
                self.ui(lambda m=f"{type(e).__name__}: {e}": self.write_log(f"입력 처리 오류: {m}"))
                self.stop_event.wait(1)

    # ------------------------------------------------------------------ 종료
    def logout(self) -> None:
        self.stop_event.set()
        self.session = None
        self.api = None
        self.user = None
        self.show_login()

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


def main() -> None:
    HostApp().mainloop()


if __name__ == "__main__":
    main()
