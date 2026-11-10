import { api, ApiError, auth } from "../api";
import { h } from "../dom";
import type { SessionOut, UserOut } from "../protocol";

export function dashboardView(user: UserOut, go: (hash: string) => void): { el: HTMLElement; dispose: () => void } {
  const list = h("div", { class: "sessions" });
  const error = h("p", { class: "error", role: "alert" });
  const codeInput = h("input", { placeholder: "접속 코드 (예: AB3K9QXZ)", maxlength: "12", autocomplete: "off" });

  const row = (s: SessionOut) =>
    h(
      "div",
      { class: "session-row" },
      h(
        "div",
        {},
        h("strong", {}, s.name),
        h("span", { class: s.online ? "badge on" : "badge" }, s.online ? "온라인" : "오프라인"),
        s.is_owner ? h("span", { class: "badge mine" }, "내 PC") : null,
        s.access_code ? h("div", { class: "muted" }, "접속 코드: ", h("code", {}, s.access_code)) : null,
      ),
      h("button", { class: "primary", onclick: () => go(`#/view/${s.id}`) }, "보기"),
    );

  const refresh = async () => {
    try {
      const sessions = await api.listSessions();
      list.replaceChildren(
        ...(sessions.length
          ? sessions.map(row)
          : [h("p", { class: "muted" }, "아직 세션이 없습니다. 호스트 PC 에서 Python 앱으로 세션을 만들거나, 접속 코드로 참여하세요.")]),
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return go("#/login");
      error.textContent = e instanceof Error ? e.message : String(e);
    }
  };

  const join = h(
    "form",
    {
      class: "join",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        error.textContent = "";
        try {
          const s = await api.joinSession(codeInput.value.trim());
          go(`#/view/${s.id}`);
        } catch (err) {
          error.textContent = err instanceof Error ? err.message : String(err);
        }
      },
    },
    codeInput,
    h("button", { type: "submit", class: "primary" }, "참여"),
  );

  const el = h(
    "main",
    { class: "page" },
    h(
      "header",
      { class: "topbar" },
      h("h1", {}, "원격 데스크톱"),
      h(
        "div",
        {},
        h("span", { class: "muted" }, `${user.username} (${user.email})`),
        h(
          "button",
          {
            class: "link",
            onclick: () => {
              auth.token = null;
              go("#/login");
            },
          },
          "로그아웃",
        ),
      ),
    ),
    h("section", { class: "card" }, h("h2", {}, "접속 코드로 참여"), join, error),
    h("section", { class: "card" }, h("h2", {}, "세션 목록"), list),
  );

  void refresh();
  const timer = window.setInterval(refresh, 5000);
  return { el, dispose: () => window.clearInterval(timer) };
}
