import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Skeleton } from 'antd'
import { Placeholder } from './pages/Placeholder'

/**
 * 路由表（8 个页面，路径与 spec §8.2-A 一致）。
 *
 * ⚠️ **页面一律懒加载** —— ECharts 有 1 MB+，只该在任务详情页加载。
 *    序列总览（首屏）不该为图表库买单。
 */
const SeriesOverviewPage = lazy(() =>
  import('./pages/SeriesOverviewPage').then((m) => ({ default: m.SeriesOverviewPage })),
)
const JobsPage = lazy(() => import('./pages/JobsPage').then((m) => ({ default: m.JobsPage })))
const JobDetailPage = lazy(() =>
  import('./pages/JobDetailPage').then((m) => ({ default: m.JobDetailPage })),
)
const EvaluationPage = lazy(() =>
  import('./pages/EvaluationPage').then((m) => ({ default: m.EvaluationPage })),
)
const BadCasesPage = lazy(() =>
  import('./pages/BadCasesPage').then((m) => ({ default: m.BadCasesPage })),
)
const AnnotatePage = lazy(() =>
  import('./pages/AnnotatePage').then((m) => ({ default: m.AnnotatePage })),
)

export function AppRoutes() {
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
      <Routes>
        <Route path="/" element={<SeriesOverviewPage />} />
        <Route path="/sources" element={<Placeholder title="数据源" />} />
        <Route path="/metrics" element={<Placeholder title="指标" />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="/badcases" element={<BadCasesPage />} />
        <Route path="/annotate" element={<AnnotatePage />} />
        {/* 旧 URL 兼容：/report → /evaluation，/platform → /jobs */}
        <Route path="/report" element={<Navigate to="/evaluation" replace />} />
        <Route path="/platform" element={<Navigate to="/jobs" replace />} />
        <Route path="*" element={<Placeholder title="页面不存在" />} />
      </Routes>
    </Suspense>
  )
}
