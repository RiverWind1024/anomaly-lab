import { Alert, Button } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { fmtUtcTime } from '../../lib/format'
import type { LabSeries } from '../../api/types'

/**
 * 「时间范围没覆盖到实际数据」的纠正提示。
 *
 * ⚠️ 为什么单独抽出来：这段逻辑有两处容易出错 ——
 *    区间怎么算（多序列取并集）、点了之后请求体带的是不是新区间。
 *    拆成纯函数 + 独立组件，才能被单测真正覆盖。
 */

/**
 * 数据实际覆盖的区间 —— 多条序列取**并集**。
 *
 * ⚠️ 用并集而不是第一条序列的区间 ——
 *    分组指标各序列的起止可能不同，取并集才不会漏掉一部分序列。
 *
 * @returns 没有可用区间时返回 null（数据为空或都没取到时间戳）
 */
export function actualRangeOf(series: LabSeries[]): { start: Dayjs; end: Dayjs } | null {
  const spans = series.filter((item) => item.data_start && item.data_end)
  if (!spans.length) return null
  const starts = spans.map((item) => dayjs(item.data_start as string).valueOf())
  const ends = spans.map((item) => dayjs(item.data_end as string).valueOf())
  return {
    start: dayjs(Math.min(...starts)),
    end: dayjs(Math.max(...ends)),
  }
}

export interface RangeSuggestionProps {
  series: LabSeries[]
  /** 用户点了「按实际范围重跑」—— 把新区间交回去。 */
  onApply: (range: [Dayjs, Dayjs]) => void
}

export function RangeSuggestion({ series, onApply }: RangeSuggestionProps) {
  const range = actualRangeOf(series)
  if (!range) return null

  return (
    <Alert
      type="info"
      showIcon
      message="时间范围可能没覆盖到实际数据"
      description={
        <span>
          数据实际覆盖 {fmtUtcTime(range.start.toISOString())} →{' '}
          {fmtUtcTime(range.end.toISOString())}。切到这段区间，采样窗口才不会落空。
          <span style={{ marginLeft: 12 }}>
            <Button size="small" onClick={() => onApply([range.start, range.end])}>
              按实际范围重跑
            </Button>
          </span>
        </span>
      }
    />
  )
}
