import { Tag, Tooltip } from 'antd'

export interface ScaleStatusTagsProps {
  status?: 'ok' | 'undetermined'
  scaleSource?: string
  scaleFallback?: boolean
}

/** 「这次检测的尺度可信吗」的两个标签 —— 预览与试跑共用一个实现。 */
export function ScaleStatusTags({
  status,
  scaleSource,
  scaleFallback,
}: ScaleStatusTagsProps) {
  return (
    <>
      {status === 'undetermined' && (
        <Tooltip title="数据里没有可用的尺度（例如整段完全不变），无法判断异常">
          <Tag color="warning">无法判定</Tag>
        </Tooltip>
      )}
      {scaleFallback && (
        <Tooltip title={`首选尺度被本窗的数据退化掉了，已退回 ${scaleSource ?? '备用尺度'}`}>
          <Tag color="warning">尺度降级 · {scaleSource}</Tag>
        </Tooltip>
      )}
    </>
  )
}
