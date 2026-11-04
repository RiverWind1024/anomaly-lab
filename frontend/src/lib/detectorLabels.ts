/**
 * 检测算法名 → 中文标签。
 *
 * ⚠️ **为什么要有这张表**：
 *    算法名是**内部标识**（`theil_sen`），直接显示给用户等于让人看代码。
 *    而中文标签又不能只写一份在后端 ——
 *    历史评测产物里存的是**改名前的旧名**，前端拿到的是裸名字，
 *    没有地方可以查。
 *
 * ⚠️ **旧名也在表里**：`deseasonalized_iqr`（旧名，说的是「去季节化」，
 *    做的却是「去趋势」）在历史评测产物里还有几百条记录。
 *    查不到标签就会原样显示 `deseasonalized_iqr` ——
 *    用户既不知道那是什么，也对不上新名。
 *
 * ⚠️ **表里没有的名字原样返回** —— 宁可显示原始名，
 *    也不要显示一个空标签或「未知算法」（那会让人以为是 bug）。
 */

/** 算法名 → 中文标签。 */
export const DETECTOR_LABELS: Record<string, string> = {
  // 统计族
  iqr: 'IQR 围栏',
  mad: 'MAD',
  zscore: 'Z 分数',
  // 季节族
  seasonal: '季节性分组',
  stl_residual: 'STL 残差',
  // 趋势族
  trend_residual_iqr: '去趋势残差 IQR',
  theil_sen: '稳健趋势线 Theil-Sen',
  // 其它
  changepoint: '变点检验',
  event_count: '事件计数',
  chronos: 'Chronos 预训练模型',
  auto: '自动推荐',
  // ⚠️ 旧名 —— 历史评测产物里还有。标签带「旧名」提示，
  //    让用户知道这是同一个算法的新旧两个名字。
  deseasonalized_iqr: '去趋势残差 IQR（旧名）',
}

/**
 * 取算法名的中文标签。
 *
 * @param name 算法名（可能是旧名，也可能是表里没有的名字）
 */
export function detectorLabel(name: string | null | undefined): string {
  if (!name) return '—'
  return DETECTOR_LABELS[name] ?? name
}
