// /api/* is proxied to the FastAPI layer (`make api`, tempo/api/server.py).
const API = process.env.TEMPO_API_URL || "http://127.0.0.1:8000";

export default {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
