import { api, ApiError, auth } from "../api";
import { h } from "../dom";
import { LoginRequest, SignupRequest } from "../protocol";

export function authView(onDone: () => void): HTMLElement {
  let mode: "login" | "signup" = "login";
  const error = h("p", { class: "error", role: "alert" });
  const usernameRow = h("label", {}, "이름", h("input", { name: "username", autocomplete: "nickname" }));
  const submit = h("button", { type: "submit", class: "primary" }, "로그인");
  const toggle = h("button", { type: "button", class: "link" }, "계정이 없나요? 회원가입");
  const title = h("h1", {}, "로그인");

  const form = h(
    "form",
    { class: "card auth" },
    title,
    h("label", {}, "이메일", h("input", { name: "email", type: "email", required: true, autocomplete: "email" })),
    usernameRow,
    h(
      "label",
      {},
      "비밀번호",
      h("input", { name: "password", type: "password", required: true, autocomplete: "current-password" }),
    ),
    error,
    submit,
    toggle,
  );

  const render = () => {
    const signup = mode === "signup";
    title.textContent = signup ? "회원가입" : "로그인";
    submit.textContent = signup ? "가입하기" : "로그인";
    toggle.textContent = signup ? "이미 계정이 있나요? 로그인" : "계정이 없나요? 회원가입";
    usernameRow.hidden = !signup;
    error.textContent = "";
  };
  toggle.addEventListener("click", () => {
    mode = mode === "login" ? "signup" : "login";
    render();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const email = String(fd.get("email") ?? "").trim();
    const username = String(fd.get("username") ?? "").trim();
    const password = String(fd.get("password") ?? "");

    // 클라이언트 측 타입 검증 (서버도 동일 규칙으로 재검증)
    const names: Record<string, string> = { email: "이메일", username: "이름(2자 이상)", password: "비밀번호(8자 이상)" };
    const fail = (issues: { path: (string | number)[] }[]) => {
      const field = String(issues[0]?.path[0] ?? "");
      error.textContent = `${names[field] ?? field} 형식을 확인하세요`;
    };

    submit.disabled = true;
    try {
      let res;
      if (mode === "signup") {
        const p = SignupRequest.safeParse({ email, username, password });
        if (!p.success) return fail(p.error.issues);
        res = await api.signup(p.data);
      } else {
        const p = LoginRequest.safeParse({ email, password });
        if (!p.success) return fail(p.error.issues);
        res = await api.login(p.data);
      }
      auth.token = res.access_token;
      onDone();
    } catch (err) {
      error.textContent = err instanceof ApiError ? err.message : "서버에 연결할 수 없습니다";
    } finally {
      submit.disabled = false;
    }
  });

  render();
  return h("main", { class: "center" }, form);
}
