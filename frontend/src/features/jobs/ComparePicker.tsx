import { Checkbox } from 'antd'
import { useMemo } from 'react'

export interface ComparePickerProps {
  /** 后端给的候选算法；为空时要回退到 detectors 的名字列表 */
  available: string[]
  fallbackNames: string[]
  autoDetector: string
  selected: string[]
  onChange: (selected: string[]) => void
}

/**
 * 候选算法列表。
 *
 * ⚠️ **必须有回退**（照搬旧 `platform.js:312-314`）：
 *    `const names = available.length ? available : fallbackNames`
 *    否则 `available` 为空时勾选组会渲染成空的。
 */
export function candidateNames(available: string[], fallbackNames: string[]): string[] {
  return available.length ? available : fallbackNames
}

/**
 * 默认勾选规则（照搬旧 `platform.js`）：
 *
 * ```ts
 * input.checked = previous.length
 *   ? previous.includes(name)
 *   : names.length <= 4 || name === autoDetector
 * ```
 *
 * 即：**候选 ≤4 个时全勾，否则只勾 auto**。
 */
export function defaultSelection(names: string[], autoDetector: string): string[] {
  return names.length <= 4 ? [...names] : names.filter((name) => name === autoDetector)
}

/**
 * 多算法勾选组。
 *
 * 候选列表来自后端的 `available` —— 它**不随** `detectors` 查询参数变化，
 * 所以取消勾选后算法仍然留在列表里，可以再勾回来。
 */
export function ComparePicker({
  available,
  fallbackNames,
  autoDetector,
  selected,
  onChange,
}: ComparePickerProps) {
  const names = useMemo(
    () => candidateNames(available, fallbackNames),
    [available, fallbackNames],
  )

  // 没手动选过 → 用默认勾选；有 → 用用户的（沿用旧版的 previous 逻辑）
  const effective = selected.length ? selected : defaultSelection(names, autoDetector)

  const handleChange = (values: unknown[]) => {
    const next = values as string[]
    // ⚠️ 后端没有「一个都不比」的表达（detectors 为空 = 比全部），
    //    全部取消时回到默认勾选 —— 否则会出现「勾选框全空但表格里有数据」的矛盾。
    onChange(next.length ? next : defaultSelection(names, autoDetector))
  }

  if (names.length === 0) {
    return <p className="muted">没有可对比的算法。</p>
  }

  return (
    <div className="compare-picker">
      <Checkbox.Group
        value={effective}
        onChange={handleChange}
        options={names.map((name) => ({ label: name, value: name }))}
      />
      <p className="muted compare-picker__hint">
        默认展示 {names.length <= 4 ? '全部候选' : `auto（${autoDetector}）`}；
        勾选后只对比勾中的算法。
      </p>
    </div>
  )
}
