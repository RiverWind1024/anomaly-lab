import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, message } from 'antd'
import { useCatalog } from '../features/jobs/queries'
import { updateMetric } from '../api/platform'
import { DataBrowser, type BrowserResult } from '../features/sources/DataBrowser'
import { BrowseChart, extractBrowseSeries } from '../features/sources/BrowseChart'
import { normalizeTimeFormat } from '../features/sources/roles'
import { writePreviewPayload } from '../features/metrics/previewBridge'
import { buildMetricPayload } from '../features/metrics/MetricFormFields'
import type { MetricFormValues } from '../features/metrics/MetricFormFields'

/**
 * 预览页把配置带回表单时用的通道。
 *
 * ⚠️ 走 localStorage —— 见 features/metrics/previewBridge.ts 的说明。
 */

/**
 * 指标数据预览页。
 *
 * ⚠️ 为什么独立成页：数据浏览的价值是「写 SQL 时能立刻看到结果」。
 *    塞在数据源详情页里，它就只是个孤立的工具；放进指标的新增/编辑流程，
 *    才是「先看结构、再定指标」。
 *
 * ⚠️ 新标签页打开 —— 原页面那半张填到一半的指标表单不能因此丢掉。
 */
export function MetricPreviewPage() {
  const [params] = useSearchParams()
  const catalog = useCatalog()
  const qc = useQueryClient()

  const sourceId = Number(params.get('sourceId') ?? '0')
  const metricId = params.get('metricId') ? Number(params.get('metricId')) : undefined

  const source = catalog.data?.sources.find((item) => item.id === sourceId)
  const metric = metricId != null
    ? catalog.data?.metrics.find((item) => item.id === metricId)
    : undefined

  /** 跑出来的结果 —— 保存按钮靠它（没跑过就没东西可存）。 */
  const [result, setResult] = useState<BrowserResult | null>(null)

  /**
   * 时序图的标题行 —— 说清楚「画的是什么」。
   *
   * ⚠️ 画的是什么由**角色**决定（用户指派的），不是猜的。
   */
  const chartSummary = useMemo(() => {
    if (!result) return '执行一次查询后显示'
    const value = result.roles.value_column
    const group = result.roles.group_column
    if (!value) return '还没有值列 —— 在下面的列头下拉里指派'
    const seriesCount = extractBrowseSeries({
      rows: result.rows,
      columns: result.columns,
      roles: result.roles,
      timeValues: result.time_values,
    }).length
    return `${value}${group ? ` · 按 ${group} 分组` : ''} · ${seriesCount} 条序列`
  }, [result])

  // 预览页的初始值：地址里的参数优先（那是用户正在编辑的版本）
  const initial = useMemo(() => {
    return {
      // ⚠️ 没有 SQL 时给 undefined —— 让浏览器用它自己的默认语句，
      //    别传空串过去（空 SQL 跑一次只会报错）
      sql: params.get('sql') ?? metric?.query ?? undefined,
      timeColumn: params.get('time_column') ?? metric?.time_column ?? '',
      valueColumn: params.get('value_column') ?? metric?.value_column ?? '',
      groupColumn: params.get('group_column') ?? metric?.group_column ?? '',
      timeFormat: params.get('time_format') ?? metric?.time_format ?? 'iso_utc',
      timezone: params.get('source_timezone') ?? metric?.source_timezone ?? 'UTC',
    }
  }, [params, metric])

  /**
   * 已知列角色 → 列头下拉的初值。
   *
   * ⚠️ 依赖都是字符串 —— 用对象当依赖的话，每次渲染都是新引用，
   *    下拉框会被反复重置。
   */
  const assignments = useMemo(() => {
    const map: Record<string, 'time' | 'value' | 'group'> = {}
    if (initial.timeColumn) map[initial.timeColumn] = 'time'
    if (initial.valueColumn) map[initial.valueColumn] = 'value'
    if (initial.groupColumn) map[initial.groupColumn] = 'group'
    return map
  }, [initial.timeColumn, initial.valueColumn, initial.groupColumn])

  /**
   * 编辑模式：把预览里改好的配置直接存回指标。
   *
   * ⚠️ 指标的其他字段（名称、频率、缺失策略）不在预览页里 ——
   *    要改那些还是回表单，只改取数方式就在这里改完直接存。
   */
  const save = useMutation({
    mutationFn: (payload: BrowserResult) => {
      if (metricId == null || !metric) throw new Error('没有可保存的指标')
      const values: MetricFormValues = {
        source_id: metric.source_id,
        name: metric.name,
        query: payload.sql,
        time_column: payload.roles.time_column ?? '',
        value_column: payload.roles.value_column ?? '',
        group_column: payload.roles.group_column ?? '',
        // ⚠️ INTEGER 的时间列要用 epoch 解释 —— 按 iso 走会静默落到 1970 年
        time_format: normalizeTimeFormat(
          payload.columns,
          payload.roles.time_column,
          payload.time_format,
        ) as MetricFormValues['time_format'],
        source_timezone: payload.source_timezone,
        missing_policy: metric.missing_policy,
        freq: metric.freq,
      }
      return updateMetric(metricId, buildMetricPayload(values))
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
      message.success('已保存到指标')
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '保存失败'),
  })

  /**
   * 新增模式：把配置带回原页面的表单。
   *
   * ⚠️ 走 localStorage + storage 事件 —— 不依赖 window.opener，
   *    那个随时可能被浏览器的隐私设置切断。
   */
  const sendBack = (payload: BrowserResult) => {
    writePreviewPayload({
      sourceId,
      sql: payload.sql,
      columns: payload.columns,
      time_column: payload.roles.time_column,
      value_column: payload.roles.value_column,
      group_column: payload.roles.group_column,
      // ⚠️ INTEGER 的时间列要用 epoch 解释 —— 按 iso 走会静默落到 1970 年
      time_format: normalizeTimeFormat(
        payload.columns,
        payload.roles.time_column,
        payload.time_format,
      ),
    })
    message.success('已带回表单 —— 回到原页面继续')
  }

  if (catalog.isPending) {
    // ⚠️ 等 catalog —— 指标配置在它里面。
    //    急着渲染的话，自动执行会用空 SQL 跑一次，然后就不跑了。
    return (
      <div className="page">
        <header className="titlebar">
          <h1>预览指标数据</h1>
        </header>
        <section className="panel">
          <p className="muted">加载中…</p>
        </section>
      </div>
    )
  }

  if (!source) {
    return (
      <div className="page">
        <header className="titlebar">
          <h1>预览指标数据</h1>
        </header>
        <section className="panel">
          <p className="muted">
            {catalog.isPending ? '加载中…' : '找不到这个数据源 —— 回数据源页重新选一个。'}
          </p>
        </section>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>预览指标数据</h1>
        <div className="titlebar__actions">
          {metric ? (
            <Button
              type="primary"
              disabled={!result}
              loading={save.isPending}
              title={result ? undefined : '先执行一次查询，确认结果没问题再保存'}
              onClick={() => {
                if (result) save.mutate(result)
              }}
            >
              保存到指标「{metric.name}」
            </Button>
          ) : null}
        </div>
      </header>

      {/* ⚠️ 时序图放**最上面** —— 「先看数据长什么样，再看 SQL 怎么写的」。
          图画的是浏览结果本身（原始数据），还没有检测分数与基线带。 */}
      <section className="panel" aria-labelledby="previewChartTitle">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="previewChartTitle">
              时序图
            </h2>
            <p className="panel__meta mono">{chartSummary}</p>
          </div>
        </div>
        <BrowseChart
          rows={result?.rows ?? []}
          columns={result?.columns ?? []}
          roles={result?.roles ?? {}}
          timeValues={result?.time_values ?? null}
        />
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">取数配置</h2>
            <p className="panel__meta mono">
              {source.name} · {source.kind}
              {metric ? ` · 指标 ${metric.name}` : ''}
            </p>
          </div>
        </div>
        <p className="muted">
          改 SQL → 执行 → 看结果。列头下拉决定哪一列是时间列、值列、分组列 ——
          指派对了，指标取到的就是这些列。
        </p>
      </section>

      <DataBrowser
        sourceId={sourceId}
        kind={source.kind}
        initialSql={initial.sql}
        initialTimeColumn={initial.timeColumn}
        initialTimeFormat={initial.timeFormat}
        initialSourceTimezone={initial.timezone}
        initialAssignments={assignments}
        autoRun
        onResult={setResult}
        onUseAsMetric={metric ? undefined : sendBack}
        useAsLabel="带回表单"
      />
    </div>
  )
}
