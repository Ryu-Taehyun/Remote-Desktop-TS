import { defineConfig } from "vite";

// 개발 서버(npm run dev): /api 요청(WebSocket 포함)을 uvicorn(8000)으로 프록시.
// 운영: npm run build 후 FastAPI 가 web/dist 를 직접 서비스하므로 프록시가 필요 없다.
export default defineConfig({
  server: {
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
  preview: {
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
});
