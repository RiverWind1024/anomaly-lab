import { Navigate, Route, Routes } from 'react-router-dom'
import { Placeholder } from './pages/Placeholder'

/**
 * 路由表（8 个页面，路径与 spec §8.2-A 一致）。
 *
 * Task 7 起逐个把 Placeholder 换成真页面。
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder title="序列总览" />} />
      <Route path="/sources" element={<Placeholder title="数据源" />} />
      <Route path="/metrics" element={<Placeholder title="指标" />} />
      <Route path="/jobs" element={<Placeholder title="检测任务" />} />
      <Route path="/jobs/:jobId" element={<Placeholder title="检测任务 · 详情与预览" />} />
      <Route path="/evaluation" element={<Placeholder title="评估报告" />} />
      <Route path="/badcases" element={<Placeholder title="Bad Case" />} />
      <Route path="/annotate" element={<Placeholder title="标注" />} />
      {/* 旧 URL 兼容：/report → /evaluation，/platform → /jobs */}
      <Route path="/report" element={<Navigate to="/evaluation" replace />} />
      <Route path="/platform" element={<Navigate to="/jobs" replace />} />
      <Route path="*" element={<Placeholder title="页面不存在" />} />
    </Routes>
  )
}
