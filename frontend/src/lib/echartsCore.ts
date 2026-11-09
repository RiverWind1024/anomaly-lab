/**
 * ECharts 按需引入的**唯一入口**。
 *
 * ⚠️ 不要在各图表文件里 `import from 'echarts-for-react'` 的默认入口 ——
 *    那会打进 `echarts` 全量包，构建出一个 1.1 MB 的共享 chunk
 *    （实测 gzip 385 KB），所有图表页都得拉。
 *
 * 这里只注册实际用到的图与组件。**新增图表类型/组件时必须在这里补**，
 * 否则运行时不会渲染（控制台报 `Series xxx is not exists`）。
 */
import * as echarts from 'echarts/core'
import { CustomChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  // 图：折线 / 散点 / custom（容忍带多边形，见 lib/bands.ts）
  LineChart,
  ScatterChart,
  CustomChart,
  // 组件
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent, // 含 inside + slider
  MarkAreaComponent,
  MarkLineComponent,
  ToolboxComponent, // 标注页的「还原」按钮
  CanvasRenderer,
])

export default echarts
