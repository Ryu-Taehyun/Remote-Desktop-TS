import "./style.css";
import { api, auth } from "./api";
import { h, mount } from "./dom";
import { authView } from "./views/auth";
import { dashboardView } from "./views/dashboard";
import { viewerView } from "./views/viewer";

const root = document.getElementById("app")!;
let dispose: (() => void) | null = null;

const go = (hash: string) => {
  if (location.hash === hash) void route();
  else location.hash = hash;
};

async function route(): Promise<void> {
  dispose?.();
  dispose = null;
  const hash = location.hash || "#/";

  if (!auth.token || hash === "#/login") {
    auth.token = null;
    return mount(root, authView(() => go("#/")));
  }

  let user;
  try {
    user = await api.me();
  } catch {
    auth.token = null;
    return go("#/login");
  }

  const viewMatch = /^#\/view\/([0-9a-f-]{36})$/.exec(hash);
  if (viewMatch?.[1]) {
    const v = viewerView(viewMatch[1], go);
    dispose = v.dispose;
    return mount(root, v.el);
  }
  const d = dashboardView(user, go);
  dispose = d.dispose;
  mount(root, d.el);
}

window.addEventListener("hashchange", () => void route());
mount(root, h("p", { class: "center muted" }, "로딩 중…"));
void route();
