import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { StateBoundary } from './StateBoundary'

const data = { ok: true }

describe('StateBoundary', () => {
  it('加载中显示骨架屏', () => {
    const { container } = render(
      <StateBoundary isLoading error={undefined} data={undefined}>{() => <div>内容</div>}</StateBoundary>,
    )
    expect(container.querySelector('.ant-skeleton')).toBeTruthy()
  })

  it('真错误显示 detail 原文（红色）', () => {
    render(
      <StateBoundary isLoading={false} error={new ApiError(500, '数据库锁住了')} data={undefined}>
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据库锁住了')).toBeTruthy()
    expect(screen.queryByText('数据不足')).toBeNull()
  })

  it('bizState=insufficient_data 显示警告而不是错误', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '序列 x 有效点仅 12 个，不足以做检测', 'insufficient_data')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据不足')).toBeTruthy()
    expect(screen.getByText('序列 x 有效点仅 12 个，不足以做检测')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('bizState=no_run 显示空态而不是红色错误框', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '该任务还没有运行记录', 'no_run')}
        data={undefined}
        emptyAction={<button>立即运行</button>}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('该任务还没有运行记录')).toBeTruthy()
    expect(screen.getByText('立即运行')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('bizState 文案与标题相同时不重复渲染', () => {
    // 后端 no_run 的 detail 就是「该任务还没有运行记录」，
    // 与默认标题一字不差 —— 渲染两遍会出现「Found multiple elements」
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '该任务还没有运行记录', 'no_run')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getAllByText('该任务还没有运行记录')).toHaveLength(1)
  })

  it('bizState=no_algorithms 显示对应空态标题', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(400, '没有可对比的算法', 'no_algorithms')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('没有可对比的算法')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('响应体里的 sufficient=false 也进数据不足态', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={undefined}
        data={data}
        insufficient={() => '有效点仅 12 个，不足以做检测'}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据不足')).toBeTruthy()
    expect(screen.getByText('有效点仅 12 个，不足以做检测')).toBeTruthy()
    expect(screen.queryByText('内容')).toBeNull()
  })

  it('空态显示标题与按钮', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={undefined}
        data={data}
        isEmpty={() => true}
        emptyTitle="还没有检测任务"
        emptyAction={<button>新建任务</button>}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('还没有检测任务')).toBeTruthy()
    expect(screen.getByText('新建任务')).toBeTruthy()
  })

  it('有数据时渲染 children', () => {
    render(
      <StateBoundary isLoading={false} error={undefined} data={data}>
        {(d) => <div>内容 {String(d.ok)}</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('内容 true')).toBeTruthy()
  })

  it('bizTitles 可以覆盖默认标题', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '后端原文', 'no_run')}
        data={undefined}
        bizTitles={{ no_run: '先跑一次看看' }}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('先跑一次看看')).toBeTruthy()
    expect(screen.getByText('后端原文')).toBeTruthy()
  })
})
