import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export interface AlgorithmGuideProps {
  guide?: {
    good_for?: string
    bad_for?: string
    score?: string
    needs?: string
  }
}

/** 算法的适用性说明 —— 悬停才看得到，不占版面。 */
export function AlgorithmGuide({ guide }: AlgorithmGuideProps) {
  if (!guide?.good_for && !guide?.bad_for) return null
  return (
    <Tooltip
      title={
        <div className="algorithm-guide">
          <div><b>适合</b>　{guide.good_for}</div>
          <div><b>失效</b>　{guide.bad_for}</div>
          {guide.score ? <div><b>分数</b>　{guide.score}</div> : null}
          {guide.needs ? <div><b>要求</b>　{guide.needs}</div> : null}
        </div>
      }
    >
      <QuestionCircleOutlined aria-label="算法适用性" className="field-hint__icon" />
    </Tooltip>
  )
}
