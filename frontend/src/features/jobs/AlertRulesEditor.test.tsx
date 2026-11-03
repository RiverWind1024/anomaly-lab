/**
 * 告警规则编辑器 —— 档位并排、阈值直接调。
 *
 * ⚠️ 重点守两件事：
 *    1. 阈值**真的能改**（这是本组件存在的理由）；
 *    2. 输出的规则表**倍数从小到大**（顺序即档位顺序，乱序会被后端拒）。
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AlertRulesEditor, rulesToTiers, tiersToRules } from './AlertRulesEditor'

describe('rulesToTiers', () => {
  it('没有规则 → 用默认的两档（P1 / P0）', () => {
    const { tiers } = rulesToTiers(null, 2.5, 3.75)
    expect(tiers.map((t) => [t.level, t.multiplier])).toEqual([
      ['P1', 2.5],
      ['P0', 3.75],
    ])
  })

  it('已有的规则 → 还原成档位', () => {
    const { tiers } = rulesToTiers(
      [
        { multiplier: 3, level: 'P1' },
        { multiplier: 5, level: 'P0' },
      ],
      2.5,
      3.75,
    )
    expect(tiers.map((t) => t.multiplier)).toEqual([3, 5])
    expect(tiers.map((t) => t.level)).toEqual(['P1', 'P0'])
  })

  it('⚠️ 绝对值条件不进档位表 —— 它是「附加」的', () => {
    const { tiers, extraText } = rulesToTiers(
      [
        { multiplier: 2.5, level: 'P1' },
        { op: '>', value: 50, level: 'P0' },
      ],
      2.5,
      3.75,
    )
    expect(tiers).toHaveLength(1)
    expect(extraText).toBe('> 50, P0')
  })
})

describe('tiersToRules', () => {
  it('倍数按从小到大输出 —— 规则表的顺序即档位顺序', () => {
    const { tiers } = rulesToTiers(null, 2.5, 3.75)
    const rules = tiersToRules(
      [
        { ...tiers[0], multiplier: 9 },
        { ...tiers[1], multiplier: 4 },
      ],
      '',
    )
    expect(rules?.map((r) => r.multiplier)).toEqual([4, 9])
  })

  it('附加的绝对值条件排在最后', () => {
    const { tiers } = rulesToTiers(null, 2.5, 3.75)
    const rules = tiersToRules(tiers, '>50, P0')
    expect(rules).toHaveLength(3)
    expect(rules?.[2]).toEqual({ op: '>', value: 50, level: 'P0' })
  })

  it('⚠️ 附加条件写错了 → 返回 null（不提交半对的规则）', () => {
    const { tiers } = rulesToTiers(null, 2.5, 3.75)
    expect(tiersToRules(tiers, '这不是条件')).toBeNull()
  })
})

describe('AlertRulesEditor', () => {
  it('显示默认的两档阈值', () => {
    render(<AlertRulesEditor value={null} onChange={vi.fn()} />)
    expect(screen.getByDisplayValue('2.5')).toBeTruthy()
    expect(screen.getByDisplayValue('3.75')).toBeTruthy()
  })

  it('⚠️ 改阈值 → 回调里带上新值（按倍数升序）', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<AlertRulesEditor value={null} onChange={onChange} />)

    const input = screen.getByDisplayValue('2.5')
    await user.clear(input)
    await user.type(input, '4')

    const last = onChange.mock.calls.at(-1)?.[0]
    // ⚠️ 输出**按倍数升序** —— P1 改成 4 后它比 P0 的 3.75 更大，跑到后面
    expect(last.map((r: { multiplier: number }) => r.multiplier)).toEqual([3.75, 4])
  })

  it('⚠️ 档位名与阈值顺序打架时给出提示', async () => {
    /* P1 的阈值调到比 P0 高 —— 排序后 P0 变成更容易触发的那一档，
       与「P0 最严重」正好相反。不提示的话用户会以为搞错了。 */
    const user = userEvent.setup()
    render(<AlertRulesEditor value={null} onChange={vi.fn()} />)

    const input = screen.getByDisplayValue('2.5')
    await user.clear(input)
    await user.type(input, '9')

    expect(screen.getByText(/档位顺序与阈值大小不一致/)).toBeTruthy()
  })

  it('添加一档 —— 新的档倍数更大', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<AlertRulesEditor value={null} onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: /添\s*加\s*一\s*档/ }))
    const last = onChange.mock.calls.at(-1)?.[0]
    expect(last).toHaveLength(3)
    expect(last[2].multiplier).toBeGreaterThan(last[1].multiplier)
  })

  it('⚠️ 只剩一档时不能删 —— 空规则表后端会拒', async () => {
    const user = userEvent.setup()
    render(<AlertRulesEditor value={null} onChange={vi.fn()} />)

    const buttons = screen.getAllByRole('button', { name: /删\s*掉\s*这\s*一\s*档/ })
    // ⚠️ 初始两档都能删
    expect(buttons.every((b) => !(b as HTMLButtonElement).disabled)).toBe(true)

    await user.click(buttons[0])
    const remaining = screen.getAllByRole('button', { name: /删\s*掉\s*这\s*一\s*档/ })
    expect(remaining.every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })

  it('已有的规则原样显示', () => {
    render(
      <AlertRulesEditor
        value={[
          { multiplier: 7, level: 'P1' },
          { multiplier: 9, level: 'P0' },
        ]}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByDisplayValue('7')).toBeTruthy()
    expect(screen.getByDisplayValue('9')).toBeTruthy()
  })
})
