/**
 * 单窗口时序图 —— 图上标的告警点必须与数字对得上。
 */

import { describe, expect, it } from 'vitest'
import { buildWindowOption } from './WindowChart'
import type { LabWindowDetail } from '../../api/types'

const DETAIL: LabWindowDetail = {
  series_id: 'm:a',
  window_index: 0,
  start: '2026-01-01T00:00:00+00:00',
  end: '2026-01-05T04:00:00+00:00',
  freq: '1h',
  n: 3,
  expected: 3,
  missing_ratio: 0,
  timestamps: [1767225600000, 1767229200000, 1767232800000],
  values: [1.0, 5.0, 2.0],
  detectors: [
    {
      detector: 'iqr',
      resolved: 'iqr',
      metric_class: 'periodic',
      fallback: false,
      rationale: '',
      scores: [0.1, 4.2, 0.3],
      severity: [0, 1, 0],
      baseline: [1.0, 1.0, 1.0],
      lower: [0.0, 0.0, 0.0],
      upper: [2.0, 2.0, 2.0],
      n_alerts: 1,
      multiplier: 2.5,
    },
  ],
  warnings: [],
}

describe('buildWindowOption', () => {
  it('画出实际值主线', () => {
    const option = buildWindowOption({ detail: DETAIL })

    const actual = option.series.find((s) => s.name === '实际值')
    expect(actual).toBeDefined()
    expect((actual as { data: unknown[] }).data).toEqual([1.0, 5.0, 2.0])
  })

  it('画出每个算法的基线', () => {
    const option = buildWindowOption({ detail: DETAIL })

    expect(option.series.find((s) => s.name === 'IQR 围栏 基线')).toBeDefined()
  })

  it('把告警点标在对应位置', () => {
    const option = buildWindowOption({ detail: DETAIL })

    const points = option.series.find((s) => s.name === 'IQR 围栏 告警')
    expect(points).toBeDefined()
    expect((points as { data: unknown[] }).data).toEqual([[1, 5.0]])
  })

  it('没有告警的算法不画散点', () => {
    const quiet = {
      ...DETAIL,
      detectors: [{ ...DETAIL.detectors[0], severity: [0, 0, 0], n_alerts: 0 }],
    }

    const option = buildWindowOption({ detail: quiet })

    expect(option.series.find((s) => s.name === 'IQR 围栏 告警')).toBeUndefined()
  })

  it('没有基线的算法不画基线', () => {
    const noBands = {
      ...DETAIL,
      detectors: [{ ...DETAIL.detectors[0], baseline: [null, null, null] }],
    }

    const option = buildWindowOption({ detail: noBands })

    expect(option.series.find((s) => s.name === 'IQR 围栏 基线')).toBeUndefined()
  })

  it('基线默认收起 —— 六条基线会把形态淹掉', () => {
    const option = buildWindowOption({ detail: DETAIL })

    // ⚠️ `legend.selected` 里 false = 未选中 = 不画
    expect(option.legend.selected['IQR 围栏 基线']).toBe(false)
    // 实际值与告警点必须默认可见
    expect(option.legend.selected['实际值']).toBeUndefined()
    expect(option.legend.selected['IQR 围栏 告警']).toBeUndefined()
  })

  it('同一实际算法只画一次 —— auto 常解析成某个固定算法', () => {
    const duplicated = {
      ...DETAIL,
      detectors: [
        { ...DETAIL.detectors[0], detector: 'auto', resolved: 'iqr' },
        { ...DETAIL.detectors[0], detector: 'iqr', resolved: 'iqr' },
      ],
    }

    const option = buildWindowOption({ detail: duplicated })

    const alerts = option.series.filter((s) => String(s.name).endsWith('告警'))
    expect(alerts).toHaveLength(1)
    expect(alerts[0].name).toBe('IQR 围栏（自动） 告警')
  })
})
