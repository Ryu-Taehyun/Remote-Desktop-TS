import { api, ApiError, auth, wsUrl } from "../api";
import { h } from "../dom";
import { WsAuth, WsInput, WsServerMessage, type InputEvent, type MouseButton, type SessionOut } from "../protocol";

const BUTTONS: Record<number, MouseButton> = { 0: "left", 1: "middle", 2: "right" };

/**
 * 원격 화면 뷰어.
 *  1) 실시간 모드: WebSocket 으로 JPEG 프레임을 바로 받고 입력도 즉시 전송 (로컬/상시 서버)
 *  2) 호환 모드: WebSocket 이 막힌 환경(일부 프록시·방화벽)에서는 HTTP 폴링으로 자동 전환
 */
export function viewerView(sessionId: string, go: (hash: string) => void): { el: HTMLElement; dispose: () => void } {
  let disposed = false;
  let session: SessionOut | null = null;
  let mode: "connecting" | "ws" | "http" = "connecting";
  let ws: WebSocket | null = null;
  let seq = 0;
  let queue: InputEvent[] = [];
  let pendingMove: InputEvent | null = null;
  let fpsCount = 0;

  const img = h("img", { class: "screen", alt: "원격 화면", draggable: "false", tabindex: "0" });
  const placeholder = h("p", { class: "muted" }, "호스트 화면을 기다리는 중…");
  const status = h("span", { class: "muted" });
  const error = h("p", { class: "error", role: "alert" });
  const title = h("h1", {}, "연결 중…");
  const controlBtn = h("button", { class: "secondary", hidden: true }, "");
  const endBtn = h("button", { class: "danger", hidden: true }, "세션 종료");

  const canControl = () => session?.allow_control === true;

  const renderHeader = () => {
    if (!session) return;
    title.textContent = session.name;
    controlBtn.hidden = !session.is_owner;
    endBtn.hidden = !session.is_owner;
    controlBtn.textContent = session.allow_control ? "원격 제어 끄기" : "원격 제어 허용";
    img.classList.toggle("controllable", canControl());
  };

  controlBtn.addEventListener("click", async () => {
    if (!session) return;
    session = await api.setControl(session.id, !session.allow_control);
    renderHeader();
  });
  endBtn.addEventListener("click", async () => {
    if (!session || !confirm("세션을 종료할까요? 호스트 앱의 공유도 중단됩니다.")) return;
    await api.endSession(session.id);
    go("#/");
  });

  // ---------- 프레임 표시: 디코딩이 밀리면 중간 프레임은 버리고 최신 것만 ----------
  let showing = false;
  let nextFrame: Blob | null = null;
  let currentUrl: string | null = null;
  const showNext = () => {
    if (!nextFrame) return;
    showing = true;
    const url = URL.createObjectURL(nextFrame);
    nextFrame = null;
    const prev = currentUrl;
    currentUrl = url;
    img.src = url;
    img.decode().catch(() => undefined).finally(() => {
      if (prev) URL.revokeObjectURL(prev);
      showing = false;
      placeholder.hidden = true;
      fpsCount++;
      showNext();
    });
  };
  const pushFrame = (blob: Blob) => {
    nextFrame = blob;
    if (!showing) showNext();
  };

  // ---------- 1) WebSocket 실시간 모드 ----------
  /** 서버가 status 를 보내면 true, 실패/시간초과면 false */
  const connectWs = () =>
    new Promise<boolean>((resolve) => {
      let ready = false;
      const token = auth.token;
      if (!token) return resolve(false);
      let sock: WebSocket;
      try {
        sock = new WebSocket(wsUrl(`/api/ws/view/${encodeURIComponent(sessionId)}`));
      } catch {
        return resolve(false);
      }
      sock.binaryType = "blob";
      const timer = window.setTimeout(() => {
        if (!ready) {
          sock.close();
          resolve(false);
        }
      }, 4000);
      sock.onopen = () => sock.send(JSON.stringify(WsAuth.parse({ type: "auth", token })));
      sock.onmessage = (ev: MessageEvent) => {
        if (ev.data instanceof Blob) return pushFrame(ev.data);
        let parsed;
        try {
          parsed = WsServerMessage.safeParse(JSON.parse(String(ev.data)));
        } catch {
          return;
        }
        if (!parsed.success) return; // 정의되지 않은 메시지는 무시
        const msg = parsed.data;
        if (msg.type === "status") {
          if (!ready) {
            ready = true;
            window.clearTimeout(timer);
            ws = sock;
            mode = "ws";
            resolve(true);
          }
          if (session) session = { ...session, allow_control: msg.allow_control, online: msg.host_online };
          renderHeader();
        } else {
          error.textContent = msg.detail;
          if (msg.detail.includes("종료")) disposed = true;
        }
      };
      sock.onclose = () => {
        window.clearTimeout(timer);
        if (!ready) return resolve(false);
        if (ws === sock) ws = null;
        if (!disposed) void start(); // 끊기면 재연결 (실패 시 HTTP 로 전환)
      };
    });

  // ---------- 2) HTTP 폴링 호환 모드 ----------
  const pollLoop = async () => {
    while (!disposed && mode === "http") {
      try {
        const f = await api.getFrame(sessionId, seq);
        if (f) {
          seq = f.seq;
          const bin = Uint8Array.from(atob(f.data_b64), (c) => c.charCodeAt(0));
          pushFrame(new Blob([bin], { type: f.mime }));
          continue;
        }
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
          error.textContent = e.message;
          return;
        }
        if (e instanceof ApiError && e.status === 401) return go("#/login");
      }
      await new Promise((r) => setTimeout(r, 100));
    }
  };

  const start = async () => {
    mode = "connecting";
    if (await connectWs()) return;
    if (disposed) return;
    mode = "http";
    void pollLoop();
  };

  const metaTimer = window.setInterval(async () => {
    const label = mode === "ws" ? "실시간" : mode === "http" ? "호환 모드(HTTP)" : "연결 중";
    status.textContent = `${fpsCount} fps · ${label} · ${session?.online ? "호스트 온라인" : "호스트 오프라인"}`;
    fpsCount = 0;
    if (mode !== "ws") {
      try {
        session = await api.getSession(sessionId);
        renderHeader();
      } catch {
        /* 다음 주기에 재시도 */
      }
    }
  }, 1000);

  // ---------- 입력 전송 ----------
  const pos = (e: MouseEvent) => {
    const r = img.getBoundingClientRect();
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) };
  };
  const push = (ev: InputEvent) => {
    if (!canControl()) return;
    if (pendingMove) {
      queue.push(pendingMove);
      pendingMove = null;
    }
    queue.push(ev);
    if (mode === "ws") flush(); // 클릭/키 입력은 바로 전송
  };

  img.addEventListener("mousemove", (e) => {
    if (canControl()) pendingMove = { type: "mouse_move", ...pos(e) }; // 마지막 위치만 전송
  });
  img.addEventListener("mousedown", (e) => {
    e.preventDefault();
    img.focus();
    const button = BUTTONS[e.button];
    if (button) push({ type: "mouse_down", ...pos(e), button });
  });
  img.addEventListener("mouseup", (e) => {
    const button = BUTTONS[e.button];
    if (button) push({ type: "mouse_up", ...pos(e), button });
  });
  img.addEventListener("contextmenu", (e) => e.preventDefault());
  img.addEventListener(
    "wheel",
    (e) => {
      if (!canControl()) return;
      e.preventDefault();
      const step = (v: number) => Math.max(-50, Math.min(50, Math.round(-v / 40)));
      const dx = step(e.deltaX);
      const dy = step(e.deltaY);
      if (dx || dy) push({ type: "wheel", dx, dy });
    },
    { passive: false },
  );
  const onKey = (type: "key_down" | "key_up") => (e: KeyboardEvent) => {
    if (document.activeElement !== img || !canControl()) return;
    e.preventDefault();
    if (e.key.length > 32) return;
    push({ type, key: e.key, code: e.code.slice(0, 32) });
  };
  img.addEventListener("keydown", onKey("key_down"));
  img.addEventListener("keyup", onKey("key_up"));

  let sending = false;
  const flush = () => {
    if (pendingMove) {
      queue.push(pendingMove);
      pendingMove = null;
    }
    if (queue.length === 0 || !canControl()) return;
    if (mode === "ws" && ws?.readyState === WebSocket.OPEN) {
      while (queue.length) ws.send(JSON.stringify(WsInput.parse({ type: "input", events: queue.splice(0, 200) })));
      return;
    }
    if (sending || mode !== "http") return;
    const batch = queue.splice(0, 200);
    sending = true;
    api
      .sendInput(sessionId, batch)
      .catch((e: unknown) => {
        error.textContent = e instanceof Error ? e.message : String(e);
      })
      .finally(() => {
        sending = false;
      });
  };
  const flushTimer = window.setInterval(flush, 30);

  const el = h(
    "main",
    { class: "page viewer" },
    h(
      "header",
      { class: "topbar" },
      h("div", {}, h("button", { class: "link", onclick: () => go("#/") }, "← 목록"), title),
      h("div", { class: "actions" }, status, controlBtn, endBtn),
    ),
    error,
    h("p", { class: "muted hint" }, "원격 제어가 허용되면 화면을 클릭한 뒤 마우스/키보드로 조작할 수 있습니다."),
    h("div", { class: "screen-wrap" }, placeholder, img),
  );

  api
    .getSession(sessionId)
    .then((s) => {
      session = s;
      renderHeader();
      void start();
    })
    .catch((e) => {
      error.textContent = e instanceof Error ? e.message : String(e);
    });

  return {
    el,
    dispose: () => {
      disposed = true;
      queue = [];
      ws?.close();
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      window.clearInterval(metaTimer);
      window.clearInterval(flushTimer);
    },
  };
}
