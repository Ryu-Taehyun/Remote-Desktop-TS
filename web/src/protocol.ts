/**
 * 송수신 타입 정의 (server/schemas.py 와 1:1 대응).
 * 모든 스키마는 .strict() — 정의되지 않은 필드가 있으면 보내지도, 받지도 않는다.
 */
import { z } from "zod";

// ---------- 인증 ----------
export const SignupRequest = z
  .object({
    email: z.string().email(),
    username: z.string().min(2).max(50),
    password: z.string().min(8).max(128),
  })
  .strict();

export const LoginRequest = z
  .object({
    email: z.string().email(),
    password: z.string().min(1).max(128),
  })
  .strict();

export const UserOut = z
  .object({
    id: z.string().uuid(),
    email: z.string().email(),
    username: z.string(),
    created_at: z.string(),
  })
  .strict();

export const TokenResponse = z
  .object({
    access_token: z.string(),
    token_type: z.literal("bearer"),
    user: UserOut,
  })
  .strict();

// ---------- 세션 ----------
export const SessionCreate = z.object({ name: z.string().min(1).max(100), allow_control: z.boolean() }).strict();
export const SessionUpdate = z.object({ allow_control: z.boolean() }).strict();
export const JoinRequest = z.object({ access_code: z.string().min(4).max(12) }).strict();

export const SessionOut = z
  .object({
    id: z.string().uuid(),
    name: z.string(),
    access_code: z.string().nullable(),
    allow_control: z.boolean(),
    online: z.boolean(),
    is_owner: z.boolean(),
    created_at: z.string(),
  })
  .strict();
export const SessionList = z.array(SessionOut);

// ---------- 화면 프레임 ----------
const Mime = z.enum(["image/jpeg", "image/png", "image/webp"]);

export const FrameOut = z
  .object({
    seq: z.number().int(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    mime: Mime,
    data_b64: z.string(),
  })
  .strict();

// ---------- 입력 이벤트 ----------
const Coord = z.number().min(0).max(1);
const MouseButton = z.enum(["left", "right", "middle"]);

export const InputEvent = z.discriminatedUnion("type", [
  z.object({ type: z.literal("mouse_move"), x: Coord, y: Coord }).strict(),
  z.object({ type: z.literal("mouse_down"), x: Coord, y: Coord, button: MouseButton }).strict(),
  z.object({ type: z.literal("mouse_up"), x: Coord, y: Coord, button: MouseButton }).strict(),
  z.object({ type: z.literal("wheel"), dx: z.number().int().min(-50).max(50), dy: z.number().int().min(-50).max(50) }).strict(),
  z.object({ type: z.literal("key_down"), key: z.string().min(1).max(32), code: z.string().max(32) }).strict(),
  z.object({ type: z.literal("key_up"), key: z.string().min(1).max(32), code: z.string().max(32) }).strict(),
]);
export const InputBatch = z.object({ events: z.array(InputEvent).min(1).max(200) }).strict();

export const Ok = z.object({ ok: z.literal(true) }).strict();
export const ErrorBody = z.object({ detail: z.unknown() });

export type SignupRequest = z.infer<typeof SignupRequest>;
export type LoginRequest = z.infer<typeof LoginRequest>;
export type UserOut = z.infer<typeof UserOut>;
export type TokenResponse = z.infer<typeof TokenResponse>;
export type SessionOut = z.infer<typeof SessionOut>;
export type FrameOut = z.infer<typeof FrameOut>;
export type InputEvent = z.infer<typeof InputEvent>;
export type MouseButton = z.infer<typeof MouseButton>;

// ---------- WebSocket 메시지 (실시간 모드) ----------
// 서버 → 뷰어: 바이너리 = JPEG 프레임, 텍스트 = 아래 타입만
export const WsAuth = z.object({ type: z.literal("auth"), token: z.string().min(1).max(4096) }).strict();
export const WsInput = z.object({ type: z.literal("input"), events: z.array(InputEvent).min(1).max(200) }).strict();
export const WsStatus = z
  .object({
    type: z.literal("status"),
    allow_control: z.boolean(),
    host_online: z.boolean(),
    viewers: z.number().int(),
  })
  .strict();
export const WsError = z.object({ type: z.literal("error"), detail: z.string() }).strict();
export const WsServerMessage = z.discriminatedUnion("type", [WsStatus, WsError]);
export type WsServerMessage = z.infer<typeof WsServerMessage>;
