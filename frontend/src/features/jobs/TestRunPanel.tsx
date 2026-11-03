import { useMemo, useState } from 'react'
import { Alert, Button, Empty, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PreviewChart } from './PreviewChart'
import { AlertRulesView } from './AlertRulesView'
import { useTestRunJob } from './queries'
import type { TestRunAlert, TestRunSeries } from '../../api/types'

export interface TestRunPanelProps {
  jobId: number
}

/**
 * 试跑面板 —— 「跑一次看看会不会告警，但不留痕」。
 *
 * ⚠️ **试跑不落库** —— 没有 run 记录、不写结果文件、
 *    也不会出现在告警记录。它只是「现在跑一下会得到什么」。
 *
 * ⚠️ 与「立即运行」的区别要说清楚：
 *    立即运行 = 真的产生一条运行记录（进告警记录、进历史）；
 *    试跑 = 只看一眼结果，什么都不留。
 */
export function TestRunPanel({ jobId }: TestRunPanelProps) {
  const testRun = useTestRunJob()
  const [seriesId, setSeriesId] = useState<string | undefined>(undefined)

  const result = testRun.data

  /** 当前要看的序列 —— 默认第一条够用的。 */
  const current: TestRunSeries | undefined = useMemo(() => {
    if (!result) return undefined
    const usable = result.results.filter((item) => item.sufficient)
    if (usable.length === 0) return undefined
    return usable.find((item) => item.series_id === seriesId) ?? usable[0]
  }, [result, seriesId])

  const alertColumns: ColumnsType<TestRunAlert> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 200,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '值',
      dataIndex: 'value',
      key: 'value',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{value.toFixed(3)}</span>,
    },
    {
      title: '分数',
      dataIndex: 'score',
      key: 'score',
      width: 100,
      align: 'right',
      render: (value: number) => <span className="mono">{value.toFixed(3)}</span>,
    },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      render: (value: string, row) => (
        <Tag color={row.severity >= 2 ? 'error' : 'warning'}>{value}</Tag>
      ),
    },
  ]

  return (
    <div className="test-run">
      <div className="job-runs__toolbar">
        <span className="muted">
          {result
            ? `${result.n_series} 条序列 · ${result.n_alerts} 个告警点 · ${result.n_p0} 个 P0`
            : '试跑不会产生运行记录，也不会进告警记录 —— 只是看一眼结果。'}
        </span>
        <Space>
          {result && result.series.length > 1 ? (
            <Select
              value={current?.series_id}
              onChange={(value) => setSeriesId(value as string)}
              options={result.series.map((item) => ({
                value: item.series_id,
                label: `${item.series_id} (${item.sufficient ? `${item.n_alerts} 告警` : '数据不足'})`,
              }))}
              style={{ minWidth: 280 }}
            />
          ) : null}
          <Button
            type="primary"
            loading={testRun.isPending}
            onClick={() => testRun.mutate(jobId)}
          >
            {result ? '再试一次' : '试跑一次'}
          </Button>
        </Space>
      </div>

      {testRun.error instanceof Error && (
        <Alert
          type="error"
          showIcon
          message="试跑失败"
          description={testRun.error.message}
          style={{ marginBottom: 12 }}
        />
      )}

      {result ? (
        <>
          {/* 规则表与阈值 —— 告警是怎么判出来的，得看得见 */}
          <section className="test-run__rules">
            <AlertRulesView rules={result.alert_rules} />
            <p className="muted">
              实际使用的检测器：<span className="mono">{result.detector}</span>
              {result.requested_detector !== result.detector ? (
                <>
                  {' '}
                  （任务里配的是 <span className="mono">{result.requested_detector}</span>）
                </>
              ) : null}
              {result.detector_rationale ? ` —— ${result.detector_rationale}` : null}
            </p>
          </section>

          {current ? (
            <PreviewChart
              timestamps={current.timestamps}
              values={current.values}
              scores={current.scores}
              baseline={current.baseline}
              lower={current.lower}
              upper={current.upper}
              severity={current.severity}
              alertThreshold={result.alert_threshold}
              criticalThreshold={result.critical_threshold}
              levels={result.levels}
            />
          ) : (
            <Empty description="没有足够的点来做检测" />
          )}

          <section className="test-run__alerts">
            <h3 className="section__title">告警点（{result.alerts.length}）</h3>
            {result.alerts.length === 0 ? (
              <p className="muted">
                当前阈值下没有告警点 —— 数值都在正常带里。
              </p>
            ) : (
              <Table<TestRunAlert>
                rowKey={(row) => `${row.series_id}:${row.index}`}
                columns={alertColumns}
                dataSource={result.alerts}
                size="small"
                pagination={{ pageSize: 20, showSizeChanger: false }}
                scroll={{ x: 'max-content' }}
              />
            )}
          </section>
        </>
      ) : (
        <Empty description="还没试跑过 —— 点「试跑一次」看看现在跑会得到什么" />
      )}
    </div>
  )
}
