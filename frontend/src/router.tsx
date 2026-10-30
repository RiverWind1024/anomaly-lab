import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Skeleton } from 'antd'
import { Placeholder } from './pages/Placeholder'

/**
 * 路由表。
 *
 * ⚠️ **页面一律懒加载** —— ECharts 有 1 MB+，只该在需要图的页面加载。
 *
 * 信息架构：数据源 → 指标 → 序列，三级从属。
 * 侧边栏只保留一级入口（「数据源」），指标与序列靠页面内下钻 ——
 * 指标是数据源的子级，平铺成两个一级页面会丢掉这层关系。
 */
const JobsPage = lazy(() => import('./pages/JobsPage').then((m) => ({ default: m.JobsPage })))
const AlertsPage = lazy(() =>
  import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })),
)
const SourcesPage = lazy(() =>
  import('./pages/SourcesPage').then((m) => ({ default: m.SourcesPage })),
)
const SourceDetailPage = lazy(() =>
  import('./pages/SourceDetailPage').then((m) => ({ default: m.SourceDetailPage })),
)
const MetricDetailPage = lazy(() =>
  import('./pages/MetricDetailPage').then((m) => ({ default: m.MetricDetailPage })),
)
const JobDetailPage = lazy(() =>
  import('./pages/JobDetailPage').then((m) => ({ default: m.JobDetailPage })),
)
const EvaluationPage = lazy(() =>
  import('./features/evaluation/EvaluationPage').then((m) => ({ default: m.EvaluationPage })),
)
const DetectionsPage = lazy(() =>
  import('./features/detections/DetectionsPage').then((m) => ({ default: m.DetectionsPage })),
)
const AnnotatePage = lazy(() =>
  import('./features/annotate/AnnotatePage').then((m) => ({ default: m.AnnotatePage })),
)

export function AppRoutes() {
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
      <Routes>
        {/* 旧的「序列总览」已删 —— 合成序列并入「检测记录」页 */}
        <Route path="/" element={<Navigate to="/sources" replace />} />
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
        <Route path="/metrics/:metricId" element={<MetricDetailPage />} />
        {/* 旧的平级「指标」页 → 指标现在是数据源的子级 */}
        <Route path="/metrics" element={<Navigate to="/sources" replace />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/runs" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/detections" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/feedback" element={<JobDetailPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="/detections" element={<DetectionsPage />} />
        <Route path="/annotate" element={<AnnotatePage />} />
        {/* 旧 URL 兼容：/report → /evaluation，/platform → /jobs，/badcases → /detections */}
        <Route path="/report" element={<Navigate to="/evaluation" replace />} />
        <Route path="/platform" element={<Navigate to="/jobs" replace />} />
        <Route path="/badcases" element={<Navigate to="/detections" replace />} />
        <Route path="*" element={<Placeholder title="页面不存在" />} />
      </Routes>
    </Suspense>
  )
}
