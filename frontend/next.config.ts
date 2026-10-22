import type { NextConfig } from "next";

/**
 * 后端地址走环境变量，默认 8200。
 *
 * 为什么不用 8000：本机还有别的项目（lab_agent_std）也占 8000，
 * 两边一起开发会互相顶掉。换端口只需设 BACKEND_ORIGIN，不用改代码
 * （后端端口同理，见 backend/main.py 的 API_PORT）。
 */
const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8200";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
