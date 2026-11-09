import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/** 后端地址。可用 `API_TARGET` 覆盖（默认 8000 = make serve 的端口）。 */
const API_TARGET = process.env.API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 监听全部网卡，便于局域网内其他设备访问；后端仍只走本机代理，无需额外开端口
    host: true,
    proxy: {
      // dev 时前端与 API 同源（浏览器只跟 :5173 说话），所以不需要 CORS
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: {
    // 生产构建的预览（vite preview）也要能拿到真实数据 ——
    // 否则验收时看到的是一片「加载失败」。
    port: 4173,
    host: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
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
        //    所以真正的优化手段有三个，都已实施：
        //      1. **不用 antd 的 App 组件** —— 它拉进 message/modal/notification，
        //         实测 +254 KB。我们用不到 App.useApp()。
        //      2. **路由级懒加载** —— ECharts 只在图表页加载。
        //      3. **ECharts 按需引入**（`src/lib/echartsCore.ts`）——
        //         全量入口 1,146 KB → 670 KB（gzip 385 → 227 KB）。
        //         ⚠️ 新增图表类型/组件时必须在那里补注册。
        //
        //    现状：首屏 JS gzip ≈ 190 KB；图表页另拉 227 KB 的共享 chunk。
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
    // ⚠️ 固定测试时区：时间展示已改为「浏览器本地时区」，
    //    不固定的话 CI（通常 UTC）与本机（东八区）断言的时间会差 8 小时。
    env: { TZ: 'Asia/Shanghai' },
    // 限制 worker 数：机器负载高时（CPU 抢占 / I/O 繁忙），
    // 默认按 CPU 核数开 worker 会让测试进程抢不到调度而**卡住**
    // （实测 load average 88 时，默认 16 worker 直接挂住不退出）。
    // 2 个 worker 跑完 57 个文件 / 477 个用例约 110 秒。
    maxWorkers: 2,
    // antd + userEvent 的交互在负载高时偶发超过默认的 5s
    // （实测全量跑曾出现 DataBrowser 用例超时，单独重跑通过）。
    // 放宽到 15s，避免本地并行任务或慢 CI runner 随机变红。
    testTimeout: 15_000,
  },
})
