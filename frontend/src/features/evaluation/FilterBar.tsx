import { Button, DatePicker, Select, Space } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { distinctValues, type EvaluationFilters } from './filters'
import type { EvaluationRow } from '../../api/types'

const { RangePicker } = DatePicker

export interface FilterBarProps {
  /** 全部记录 —— 候选值从这里汇总。 */
  rows: EvaluationRow[]
  filters: EvaluationFilters
  onChange: (next: EvaluationFilters) => void
}

/** 字符串区间 → dayjs 区间（受控用）。 */
function toRange(filters: EvaluationFilters): [Dayjs | null, Dayjs | null] | null {
  if (!filters.since && !filters.until) return null
  return [
    filters.since ? dayjs(filters.since) : null,
    filters.until ? dayjs(filters.until) : null,
  ]
}

/**
 * 筛选栏：时间范围 / 检测算法 / 形态 / 来源。
 *
 * ⚠️ **评估页与检测记录页共用这一个** —— 同一套筛选逻辑分两处维护必然漂移，
 *    而这两个页面看的是**同一份数据**。
 */
export function FilterBar({ rows, filters, onChange }: FilterBarProps) {
  const hasFilters = Object.values(filters).some((value) => value !== undefined)

  return (
    <Space wrap>
      <RangePicker
        showTime
        // ⚠️ **受控** —— 不受控的话「重置」清掉了 filters，
        //    但输入框里还显示着旧的时间范围，看着像没生效。
        value={toRange(filters)}
        placeholder={['开始时间', '结束时间']}
        onChange={(range) => {
          const [from, to] = range ?? []
          onChange({
            ...filters,
            since: from ? from.format('YYYY-MM-DDTHH:mm:ss') : undefined,
            until: to ? to.format('YYYY-MM-DDTHH:mm:ss') : undefined,
          })
        }}
      />
      <Select
        allowClear
        placeholder="全部算法"
        style={{ width: 150 }}
        value={filters.detector}
        onChange={(value) => onChange({ ...filters, detector: value })}
        options={distinctValues(rows, (row) => row.detector).map((v) => ({
          value: v,
          label: v,
        }))}
      />
      <Select
        allowClear
        placeholder="全部形态"
        style={{ width: 150 }}
        value={filters.metricClass}
        onChange={(value) => onChange({ ...filters, metricClass: value })}
        options={distinctValues(rows, (row) => row.metric_class).map((v) => ({
          value: v,
          label: v,
        }))}
      />
      <Select
        allowClear
        placeholder="全部来源"
        style={{ width: 150 }}
        value={filters.source}
        onChange={(value) => onChange({ ...filters, source: value })}
        options={distinctValues(rows, (row) => row.source ?? '').map((v) => ({
          value: v,
          label: v,
        }))}
      />
      {hasFilters ? (
        <Button size="small" onClick={() => onChange({})}>
          重置
        </Button>
      ) : null}
    </Space>
  )
}
