/**
 * 告警规则**编辑器** —— 档位并排，阈值直接调。
 *
 * ⚠️ 为什么要这个而不是一个纯文本框：
 *    原来的输入框要用户手写「2.5, P1 / 3.75, P0」——
 *    而 2.5 / 3.75 这两个值**恰恰是最该被调的东西**（算法的默认阈值）。
 *    让它们躲在一个文本框里，等于把最常改的配置藏起来。
 *
 * ⚠️ 两类条件分工不变（见 `rules.ts`）：
 *    - **倍数条件**（主判定）：下面的档位表，一档一个倍数 + 一个等级；
 *    - **绝对值条件**（并行补充）：折叠区里的文本框，保留原有写法。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { AutoComplete, Button, Input, InputNumber, Tooltip } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { AlertRule } from '../../api/types'
import { parseRules } from './rules'

/** 档位等级的可选值（也能自己输入别的名字）。 */
const LEVEL_OPTIONS = [
  { value: 'P0' },
  { value: 'P1' },
  { value: 'P2' },
  { value: 'P3' },
]

/**
 * 档位的**严重程度** —— 数字越小越严重（P0 最严重）。
 *
 * ⚠️ 规则表的**位置**决定等级（越靠后等级越高），
 *    而位置又要按倍数从小到大排 ——
 *    所以「档位名的严重顺序」必须与「倍数的顺序」一致，
 *    否则 P0（最严重）会比 P1 更容易触发。
 *
 * ⚠️ 自定义的档位名（不在 P 序列里）不参与判断 ——
 *    我们猜不出它的严重程度，只能交给用户自己保证。
 */
function severityOf(level: string): number | null {
  const match = /^P(\d+)$/.exec(level.trim().toUpperCase())
  if (!match) return null
  return Number(match[1])
}

/**
 * 档位顺序与倍数顺序**是否打架**。
 *
 * ⚠️ 例：P1 的阈值被调到 4，P0 还是 3.75 ——
 *    按倍数排序后 P0 排到了前面，于是「P0 更容易触发」——
 *    与 P0 = 最严重的含义**正好相反**。
 */
export function tierOrderConflict(tiers: Tier[]): boolean {
  const sorted = [...tiers].sort((a, b) => (a.multiplier ?? 0) - (b.multiplier ?? 0))
  const known = sorted
    .map((tier) => severityOf(tier.level))
    .filter((value): value is number => value !== null)
  // ⚠️ 严重程度必须**跟着倍数一起递减**（P1 → P0 才是从低到高严重）
  for (let i = 1; i < known.length; i += 1) {
    if (known[i] >= known[i - 1]) return true
  }
  return false
}

export interface AlertRulesEditorProps {
  value: AlertRule[] | null | undefined
  onChange: (rules: AlertRule[] | null) => void
  /** 没有规则时显示的默认档位（P1 档的倍数）。 */
  defaultThreshold?: number
  /** 没有规则时显示的默认档位（P0 档的倍数）。 */
  defaultCriticalThreshold?: number
  /** 禁用（只读场景）。 */
  disabled?: boolean
}

/** 一行档位。 */
interface Tier {
  id: string
  level: string
  multiplier: number | null
}

let seq = 0
function nextId(): string {
  seq += 1
  return `tier-${seq}`
}

/**
 * 规则表 → 档位行 + 附加条件文本。
 *
 * ⚠️ 倍数条件进档位表，**绝对值条件**进附加文本 ——
 *    绝对值条件在界面上是「补充」，不该和主判定混在一张表里。
 */
export function rulesToTiers(
  rules: AlertRule[] | null | undefined,
  defaultThreshold: number,
  defaultCritical: number,
): { tiers: Tier[]; extraText: string } {
  const list = rules ?? []
  const multipliers = list.filter((rule) => rule.multiplier != null)
  const absolutes = list.filter((rule) => rule.multiplier == null)

  const tiers: Tier[] =
    multipliers.length > 0
      ? multipliers.map((rule) => ({
          id: nextId(),
          level: rule.level,
          multiplier: rule.multiplier ?? null,
        }))
      : [
          { id: nextId(), level: 'P1', multiplier: defaultThreshold },
          { id: nextId(), level: 'P0', multiplier: defaultCritical },
        ]

  const extraText = absolutes
    .map((rule) => `${rule.op} ${rule.value}, ${rule.level}`)
    .join('\n')

  return { tiers, extraText }
}

/** 档位行 + 附加条件文本 → 规则表。 */
export function tiersToRules(tiers: Tier[], extraText: string): AlertRule[] | null {
  const parsed = parseRules(extraText)
  if (parsed.errors && Object.keys(parsed.errors).length > 0) return null

  const multiplierRules: AlertRule[] = tiers
    .filter((tier) => tier.multiplier != null && tier.multiplier > 0)
    .map((tier) => ({ multiplier: tier.multiplier as number, level: tier.level }))
    // ⚠️ **倍数从小到大** —— 规则表的顺序即档位顺序（从低到高严重），
    //    顺序错了等级就乱了（后端也会拒）。
    .sort((a, b) => (a.multiplier as number) - (b.multiplier as number))

  const absoluteRules = parsed.rules ?? []
  return [...multiplierRules, ...absoluteRules]
}

export function AlertRulesEditor({
  value,
  onChange,
  defaultThreshold = 2.5,
  defaultCriticalThreshold = 3.75,
  disabled = false,
}: AlertRulesEditorProps) {
  const initial = useMemo(
    () => rulesToTiers(value, defaultThreshold, defaultCriticalThreshold),
    // ⚠️ 只在**首次**算 —— 之后由下面的 effect 同步
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const [tiers, setTiers] = useState<Tier[]>(initial.tiers)
  const [extraText, setExtraText] = useState(initial.extraText)

  /**
   * 外部值变化时重建。
   *
   * ⚠️ **只认「不是我们自己发出去的」变化** ——
   *    否则用户输入到一半（"2."）就会被重建冲掉，光标跳回开头。
   */
  const lastEmitted = useRef<string>('')
  useEffect(() => {
    const key = JSON.stringify(value ?? null)
    if (key === lastEmitted.current) return
    const next = rulesToTiers(value, defaultThreshold, defaultCriticalThreshold)
    setTiers(next.tiers)
    setExtraText(next.extraText)
    lastEmitted.current = key
  }, [value, defaultThreshold, defaultCriticalThreshold])

  /** 改动 → 通知外部。 */
  const emit = (nextTiers: Tier[], nextExtra: string) => {
    const rules = tiersToRules(nextTiers, nextExtra)
    lastEmitted.current = JSON.stringify(rules ?? null)
    onChange(rules)
  }

  const updateTier = (id: string, patch: Partial<Tier>) => {
    const next = tiers.map((tier) => (tier.id === id ? { ...tier, ...patch } : tier))
    setTiers(next)
    emit(next, extraText)
  }

  const removeTier = (id: string) => {
    // ⚠️ 至少留一档 —— 空规则表后端会拒（400），不如不让删
    if (tiers.length <= 1) return
    const next = tiers.filter((tier) => tier.id !== id)
    setTiers(next)
    emit(next, extraText)
  }

  const addTier = () => {
    // ⚠️ 新档排在最后 —— 倍数最大的那一档
    const last = tiers[tiers.length - 1]
    const multiplier = last?.multiplier ? last.multiplier * 1.5 : 2.5
    const next = [...tiers, { id: nextId(), level: 'P0', multiplier }]
    setTiers(next)
    emit(next, extraText)
  }

  const extraErrors = useMemo(() => {
    const parsed = parseRules(extraText)
    return Object.values(parsed.errors)
  }, [extraText])

  const conflict = useMemo(() => tierOrderConflict(tiers), [tiers])

  return (
    <div className="rules-editor">
      <div className="rules-editor__tiers">
        {tiers.map((tier) => (
          <div className="rules-editor__tier" key={tier.id}>
            <AutoComplete
              value={tier.level}
              options={LEVEL_OPTIONS}
              size="small"
              disabled={disabled}
              style={{ width: 76 }}
              onChange={(next) => updateTier(tier.id, { level: next })}
            />
            <span className="rules-editor__times">×</span>
            <InputNumber
              value={tier.multiplier}
              size="small"
              min={0.01}
              step={0.25}
              disabled={disabled}
              style={{ width: 110 }}
              // ⚠️ **formatter 去掉多余的尾零** ——
              //    antd 会按 `step` 的小数位推断精度（step=0.25 → 2 位），
              //    于是 2.5 显示成「2.50」。用户配的明明是 2.5。
              formatter={(value) =>
                value === undefined || value === null ? '' : String(value)
              }
              parser={(value) => (value === '' ? NaN : Number(value))}
              onChange={(next) => updateTier(tier.id, { multiplier: next })}
            />
            <Tooltip title="删掉这一档">
              <Button
                size="small"
                type="text"
                aria-label="删掉这一档"
                icon={<DeleteOutlined />}
                disabled={disabled || tiers.length <= 1}
                onClick={() => removeTier(tier.id)}
              />
            </Tooltip>
          </div>
        ))}
        <Button size="small" icon={<PlusOutlined />} disabled={disabled} onClick={addTier}>
          添加一档
        </Button>
      </div>

      {/* ⚠️ 概念解释**折起来** —— 它解释的是规则语义，不是当前要填的东西，
          常驻只会把本来就复杂的这块撑得更满。 */}
      <details className="rules-editor__extra">
        <summary>倍数怎么算？</summary>
        <p className="muted rules-editor__hint">
          倍数是「偏离基线多少倍算异常」。档位按倍数从小到大排，命中多条时取最高档。
        </p>
      </details>

      {/* ⚠️ 档位名与倍数顺序打架 —— 不说清楚，用户会以为 P0 比 P1 更容易触发。 */}
      {conflict && (
        <p className="form-hint">
          档位顺序与阈值大小不一致 —— 实际生效时按<strong>阈值从小到大</strong>排列。
          P0 是更严重的档位，它的阈值应该比 P1 更高。
        </p>
      )}

      {/* ⚠️ 绝对值条件罕用 —— 折起来，别喧宾夺主 */}
      <details className="rules-editor__extra">
        <summary>附加条件（绝对值）</summary>
        <Input.TextArea
          value={extraText}
          rows={3}
          disabled={disabled}
          spellCheck={false}
          placeholder={'每行一条「条件, 等级」\n例：\n>50, P0'}
          onChange={(event) => {
            const next = event.target.value
            setExtraText(next)
            emit(tiers, next)
          }}
        />
        {extraErrors.length > 0 && (
          <p className="form-error">附加条件有误：{extraErrors.join('；')}</p>
        )}
        <p className="muted">
          绝对值条件与倍数条件<strong>并行生效</strong> ——
          只能抬高等级，不会压低分数判定。
        </p>
      </details>
    </div>
  )
}
