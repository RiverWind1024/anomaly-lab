/**
 * 表单里的数值下限/上限。
 *
 * ⚠️ 这三个数字**来自后端**，前端只是提前提示：
 *   - `WINDOW_POINTS_MIN` / `WINDOW_POINTS_MAX` ← `platform/validation.py::validate_window_points`
 *   - `INTERVAL_SECONDS_MIN`                  ← `platform/validation.py::validate_interval_seconds`
 * 后端没有把限制暴露到 API，改那边时这里必须同步；
 * `tests/web/test_api_contract.py` 会读这个文件做交叉校验，漂移会红。
 */

export const WINDOW_POINTS_MIN = 10
export const WINDOW_POINTS_MAX = 100_000
export const INTERVAL_SECONDS_MIN = 10
