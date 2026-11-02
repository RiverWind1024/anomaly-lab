import { List, Pagination, Tag } from 'antd'
import type { EvaluationRow } from '../../api/types'
import { isSelectedRow, paginate, recordKey, type RecordKey } from './records'

export interface DetectionsListProps {
  /** 已筛选的记录（分页在这里切）。 */
  rows: EvaluationRow[]
  /** 当前选中的记录。 */
  selected: RecordKey | undefined
  onSelect: (row: EvaluationRow) => void
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
}

/**
 * 左栏的记录索引：可点选的列表 + 分页。
 *
 * ⚠️ **分页器在滚动区之外** —— 侧栏是 `overflow: auto` 的，
 *    分页器放进去就得滚到底才看得见，那等于没有分页。
 */
export function DetectionsList({
  rows,
  selected,
  onSelect,
  page,
  pageSize,
  onPageChange,
}: DetectionsListProps) {
  const items = paginate(rows, page, pageSize)

  return (
    <div className="detections-list">
      <List
        size="small"
        className="detections-list__items"
        pagination={false}
        rowKey={(row: EvaluationRow) => recordKey(row)}
        dataSource={items}
        renderItem={(row) => (
          <List.Item
            className={`detections-list__item${isSelectedRow(row, selected) ? ' is-active' : ''}`}
            onClick={() => onSelect(row)}
          >
            <span className="mono detections-list__id">{row.series_id}</span>
            {/* ⚠️ 算法标签不是装饰 —— 记录是「序列 × 算法」， taste-skill-ignore
                只看序列分不清同序列的不同算法。 */}
            <Tag className="detections-list__detector">{row.detector}</Tag>
          </List.Item>
        )}
      />
      <Pagination
        size="small"
        current={page}
        pageSize={pageSize}
        total={rows.length}
        showSizeChanger
        pageSizeOptions={[20, 50, 100]}
        onChange={(nextPage, nextSize) => onPageChange(nextPage, nextSize)}
      />
    </div>
  )
}
