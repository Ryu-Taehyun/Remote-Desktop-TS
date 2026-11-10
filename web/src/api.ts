/**
 * 타입 안전 API 클라이언트.
 * - 요청 본문은 전송 전에 스키마로 검증(parse)되어 정의된 필드만 나간다.
 * - 응답 본문도 스키마로 검증되어, 예상과 다른 데이터는 예외로 처리된다.
 */
import { z } from "zod";
import * as P from "./protocol";

const TOKEN_KEY = "rd_token";
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const auth = {
  get token(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set token(v: string | null) {
    try {
      if (v) localStorage.setItem(TOKEN_KEY, v);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* 저장소 사용 불가 시 무시 */
    }
  },
};

function errorMessage(body: unknown, status: number): string {
  const parsed = P.ErrorBody.safeParse(body);
  if (!parsed.success) return `요청 실패 (${status})`;
  const d = parsed.data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return "입력값을 확인하세요: " + d.map((e) => (e as { msg?: string }).msg ?? "").join(", ");
  return `요청 실패 (${status})`;
}

async function request<Req extends z.ZodTypeAny, Res extends z.ZodTypeAny>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  res: Res,
  req?: { schema: Req; body: z.input<Req> },
  opts: { allowNoContent?: boolean } = {},
): Promise<z.infer<Res> | null> {
  const headers: Record<string, string> = {};
  const token = auth.token;
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: string | undefined;
  if (req) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(req.schema.parse(req.body));
  }
  const r = await fetch(API_BASE + path, { method, headers, body });
  if (r.status === 204 && opts.allowNoContent) return null;
  const json: unknown = await r.json().catch(() => null);
  if (!r.ok) {
    if (r.status === 401) auth.token = null;
    throw new ApiError(r.status, errorMessage(json, r.status));
  }
  return res.parse(json) as z.infer<Res>;
}

// null 을 반환하지 않는 호출용 헬퍼
async function must<T>(p: Promise<T | null>): Promise<T> {
  const v = await p;
  if (v === null) throw new ApiError(204, "응답이 비어 있습니다");
  return v;
}

export const api = {
  signup: (body: P.SignupRequest) =>
    must(request("POST", "/api/auth/signup", P.TokenResponse, { schema: P.SignupRequest, body })),
  login: (body: P.LoginRequest) =>
    must(request("POST", "/api/auth/login", P.TokenResponse, { schema: P.LoginRequest, body })),
  me: () => must(request("GET", "/api/auth/me", P.UserOut)),

  listSessions: () => must(request("GET", "/api/sessions", P.SessionList)),
  createSession: (name: string, allow_control: boolean) =>
    must(request("POST", "/api/sessions", P.SessionOut, { schema: P.SessionCreate, body: { name, allow_control } })),
  joinSession: (access_code: string) =>
    must(request("POST", "/api/sessions/join", P.SessionOut, { schema: P.JoinRequest, body: { access_code } })),
  getSession: (id: string) => must(request("GET", `/api/sessions/${encodeURIComponent(id)}`, P.SessionOut)),
  setControl: (id: string, allow_control: boolean) =>
    must(
      request("PATCH", `/api/sessions/${encodeURIComponent(id)}`, P.SessionOut, {
        schema: P.SessionUpdate,
        body: { allow_control },
      }),
    ),
  endSession: (id: string) => must(request("DELETE", `/api/sessions/${encodeURIComponent(id)}`, P.Ok)),

  /** 새 프레임이 없으면 null */
  getFrame: (id: string, after: number) =>
    request("GET", `/api/sessions/${encodeURIComponent(id)}/frame?after=${after}`, P.FrameOut, undefined, {
      allowNoContent: true,
    }),
  sendInput: (id: string, events: P.InputEvent[]) =>
    must(
      request("POST", `/api/sessions/${encodeURIComponent(id)}/input`, P.Ok, {
        schema: P.InputBatch,
        body: { events },
      }),
    ),
};
