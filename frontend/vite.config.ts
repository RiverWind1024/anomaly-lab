import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/** 后端地址。可用 `API_TARGET` 覆盖（默认 8000 = make serve 的端口）。 */
const API_TARGET = process.env.API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // dev 时前端与 API 同源（浏览器只跟 :5173 说话），所以不需要 CORS
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // ⚠️ **不要**把 antd 放进 manualChunks —— 那会强制把全部 antd 组件打进
        //    一个 chunk，反而**阻止**了 tree-shaking（实测 800 KB vs 389 KB）。
        //
        //    AntD v5 的 bundle 成本（实测 vite 7 + antd 5，未压缩）：
        //      纯 react              142 KB
        //      + antd/locale/zh_CN   150 KB（+8 KB，locale 本身很轻）
        //      + ConfigProvider      218 KB（+76 KB）
        //      + Table               350 KB（Table 的 style 依赖链会拖进
        //                                rc-tree / rc-select / rc-input）
        //      + antd App            396 KB（App 额外拉进 message/modal/notification）
        //
        //    ConfigProvider 因运行时 validateMessages 配置而引入 rc-field-form，
        //    **静态摇树消不掉**（AntD 官方已知问题，见 ant-design#41607）。
        //    路径引入（antd/es/table）与 barrel 引入差别 <20 KB，不值得为它改写法。
        //
        //    所以真正的优化手段只有两个，都已实施：
        //      1. **不用 antd 的 App 组件** —— 它拉进 message/modal/notification，
        //         实测 +254 KB。我们用不到 App.useApp()。
        //      2. **路由级懒加载** —— ECharts 有 1 MB+，只该在任务详情页加载。
        //
        //    现状：全部 chunk gzip 合计 ≈ 288 KB，首屏 ≈ 287 KB。
        //    对内部监控工具可接受；不再为 AntD 的固有成本继续挖。
        manualChunks(id) {
          // 只把 React 核心拆出来（它变动最少，缓存收益最大）
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react/')) {
            return 'react'
          }
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 限制 worker 数：机器负载高时（CPU 抢占 / I/O 繁忙），
    // 默认按 CPU 核数开 worker 会让测试进程抢不到调度而**卡住**
    // （实测 load average 88 时，默认 16 worker 直接挂住不退出）。
    // 2 个 worker 跑完 78 个用例只要 6 秒，没必要开更多。
    maxWorkers: 2,
  },
})
