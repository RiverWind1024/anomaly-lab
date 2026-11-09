import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  DatePicker,
  Input,
  InputNumber,
  Segmented,
  Select,
  message,
} from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { inspectLab, listLabExperiments, evaluateLab, runLab, saveLabExperiment } from '../../api/platform'
import { hint } from '../../components/FieldHint'
import { useCatalog } from '../jobs/queries'
import { ExperimentPanel } from './ExperimentPanel'
import { ExperimentRecords } from './ExperimentRecords'
import { RangeSuggestion } from './RangeSuggestion'
import { TruthEvalPanel } from './TruthEvalPanel'
import { ResultView } from './ResultView'
import {
  DEFAULT_SAMPLING,
  DEFAULT_SQL,
  DEFAULT_SYNTHETIC,
  DETECTOR_OPTIONS,
  METRIC_CLASS_OPTIONS,
  freqSeconds,
  type Kind,
  type LabRequest,
  type SamplingForm,
  type SqlForm,
  type SyntheticForm,
  type TruthKind,
} from './labConstants'
import './lab.css'

export { ResultView }

export function LabPage() {
  const catalog = useCatalog()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  /**
   * 数据源 / 指标 / 时间范围 / 窗口点数进 URL —— 页面可以被收藏、分享，
   * 刷新后还在同一处。
   *
   * ⚠️ 与「指标预览」页同一套做法（见 MetricChartPage）。
   */
  const urlSourceId = params.get('sourceId') ? Number(params.get('sourceId')) : undefined
  const urlMetricId = params.get('metricId') ? Number(params.get('metricId')) : undefined
  const urlStart = params.get('start')
  const urlEnd = params.get('end')
  const urlWindowPoints = params.get('window_points')
    ? Number(params.get('window_points'))
    : undefined

  const [kind, setKind] = useState<Kind>('metric')
  const [sourceId, setSourceId] = useState<number | undefined>(urlSourceId)
  const [metricId, setMetricId] = useState<number | undefined>(urlMetricId)
  const [range, setRange] = useState<[Dayjs, Dayjs]>(() => [
    // ⚠️ URL 里是**毫秒时间戳的字符串** —— `dayjs("1793203380000")` 会得到
    //    Invalid Date，必须先转成数字。
    urlStart ? dayjs(Number(urlStart)) : dayjs().subtract(30, 'day'),
    urlEnd ? dayjs(Number(urlEnd)) : dayjs(),
  ])
  const [sampling, setSampling] = useState<SamplingForm>(() => ({
    ...DEFAULT_SAMPLING,
    window_points: urlWindowPoints ?? DEFAULT_SAMPLING.window_points,
  }))
  const [sqlForm, setSqlForm] = useState<SqlForm>(DEFAULT_SQL)
  const [syntheticForm, setSyntheticForm] = useState<SyntheticForm>(DEFAULT_SYNTHETIC)
  const [truth, setTruth] = useState<TruthKind>('none')
  const [detectors, setDetectors] = useState<string[]>([])

  /** 改 URL 参数 —— 一次改完，避免两次调用互相覆盖。 */
  const setUrlParams = (changes: Record<string, number | undefined>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value === undefined) next.delete(key)
          else next.set(key, String(value))
        }
        return next
      },
      { replace: true },
    )
  }

  const sources = catalog.data?.sources ?? []
  const metrics = catalog.data?.metrics ?? []
  const sourceMetrics = useMemo(
    () => metrics.filter((item) => item.source_id === sourceId),
    [metrics, sourceId],
  )
  const metric = useMemo(
    () => metrics.find((item) => item.id === metricId),
    [metrics, metricId],
  )

  const run = useMutation({
    mutationFn: inspectLab,
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '预检失败')
    },
  })

  const experiment = useMutation({
    mutationFn: runLab,
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '对比实验失败')
    },
  })

  const evaluation = useMutation({
    mutationFn: evaluateLab,
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '有真值评估失败')
    },
  })

  /** 已保存的实验记录 —— 列表页用。 */
  const records = useQuery({
    queryKey: ['lab-experiments'],
    queryFn: listLabExperiments,
  })

  const save = useMutation({
    mutationFn: saveLabExperiment,
    onSuccess: (saved) => {
      message.success(`实验记录已保存：${saved.id}`)
      records.refetch()
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '保存失败')
    },
  })

  /** 把时间范围挪到数据实际所在区间，并重跑一次预检。 */
  const useActualRange = (next: [Dayjs, Dayjs]) => {
    setRange(next)
    setUrlParams({ start: next[0].valueOf(), end: next[1].valueOf() })
    const payload = buildPayload(next)
    if (payload) run.mutate(payload)
  }

  /**
   * 校验数据来源 —— 两个动作共用。
   *
   * @param overrideRange 指定时间范围（不给就用当前选择）
   * @returns 请求体；数据不全时返回 null（并已提示用户）。
   */
  const buildPayload = (
    overrideRange?: [Dayjs, Dayjs],
  ): LabRequest | null => {
    const [from, to] = overrideRange ?? range
    const start = from.toISOString()
    const end = to.toISOString()

    if (kind === 'synthetic') {
      // ⚠️ 合成数据的范围由**点数 × 频率**决定 —— 用户不用选结束时间。
      const span = freqSeconds(syntheticForm.freq) * syntheticForm.n_points
      return {
        kind: 'synthetic',
        start,
        end: from.add(span, 'second').toISOString(),
        freq: syntheticForm.freq,
        truth: 'none',
        synthetic: {
          metric_class: syntheticForm.metric_class,
          n_points: syntheticForm.n_points,
          n_anomalies: syntheticForm.n_anomalies,
          anomaly_types: [],
          seed: syntheticForm.seed,
        },
        sampling: {
          ...sampling,
          // ⚠️ 点数预算不能小于数据本身 —— 否则窗口会被砍掉一半。
          max_points: Math.max(sampling.max_points, syntheticForm.n_points),
        },
      }
    }

    if (kind === 'metric') {
      if (metricId === undefined) {
        message.warning('先选一个指标')
        return null
      }
      return {
        kind: 'metric',
        metric_id: metricId,
        start,
        end,
        truth,
        sampling,
      }
    }

    if (sourceId === undefined) {
      message.warning('先选一个数据源')
      return null
    }
    if (!sqlForm.sql.trim()) {
      message.warning('临时 SQL 不能为空')
      return null
    }
    // ⚠️ 频率当场问 —— 临时 SQL 没有指标可以继承，不给频率切不出窗口。
    if (!sqlForm.freq.trim()) {
      message.warning('临时 SQL 必须给频率，否则无法切窗')
      return null
    }
    return {
      kind: 'sql',
      source_id: sourceId,
      sql: sqlForm.sql,
      time_column: sqlForm.time_column,
      value_column: sqlForm.value_column,
      group_column: sqlForm.group_column || null,
      freq: sqlForm.freq,
      time_format: sqlForm.time_format,
      source_timezone: sqlForm.source_timezone,
      truth,
      start,
      end,
      sampling,
    }
  }

  const submit = () => {
    const payload = buildPayload()
    if (payload) run.mutate(payload)
  }

  const runExperiment = () => {
    const payload = buildPayload()
    if (!payload) return
    // ⚠️ 不选算法 → 后端用 `auto` + 形态推荐的候选
    experiment.mutate(detectors.length ? { ...payload, detectors } : payload)
  }

  /**
   * 有真值评估 —— 校准集选阈值，测试集报 F1。
   *
   * ⚠️ 与「跑对比实验」的区别：那个不需要真值，产出检出画像；
   *    这个需要点级真值，产出 P / R / F1。
   */
  const runEvaluation = () => {
    const payload = buildPayload()
    if (!payload) return
    evaluation.mutate({
      ...payload,
      detectors: detectors.length ? detectors : undefined,
      split_ratio: 0.5,
    })
  }

  /**
   * 保存当前这次实验 —— 落盘成可复现的记录。
   *
   * ⚠️ 记录里存的是**屏幕上看到的**那份结果（后端不重跑），
   *    另附 spec、git sha、依赖版本与结果指纹。
   */
  const saveExperiment = () => {
    const payload = buildPayload()
    if (!payload) return
    if (!experiment.data) {
      message.warning('先跑一次对比实验')
      return
    }
    save.mutate({
      ...payload,
      detectors: detectors.length ? detectors : undefined,
      result: experiment.data,
    })
  }

  /** 从实验记录跳到任务表单（带草稿回填）。 */
  const createJobFrom = (recordId: string) => {
    navigate(`/jobs?experimentId=${encodeURIComponent(recordId)}`)
  }

  return (
    <div className="page">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>指标预检</h1>
        </div>
        <div className="titlebar__actions">
          <Button onClick={submit} loading={run.isPending}>
            开始预检
          </Button>
          <Button
            type="primary"
            onClick={runExperiment}
            loading={experiment.isPending}
            title="在同一批窗口上跑多个算法，产出检出画像"
          >
            跑对比实验
          </Button>
          <Button
            onClick={runEvaluation}
            loading={evaluation.isPending}
            title="校准集选阈值，测试集报 F1 —— 需要这批数据带真值"
          >
            有真值评估
          </Button>
        </div>
      </header>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">数据与范围</h2>
          </div>
        </div>

        <div className="lab-form">
          <label className="lab-form__field">
            <span className="lab-form__label">数据来源</span>
            <Segmented<Kind>
              value={kind}
              onChange={(value) => setKind(value)}
              options={[
                { value: 'metric', label: '已有指标' },
                { value: 'sql', label: '临时 SQL' },
                { value: 'synthetic', label: '合成数据' },
              ]}
            />
          </label>

          {kind !== 'synthetic' ? (
            <label className="lab-form__field">
              <span className="lab-form__label">数据源</span>
              <Select
                style={{ width: 240 }}
                placeholder="选数据源"
                showSearch
                optionFilterProp="label"
                value={sourceId}
                options={sources.map((source) => ({
                  value: source.id,
                  label: `${source.name} · ${source.kind}`,
                }))}
                onChange={(next) => {
                  setSourceId(next)
                  setMetricId(undefined)
                  setUrlParams({ sourceId: next, metricId: undefined })
                }}
              />
            </label>
          ) : null}

          {kind === 'metric' ? (
            <label className="lab-form__field">
              <span className="lab-form__label">指标</span>
              <Select
                style={{ width: 280 }}
                placeholder="选指标"
                showSearch
                optionFilterProp="label"
                disabled={sourceId === undefined}
                value={metricId}
                options={sourceMetrics.map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
                onChange={(next) => {
                  setMetricId(next)
                  setUrlParams({ metricId: next })
                }}
              />
            </label>
          ) : null}

          {kind === 'synthetic' ? (
            <label className="lab-form__field">
              <span className="lab-form__label">起始时间（本地时间）</span>
              <DatePicker
                showTime
                value={range[0]}
                onChange={(value) => {
                  if (!value) return
                  setRange([value, range[1]])
                  setUrlParams({ start: value.valueOf() })
                }}
              />
            </label>
          ) : (
            <label className="lab-form__field">
              <span className="lab-form__label">时间范围（本地时间）</span>
              <DatePicker.RangePicker
                showTime
                allowClear={false}
                value={range}
                onChange={(values) => {
                  if (values?.[0] && values?.[1]) {
                    setRange([values[0], values[1]])
                    setUrlParams({ start: values[0].valueOf(), end: values[1].valueOf() })
                  }
                }}
              />
            </label>
          )}

          {kind !== 'synthetic' ? (
            <label className="lab-form__field">
              <span className="lab-form__label">
                {hint('真值', '人工标注来自标注页 —— 文件名要与序列 id 完全一致。')}
              </span>
              <Segmented<TruthKind>
                value={truth}
                onChange={(value) => setTruth(value)}
                options={[
                  { value: 'none', label: '无真值' },
                  { value: 'annotation', label: '人工标注' },
                ]}
              />
            </label>
          ) : null}
        </div>

        {kind === 'sql' ? (
          <div className="lab-form lab-form--sql">
            <label className="lab-form__field lab-form__field--wide">
              <span className="lab-form__label">SQL（支持 $timefilter）</span>
              <Input.TextArea
                rows={4}
                className="mono"
                placeholder="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts"
                value={sqlForm.sql}
                onChange={(event) => setSqlForm({ ...sqlForm, sql: event.target.value })}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">时间列</span>
              <Input
                value={sqlForm.time_column}
                onChange={(event) => setSqlForm({ ...sqlForm, time_column: event.target.value })}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">值列</span>
              <Input
                value={sqlForm.value_column}
                onChange={(event) => setSqlForm({ ...sqlForm, value_column: event.target.value })}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">分组列（可选）</span>
              <Input
                value={sqlForm.group_column}
                onChange={(event) => setSqlForm({ ...sqlForm, group_column: event.target.value })}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">
                {hint('频率', '切窗必需 —— 临时 SQL 没有指标可以继承频率。')}
              </span>
              <Input
                value={sqlForm.freq}
                onChange={(event) => setSqlForm({ ...sqlForm, freq: event.target.value })}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">时间格式</span>
              <Select
                style={{ width: 160 }}
                value={sqlForm.time_format}
                onChange={(value) => setSqlForm({ ...sqlForm, time_format: value })}
                options={[
                  { value: 'iso_utc', label: 'ISO UTC' },
                  { value: 'iso_naive', label: 'ISO 无时区' },
                  { value: 'epoch_s', label: 'epoch 秒' },
                  { value: 'epoch_ms', label: 'epoch 毫秒' },
                ]}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">源时区</span>
              <Input
                value={sqlForm.source_timezone}
                onChange={(event) =>
                  setSqlForm({ ...sqlForm, source_timezone: event.target.value })
                }
              />
            </label>
          </div>
        ) : null}

        {kind === 'synthetic' ? (
          <div className="lab-form lab-form--sql">
            <label className="lab-form__field">
              <span className="lab-form__label">形态</span>
              <Select
                style={{ width: 180 }}
                value={syntheticForm.metric_class}
                onChange={(value) => setSyntheticForm({ ...syntheticForm, metric_class: value })}
                options={METRIC_CLASS_OPTIONS}
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">点数</span>
              <InputNumber
                min={100}
                step={500}
                value={syntheticForm.n_points}
                onChange={(value) =>
                  setSyntheticForm({
                    ...syntheticForm,
                    n_points: value ?? DEFAULT_SYNTHETIC.n_points,
                  })
                }
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">异常数</span>
              <InputNumber
                min={0}
                value={syntheticForm.n_anomalies}
                onChange={(value) =>
                  setSyntheticForm({
                    ...syntheticForm,
                    n_anomalies: value ?? DEFAULT_SYNTHETIC.n_anomalies,
                  })
                }
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">
                {hint('频率', '合成数据的采样间隔 —— 决定一个窗口有多长。')}
              </span>
              <Input
                value={syntheticForm.freq}
                onChange={(event) =>
                  setSyntheticForm({ ...syntheticForm, freq: event.target.value })
                }
              />
            </label>
            <label className="lab-form__field">
              <span className="lab-form__label">
                {hint('随机种子', '同一个种子生成完全相同的数据与异常 —— 换个种子就换一批。')}
              </span>
              <InputNumber
                value={syntheticForm.seed}
                onChange={(value) =>
                  setSyntheticForm({ ...syntheticForm, seed: value ?? DEFAULT_SYNTHETIC.seed })
                }
              />
            </label>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">采样参数</h2>
          </div>
        </div>
        <div className="lab-form">
          <label className="lab-form__field">
            <span className="lab-form__label">采样模式</span>
            <Select
              style={{ width: 180 }}
              value={sampling.mode}
              onChange={(value) => setSampling({ ...sampling, mode: value })}
              options={[
                { value: 'even', label: '均匀采样' },
                { value: 'recent', label: '最近窗口' },
                { value: 'stratified', label: '分层采样' },
              ]}
            />
          </label>
          <label className="lab-form__field">
            <span className="lab-form__label">
              {hint('窗口点数', '必须与未来任务的窗口一致 —— 否则「预检看到的」不是「上线得到的」。')}
            </span>
            <InputNumber
              min={1}
              value={sampling.window_points}
              onChange={(value) => {
                const points = value ?? DEFAULT_SAMPLING.window_points
                setSampling({ ...sampling, window_points: points })
                setUrlParams({ window_points: points })
              }}
            />
          </label>
          <label className="lab-form__field">
            <span className="lab-form__label">点数预算</span>
            <InputNumber
              min={1}
              value={sampling.max_points}
              onChange={(value) =>
                setSampling({ ...sampling, max_points: value ?? DEFAULT_SAMPLING.max_points })
              }
            />
          </label>
          <label className="lab-form__field">
            <span className="lab-form__label">最多窗口</span>
            <InputNumber
              min={1}
              value={sampling.max_windows}
              onChange={(value) =>
                setSampling({ ...sampling, max_windows: value ?? DEFAULT_SAMPLING.max_windows })
              }
            />
          </label>
          <label className="lab-form__field">
            <span className="lab-form__label">有效点比例</span>
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              value={sampling.min_valid_ratio}
              onChange={(value) =>
                setSampling({
                  ...sampling,
                  min_valid_ratio: value ?? DEFAULT_SAMPLING.min_valid_ratio,
                })
              }
            />
          </label>
        </div>
        {metric ? (
          <p className="panel__foot muted">
            已选指标：<span className="mono">{metric.name}</span> · 查询{' '}
            <span className="mono">{metric.query}</span>
          </p>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">要对比哪些算法</h2>
          </div>
        </div>
        <div className="lab-form">
          <label className="lab-form__field lab-form__field--wide">
            <span className="lab-form__label">算法</span>
            <Select
              mode="multiple"
              allowClear
              style={{ width: '100%', maxWidth: 720 }}
              placeholder="留空则由系统推荐"
              value={detectors}
              options={DETECTOR_OPTIONS}
              onChange={(value) => setDetectors(value)}
            />
          </label>
        </div>
      </section>

      {run.data ? <ResultView result={run.data} /> : null}

      {run.data ? (
        <RangeSuggestion series={run.data.series} onApply={useActualRange} />
      ) : null}

      {run.isPending ? (
        <section className="panel">
          <p className="muted">正在取数、切窗、体检、推断形态…</p>
        </section>
      ) : null}

      {run.isError ? (
        <Alert
          type="error"
          showIcon
          message="预检失败"
          description={run.error instanceof Error ? run.error.message : '未知错误'}
        />
      ) : null}

      {experiment.data ? <ExperimentPanel result={experiment.data} /> : null}

      {experiment.isPending ? (
        <section className="panel">
          <p className="muted">正在同一批窗口上跑各算法…</p>
        </section>
      ) : null}

      {experiment.isError ? (
        <Alert
          type="error"
          showIcon
          message="对比实验失败"
          description={experiment.error instanceof Error ? experiment.error.message : '未知错误'}
        />
      ) : null}

      {evaluation.data ? <TruthEvalPanel result={evaluation.data} /> : null}

      {evaluation.isPending ? (
        <section className="panel">
          <p className="muted">正在校准阈值、并在测试集上算 F1…</p>
        </section>
      ) : null}

      {evaluation.isError ? (
        <Alert
          type="error"
          showIcon
          message="有真值评估失败"
          description={evaluation.error instanceof Error ? evaluation.error.message : '未知错误'}
        />
      ) : null}

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">实验记录</h2>
          </div>
          <Button
            onClick={saveExperiment}
            loading={save.isPending}
            disabled={!experiment.data}
            data-testid="lab-save-experiment"
          >
            保存这次实验
          </Button>
        </div>
        <ExperimentRecords
          records={records.data ?? []}
          loading={records.isPending}
          onCreateJob={createJobFrom}
        />
      </section>

      {!run.data && !experiment.data && !run.isPending && !experiment.isPending ? (
        <section className="panel">
          <p className="muted">
            选好数据与采样参数后点「开始预检」看数据质量，或点「跑对比实验」比算法。
            默认取最近 30 天，每条序列 10k 点预算。
          </p>
        </section>
      ) : null}
    </div>
  )
}
