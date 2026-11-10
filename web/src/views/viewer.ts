import { api, ApiError } from "../api";
import { h } from "../dom";
import type { InputEvent, MouseButton, SessionOut } from "../protocol";

const BUTTONS: Record<number, MouseButton> = { 0: "left", 1: "middle", 2: "right" };

/**
 * 원격 화면 뷰어.
 * Vercel 서버리스는 WebSocket 을 유지할 수 없으므로 HTTP 롱폴링 방식:
 *  - 프레임: GET /frame?after=seq 를 반복 (새 프레임 없으면 204)
 *  - 입력: 이벤트를 모아서 80ms 마다 POST /input 배치 전송
 */
export function viewerView(sessionId: string, go: (hash: string) => void): { el: HTMLElement; dispose: () => void } {
  let disposed = false;
  let session: SessionOut | null = null;
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

  // ---------- 프레임 수신 루프 ----------
  const frameLoop = async () => {
    while (!disposed) {
      try {
        const f = await api.getFrame(sessionId, seq);
        if (f) {
          seq = f.seq;
          img.src = `data:${f.mime};base64,${f.data_b64}`;
          placeholder.hidden = true;
          fpsCount++;
          continue; // 바로 다음 프레임 요청
        }
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
          error.textContent = e.message;
          return;
        }
        if (e instanceof ApiError && e.status === 401) return go("#/login");
      }
      await new Promise((r) => setTimeout(r, 200));
    }
  };

  const metaTimer = window.setInterval(async () => {
    status.textContent = `${fpsCount} fps · ${session?.online ? "호스트 온라인" : "호스트 오프라인"}`;
    fpsCount = 0;
    try {
      session = await api.getSession(sessionId);
      renderHeader();
    } catch {
      /* 다음 주기에 재시도 */
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
  const flushTimer = window.setInterval(async () => {
    if (pendingMove) {
      queue.push(pendingMove);
      pendingMove = null;
    }
    if (sending || queue.length === 0 || !canControl()) return;
    const batch = queue.splice(0, 200);
    sending = true;
    try {
      await api.sendInput(sessionId, batch);
    } catch (e) {
      error.textContent = e instanceof Error ? e.message : String(e);
    } finally {
      sending = false;
    }
  }, 80);

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
      void frameLoop();
    })
    .catch((e) => {
      error.textContent = e instanceof Error ? e.message : String(e);
    });

  return {
    el,
    dispose: () => {
      disposed = true;
      queue = [];
      window.clearInterval(metaTimer);
      window.clearInterval(flushTimer);
    },
  };
}
