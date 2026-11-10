import { defineConfig } from "vite";

// 로컬 개발 시 /api 요청(WebSocket 포함)을 uvicorn(8000)으로 프록시. Vercel 에서는 같은 도메인의 /api 함수가 처리.
export default defineConfig({
  server: {
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
  preview: {
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
});
