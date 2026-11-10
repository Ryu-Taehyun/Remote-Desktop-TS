"""원격 데스크톱 호스트 앱 (Python tkinter GUI).

이 PC 의 화면을 서버로 전송하고, 원격 제어가 허용되면 뷰어의 입력을 재생한다.
실행:  python -m agent
"""
from __future__ import annotations

import os
import platform
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from pydantic import ValidationError

from .client import ApiClient, ApiError
from .protocol import SessionOut, TokenResponse

DEFAULT_SERVER = os.getenv("RD_SERVER", "http://localhost:8000")


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
        server = tk.StringVar(value=DEFAULT_SERVER)
        email, username, password = tk.StringVar(), tk.StringVar(), tk.StringVar()

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
        self.fps_var = tk.IntVar(value=4)
        self.quality_var = tk.IntVar(value=60)
        self.width_var = tk.StringVar(value="1280")

        f = ttk.LabelFrame(c, text="세션 설정", padding=10)
        f.pack(fill="x")
        ttk.Label(f, text="PC 이름").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(f, text="FPS").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, from_=1, to=10, textvariable=self.fps_var, width=6).grid(row=1, column=1, sticky="w", pady=2)
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
            self.session = s
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
        from .capture import ScreenCapturer

        assert self.api and self.session
        api, sid = self.api, self.session.id
        try:
            cap = ScreenCapturer()
        except Exception as e:
            self.ui(lambda: self._session_gone(f"화면 캡처 초기화 실패: {e}"))
            return
        self.monitor = cap.monitor
        frames, t0, errors = 0, time.monotonic(), 0
        try:
            while not self.stop_event.is_set():
                start = time.monotonic()
                fps = max(1, min(10, int(self.fps_var.get() or 1)))
                try:
                    frame = cap.grab(max_width=int(self.width_var.get()), quality=int(self.quality_var.get()))
                    ack = api.upload_frame(sid, frame)
                    errors = 0
                    frames += 1
                    if ack.allow_control != self.control_var.get():  # 웹에서 변경된 경우 동기화
                        self.ui(lambda v=ack.allow_control: self.control_var.set(v))
                    if self.session:
                        self.session = self.session.model_copy(update={"allow_control": ack.allow_control})
                except ApiError as e:
                    if e.status in (403, 404):
                        self.ui(lambda: self._session_gone("세션이 종료되었습니다"))
                        return
                    errors += 1
                    self.ui(lambda m=str(e): self.write_log(f"업로드 실패: {m}"))
                except Exception as e:
                    errors += 1
                    self.ui(lambda m=f"{type(e).__name__}: {e}": self.write_log(f"전송 오류: {m}"))
                if errors:
                    self.stop_event.wait(min(10, 2 ** errors))  # 지수 백오프
                    continue
                now = time.monotonic()
                if now - t0 >= 2:
                    rate = frames / (now - t0)
                    self.ui(lambda r=rate, n=len(frame.data_b64): self.status_var.set(
                        f"공유 중 · {r:.1f} fps · 프레임 {n * 3 // 4 // 1024} KB"))
                    frames, t0 = 0, now
                self.stop_event.wait(max(0.0, 1 / fps - (time.monotonic() - start)))
        finally:
            cap.close()

    def _input_worker(self) -> None:
        assert self.api and self.session
        api, sid = self.api, self.session.id
        player = None
        while not self.stop_event.is_set():
            if not (self.session and self.session.allow_control):
                self.stop_event.wait(0.5)
                continue
            try:
                if player is None:
                    while not hasattr(self, "monitor") and not self.stop_event.is_set():
                        self.stop_event.wait(0.1)
                    from .input_control import InputPlayer

                    player = InputPlayer(self.monitor)
                batch = api.drain_input(sid)
                for ev in batch.events:
                    player.play(ev)
                self.stop_event.wait(0.03 if batch.events else 0.1)
            except ApiError as e:
                if e.status in (403, 404):
                    return
                self.stop_event.wait(1)
            except Exception as e:
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
