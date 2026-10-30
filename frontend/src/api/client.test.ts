import { describe, expect, it } from 'vitest'
import { ApiError, request } from './client'

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** request() 的 T 推不出来，catch 回来的值是 unknown —— 用这个助手拿类型安全的 ApiError。 */
async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    return e as ApiError
  }
  throw new Error('期望抛 ApiError，但请求成功了')
}

describe('request', () => {
  it('把 422 的数组 detail 拼成可读文案', async () => {
    const resp = jsonResponse(422, {
      detail: [
        { loc: ['body', 'freq'], msg: 'value is not a valid frequency', type: 'value_error' },
        { loc: ['body', 'query'], msg: 'field required', type: 'missing' },
      ],
    })
    const err = await expectApiError(request('/api/platform/metrics', { method: 'POST' }, resp))
    expect(err.status).toBe(422)
    expect(err.message).toBe('value is not a valid frequency；field required')
  })

  it('字符串 detail 原样透出', async () => {
    const resp = jsonResponse(404, { detail: '序列不存在: abc' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.message).toBe('序列不存在: abc')
  })

  it('读取业务态响应头 X-Anomaly-Biz-State', async () => {
    const resp = jsonResponse(404, { detail: '该任务还没有运行记录' }, {
      'X-Anomaly-Biz-State': 'no_run',
    })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBe('no_run')
  })

  it('响应头缺失时按 detail 前缀兜底', async () => {
    const resp = jsonResponse(404, { detail: '该任务还没有运行记录' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBe('no_run')
  })

  it('既没有响应头也不是业务态文案时 bizState 为 undefined', async () => {
    const resp = jsonResponse(404, { detail: '序列不存在: abc' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBeUndefined()
  })

  it('2xx 直接返回 body', async () => {
    const resp = jsonResponse(200, { ok: true })
    await expect(request('/api/x', {}, resp)).resolves.toEqual({ ok: true })
  })
})
