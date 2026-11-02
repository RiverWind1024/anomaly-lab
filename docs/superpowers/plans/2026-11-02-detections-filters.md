# spec 3 实现计划：检测记录页筛选与分页

> 对应 spec：`docs/superpowers/specs/2026-11-02-detections-filters-design.md`
> 分支：`feature/detections-filters`

## 任务分解

| # | 任务 | 文件 | 验证 |
|---|---|---|---|
| T1 | 后端：`/api/badcases` 加可选 `detector` + 校验 | `src/anomaly_lab/web/app.py` | 生效 / 默认兼容 / 路径穿越 400 |
| T2 | 前端 API：`getBadcases` 带 detector | `frontend/src/api/series.ts` | 类型检查 |
| T3 | 前端 query：`useDetectionDetail` 带 detector | `frontend/src/features/detections/queries.ts` | — |
| T4 | 纯函数：`resolveSelected` / 分页切片 | `frontend/src/features/detections/records.ts` | 单测 |
| T5 | 筛选栏组件 | `frontend/src/features/detections/DetectionFilters.tsx` | — |
| T6 | 左栏列表组件（列表 + 分页） | `frontend/src/features/detections/DetectionsList.tsx` | — |
| T7 | 页面组装 + 详情头 | `frontend/src/features/detections/DetectionsPage.tsx` | 页面测试 |
| T8 | 评估页链接带 detector | `frontend/src/features/evaluation/EvaluationPage.tsx` | 改既有断言 |
| T9 | 后端测试 | `tests/web/test_badcases.py` | pytest |
| T10 | 前端测试 | `frontend/src/features/detections/*.test.tsx` | vitest |
| T11 | 样式 | `frontend/src/styles/global.css` | — |
| T12 | 文档 | `docs/PLATFORM.md` `docs/ROADMAP.md` | 自检 |

## 实施顺序

```
T1 → T2 → T3 → T4          # 通路与纯函数先到位
        ↓
     T5 → T6 → T7 → T8      # 前端组装
        ↓
     T9 → T10 → T11 → T12   # 测试与收尾
```

## 关键约束（实现时不能忘）

1. **算法名必须校验**（`validate_identifier`）—— 它要拼进文件路径。
   非法 → **400**（不是 404，不是 500）。
2. **`detector` 默认 `iqr`** —— 老行为不变，向后兼容。
3. **端点路径不变** → `EXPECTED_PATHS` 与 `test_api_contract.py` 都不用改。
4. **筛选维度就是 `EvaluationFilters` 的五个** —— `filters.ts` **一个字都不改**。
5. **分页器在滚动区之外** —— 否则要滚到底才看得见。
6. **高亮按 (序列, 算法)** —— 只按序列会把同序列的所有行点亮（那是 bug）。
7. **筛选不改变选中项**，但详情头要提示「不在当前筛选结果内」。
8. **深链接要拨页** —— URL 里的记录可能在第 3 页。
9. 中文两字按钮在 antd 里会自动插空格 —— 断言用 `/执\s*行/` 这种正则。

## 验收

```bash
.venv/bin/python -m pytest -q          # 全绿
make lint                               # ruff 全绿
cd frontend && npx tsc --noEmit && npm test && npm run build
```
