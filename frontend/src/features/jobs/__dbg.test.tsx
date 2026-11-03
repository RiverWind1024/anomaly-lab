import { InputNumber } from 'antd'
import { render } from '@testing-library/react'
import { describe, it } from 'vitest'

function show(label: string, el: React.ReactElement) {
  const { container } = render(el)
  const v = [...container.querySelectorAll('input')].map((i) => i.value)
  console.log(label, v)
}

describe('dbg', () => {
  it('combos', () => {
    show('step=0.25:', <InputNumber value={2.5} step={0.25} />)
    show('no step:   ', <InputNumber value={2.5} />)
    show('step=0.5:  ', <InputNumber value={2.5} step={0.5} />)
    show('formatter: ', <InputNumber value={2.5} step={0.25} formatter={(v) => String(v)} />)
    show('3.75 fmtr: ', <InputNumber value={3.75} step={0.25} formatter={(v) => String(v)} />)
  })
})
