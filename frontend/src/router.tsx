import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Skeleton } from 'antd'
import { Placeholder } from './pages/Placeholder'

/**
 * 路由表。
 *
 * ⚠️ **页面一律懒加载** —— ECharts 有 1 MB+，只该在需要图的页面加载。
 *
 * 信息架构：数据（分组）→ 数据源 → 指标 → 序列。
 * 侧边栏「数据」是**分组**，下面是「数据源」与「指标」两个平级页面；
 * 序列靠页面内下钻 —— 指标是数据源的从属，平铺成一级入口会丢掉这层关系。
 */
const JobsPage = lazy(() => import('./pages/JobsPage').then((m) => ({ default: m.JobsPage })))
const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const AlertsPage = lazy(() =>
  import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })),
)
const SourcesPage = lazy(() =>
  import('./pages/SourcesPage').then((m) => ({ default: m.SourcesPage })),
)
const SourceDetailPage = lazy(() =>
  import('./pages/SourceDetailPage').then((m) => ({ default: m.SourceDetailPage })),
)
const MetricsPage = lazy(() =>
  import('./pages/MetricsPage').then((m) => ({ default: m.MetricsPage })),
)
const MetricFormPage = lazy(() =>
  import('./pages/MetricFormPage').then((m) => ({ default: m.MetricFormPage })),
)
const MetricDetailPage = lazy(() =>
  import('./pages/MetricDetailPage').then((m) => ({ default: m.MetricDetailPage })),
)
const MetricPreviewPage = lazy(() =>
  import('./pages/MetricPreviewPage').then((m) => ({ default: m.MetricPreviewPage })),
)
const MetricChartPage = lazy(() =>
  import('./pages/MetricChartPage').then((m) => ({ default: m.MetricChartPage })),
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
const LabPage = lazy(() =>
  import('./features/lab/LabPage').then((m) => ({ default: m.LabPage })),
)
const MonitoringPage = lazy(() =>
  import('./features/monitoring/MonitoringPage').then((m) => ({ default: m.MonitoringPage })),
)

export function AppRoutes() {
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
      <Routes>
        {/* 旧的「序列总览」已删 —— 合成序列并入「检测记录」页；首页是概览 */}
        <Route path="/" element={<DashboardPage />} />
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
        {/* 指标：列表 / 新增 / 编辑 / 详情 */}
        <Route path="/metrics" element={<MetricsPage />} />
        {/* ⚠️ 静态段要声明在 `/metrics/:metricId` **之前** ——
            否则 "preview" 会被当成 metricId。 */}
        <Route path="/metrics/preview" element={<MetricChartPage />} />
        <Route path="/metrics/new" element={<MetricFormPage />} />
        <Route path="/metrics/:metricId/edit" element={<MetricFormPage />} />
        <Route path="/metrics/:metricId" element={<MetricDetailPage />} />
        {/* 指标取数预览 —— 从指标的新增/编辑表单里开新标签页跳过来 */}
        <Route path="/metric-preview" element={<MetricPreviewPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/test" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/runs" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/detections" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/feedback" element={<JobDetailPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="/detections" element={<DetectionsPage />} />
        <Route path="/annotate" element={<AnnotatePage />} />
        <Route path="/lab" element={<LabPage />} />
        <Route path="/monitoring" element={<MonitoringPage />} />
        {/* 旧 URL 兼容：/report → /evaluation，/platform → /jobs，/badcases → /detections */}
        <Route path="/report" element={<Navigate to="/evaluation" replace />} />
        <Route path="/platform" element={<Navigate to="/jobs" replace />} />
        <Route path="/badcases" element={<Navigate to="/detections" replace />} />
        <Route path="*" element={<Placeholder title="页面不存在" />} />
      </Routes>
    </Suspense>
  )
}
