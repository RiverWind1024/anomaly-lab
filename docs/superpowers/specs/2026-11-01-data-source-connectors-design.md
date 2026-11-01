# 数据源连接器与数据浏览器（设计）

> 日期：2026-11-01　状态：待实施
> 定位：作品集（portfolio）方向的生产化改造 —— 第一个 spec。

## 背景

平台目前只有一种数据源（本地 SQLite 文件），指标定义里手写 SQL 后**看不到查出来什么、
结构长什么样** —— 只能靠猜，错了要等检测任务跑完才知道。这让「数据源 → 指标 → 序列」
这条链在演示和真实使用中都很难用。

同时，时序库（InfluxDB 3、ClickHouse、TDengine…）大多提供 **SQL over HTTP**，
平台应该能直接接上，而不是为每家写一套专用查询。

## 目标

1. 新增 **HTTP 透传数据源**：把指标 SQL 原样发给远端 SQL 网关，取回表格。
2. 新增 **数据浏览器**：在数据源上写 SQL → 看到列结构与前 N 行 → 一键生成指标。
3. 抽出 **连接器抽象**，让后续接入 InfluxDB 3 / ClickHouse / Prometheus 只需新增一个类。

## 非目标

- 告警外发（webhook / 邮件 / IM）—— 独立 spec。
- 认证与多租户 —— 作品集定位下暂不做。
- 「假远端时序数据库」（持续产数 + InfluxDB 形状的 SQL 端点）—— **spec 2**。
  本轮用**测试夹具**（pytest 里起一个假 HTTP 端点）验证透传路径。
- 第二层（专有查询语言）连接器：InfluxDB 2.x 的 InfluxQL、Prometheus 的 PromQL。
  **只预留设计位置，本轮不实现**（见 §12）。
- Postgres / MySQL 等需要驱动的数据库 —— 等有实际需求再说。

---

## 1. 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | **接口型数据源走「SQL 透传」**，而非「拉回本地执行」 | 远端算完再回来，数据量再大也不占本地内存；能直接接 ClickHouse/InfluxDB 3/Doris 等一大批系统 |
| D2 | **不引入新依赖** | HTTP 客户端用标准库 `urllib.request`（项目 `data/public.py` 已有先例）；mock 服务用已有的 FastAPI/uvicorn。实测 DuckDB（23MB wheel）在本环境下载超时 |
| D3 | **连接器只负责「SQL → DataFrame」，后处理全部共用** | 时间解析 / 排序 / group by 拆分 / 缺失策略本就方言无关，抽出来后每个连接器只有 60~90 行 |
| D4 | `Source` 新增 `config` JSON 列，**`path` 列保留** | SQLite 路径与既有测试零破坏；HTTP 源参数放 JSON，后续加 kind 不用改表结构 |
| D5 | **`$timefilter` 由连接器各自替换** | 现有替换是 SQLite 专有的 `julianday()`，在 ClickHouse/Postgres 上是错的。但用户在指标里的写法不变 |
| D6 | **`{sql}` 占位符同时支持 URL 与 body** | InfluxDB 3 的端点是 `POST /api/v3/query_sql`，SQL 在 body 的 `q` 字段里 |
| D7 | **`format` 同时决定请求参数与响应解析** | InfluxDB 3 的 `format` 取值是 `pretty\|json\|csv\|parquet\|jsonl`，**默认 `json`**；用 `csv` 可完全避开 `parquet` 所需的 pyarrow 重依赖 |
| D8 | **`validate_query` 拆成两档** | 浏览用的 SQL 不该强制包含 `$timefilter`（那是指标的要求） |
| D9 | 透传源**不做「安全」的伪装** | SQL 原样发到远端执行，关键字黑名单可绕过。真正的安全边界是远端账号权限 —— UI 与文档必须讲明 |
| D10 | HTTP 侧时间字面量**跟随 `time_format`**，不统一用 `Z` | 平台的 `to_iso()` 输出是 `...+00:00`；用 `Z` 会让字符串比较在边界差一小时（`'+'`(0x2B) < `'Z'`(0x5A)） |
| D11 | **浏览与指标共用同一套时间条件替换** | 用户粘贴指标 SQL 预览时，替换逻辑必须与运行时完全一致，否则「预览看到的」≠「跑出来的」 |
| D12 | **响应解析用 pandas**（`read_csv` / `DataFrame`），不用标准库 csv/json | 标准库产出的全是字符串 → dtype 恒为 object → 类型推断成为死代码 |
| D13 | 脱敏在 **store 层**，不在前端 | 前端拿不到原值，「保留原值」这类合并规则只能后端做 |

## 2. 连接器抽象

```
src/anomaly_lab/platform/sources/
  __init__.py     # 注册表：get_connector(source, data_root) / SUPPORTED_KINDS
  base.py         # Connector 协议 + 共用后处理 + 时间字面量生成
  sqlite.py       # 现有逻辑搬过来，实现协议
  http_sql.py     # 新写：填 {sql} → 发出去 → 解析成表
```

`sqlite_source.py` **保留为薄壳**（`load_series` 从 `sources/sqlite.py` 再导出），
让 `tests/platform/test_sqlite_source.py`、`test_data_quality.py`、`test_robustness.py`
（后者还 monkeypatch `runner.load_series`）**零改动**。

### 2.1 协议

```python
class SourceConnector(Protocol):
    kind: str

    def execute_sql(
        self, sql: str, *, limit: int | None = None
    ) -> pd.DataFrame:
        """执行只读 SQL，返回表格（列名 + pandas 推断的 dtype）。"""

    def fetch(
        self, metric: Metric, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """取 [start, end) 的数据（内部做 $timefilter 替换）。"""

    def test_connection(self) -> tuple[bool, str]:
        """「测试连接」按钮：返回 (是否成功, 说明)。"""
```

- **不设 `describe()`** —— 脱敏在 store 层做（D13），连接器不需要知道展示格式。
- **构造**：`get_connector(source: Source, data_root: Path) -> SourceConnector`。
  连接器从 `source.config` 拿自己的参数；`data_root` 用于解析 SQLite 源的相对路径
  （沿用 `runner.resolve_source_path` 的语义：`Path(source.path)` 绝对路径直接用，
  相对路径拼 `data_root`）。

### 2.2 共用后处理（`base.py`）

从 `sqlite_source.py` 搬过来，**逻辑一字不改**：

```python
def series_from_frame(frame: pd.DataFrame, metric: Metric) -> list[SeriesBundle]:
    """解析时间列 → 排序 → group by 拆序列 → 缺失策略"""
```

**契约（验收依据）**：

| 情形 | 行为 |
|---|---|
| `frame` 为空 | 返回 `[]` |
| 缺 `value_column` 列 | `ValueError("查询结果缺少 value_column: {name}")` |
| 缺 `group_column` 列 | `ValueError("查询结果缺少 group_column: {name}")` |
| `group_column` 为空 | 不分组，整表当一条序列，`group=None` |
| 每条序列的 `meta` | `metric_id` / `metric_name` / `group` / `source_id` / `n_missing` / `n_valid` / `sufficient` |
| `sufficient` 判定 | 有效点数 ≥ `MIN_VALID_POINTS`（=10，常量归 `base.py`） |

沿用的既有函数：`_parse_time_column` / `_apply_missing_policy` / `_group_label` /
`validate_identifier`。

### 2.3 调用链

```
runner.execute_job
  └─ connector.fetch(metric, start, end) -> DataFrame        ← 连接器负责
       └─ series_from_frame(frame, metric) -> [SeriesBundle]  ← 共用
            └─ 检测器 / 告警分级（完全不变）

POST /api/platform/sources/{id}/query
  └─ connector.execute_sql(sql, limit=...) -> DataFrame      ← 连接器负责
```

**检测、告警、浏览三条路径共用同一套后处理与时间替换** —— 这是「连接器抽象成立」的判据。

## 3. 数据源配置模型

### 3.1 表与模型

```sql
ALTER TABLE sources ADD COLUMN config TEXT NOT NULL DEFAULT '{}';
```

`Source` dataclass **末尾**新增带默认值的字段（现有字段全是必填，加默认字段必须放最后）：

```python
@dataclass(frozen=True)
class Source:
    id: int
    name: str
    kind: str
    path: str
    created_at: str
    config: dict = field(default_factory=dict)
```

**store 层解码**：现有三处 `Source(**dict(row))`（`store.py` 的 `list_sources` /
`get_source` / 内部查找）改为统一的 `_to_source(row)`：

```python
def _to_source(row) -> Source:
    data = dict(row)
    raw = data.pop("config") or "{}"
    data["config"] = json.loads(raw) if raw else {}
    return Source(**data)
```

`asdict(source)` 会把 `config` 原样带给前端 —— 脱敏见 §3.4。

### 3.2 kind = "sqlite"（现状不变）

- `path` 列存相对 `data_root` 的路径（如 `platform/source.db`）
- `config` = `{}`

### 3.3 kind = "http"（新增）

```jsonc
{
  "url": "https://ch.internal:8123/?query={sql}",        // URL 模板
  "method": "POST",                                       // GET | POST
  "body": { "db": "demo", "q": "{sql}", "format": "csv" },// 可选，body 模板
  "headers": { "Authorization": "Bearer xxx" },           // 可选
  "format": "csv",                                       // json | csv | jsonl
  "rows_path": "data",                                   // 可选，见下
  "timeout_seconds": 30
}
```

| 字段 | 语义 |
|---|---|
| `url` | 必填。`{sql}` 占位符在此生效，替换时做 **URL 编码** |
| `method` | `GET`（默认）或 `POST` |
| `body` | 可选。`{sql}` 占位符在此生效，替换时**原样替换**（不 URL 编码 —— 百分号编码会污染 SQL）。dict → 以 `application/json` 序列化 |
| `headers` | 可选，原样发送 |
| `format` | 请求时写进 `body["format"]`（若 body 存在）；响应时决定解析方式 |
| `rows_path` | 可选，点号路径（如 `"data"` / `"results.items"`），用于「顶层是对象、里面有个数组」 |
| `timeout_seconds` | 默认 30 |

**`rows_path` 的明确限制**：只支持**单层点号路径**指向一个对象数组。
**不支持** InfluxDB 3 的两段式响应（`results[].series[].columns` + `values`）——
文档注明「接 InfluxDB 3 请用 `format=csv`」。

**CSV 响应必须带表头行**（InfluxDB 3 的 csv format 带头；ClickHouse 的 `FORMAT CSVWithNames` 带头）。

**`kind` 收敛为枚举**：`SUPPORTED_KINDS = ("sqlite", "http")`，
store 在 `add_source` / `update_source` 校验；前端把 kind 从自由文本 Input 改成 Select。

### 3.4 密钥脱敏与「保留原值」

脱敏在 **store 层**（D13），规则：

- `headers` 的每个值 → `Bearer ••••` / `Basic ••••` / 其它 → `••••`
- `url` 的 query 里若出现 `token` / `key` / `password` / `secret` 参数 → 值替换为 `••••`
- `body` 里同样处理上述键名

**返回 source 的接口全部走脱敏**（逐个点名，避免遗漏）：
`POST /api/platform/sources`（创建响应）、`PATCH /api/platform/sources/{id}`、
`GET /api/platform/catalog`。

**「保留原值」规则**（前端提交的是脱敏值时不能覆盖真值）：
`update_source` 里，若新值 == 旧值的脱敏形式，则**沿用旧值**。

## 4. 时间边界（`$timefilter` 与 `{start}`/`{end}`）

### 4.1 两套占位符，职责清晰

| 占位符 | 用于 | 语义 |
|---|---|---|
| `$timefilter` | **指标 SQL** | 平台知道时间列（`metric.time_column`）与格式，替换成完整的时间条件 |
| `{start}` / `{end}` | **浏览 SQL** | 用户自己在 SQL 里写列名，平台只替换成时间字面量 |

**浏览时若 SQL 含 `$timefilter`**：允许，但需要调用方额外提供
`time_column` / `time_format` / `source_timezone`；缺 `time_column` → 400
（提示「使用 $timefilter 需要指定时间列」）。提供后**走与指标完全相同的替换逻辑**
（D11）→ 预览结果 == 运行时取数结果。

### 4.2 字面量生成（按 `time_format`）

```python
def time_literal(value: datetime, fmt: str, tz: str) -> str:
    if fmt == "iso_utc":    return value.astimezone(UTC).isoformat(timespec="seconds")   # "2026-10-30T09:38:00+00:00"
    if fmt == "iso_naive":  return 源时区墙钟字符串                              # "2026-10-30T09:38:00"
    if fmt == "epoch_s":    return str(int(value.timestamp()))
    if fmt == "epoch_ms":   return str(int(value.timestamp() * 1000))
```

⚠️ **必须与平台的 `to_iso()` 完全一致（T 分隔 + `+00:00`）** ——
`to_iso()` 就是 `value.astimezone(UTC).isoformat(timespec="seconds")`；
用空格分隔会与平台自己的时间表示对不上。

⚠️ `iso_utc` 用 **T 分隔 + `+00:00` 偏移**而非 `Z`（D10）：
同一偏移、同一 ISO 格式下**字符串字典序 == 时间序**，
边界比较才正确。用 `Z` 会让 `+`(0x2B) < `Z`(0x5A) → 边界行被误判。

### 4.3 两套方言

| 连接器 | `$timefilter` 替换成 | 方式 |
|---|---|---|
| sqlite | `julianday("col") >= julianday(?) AND julianday("col") < julianday(?)` | **参数绑定**（现状不变） |
| http | `"col" >= '{literal}' AND "col" < '{literal}'` | 字面量（列名过 `validate_identifier`，字面量由平台生成，无注入面） |

HTTP 侧的列名加双引号是 **SQL 标准标识符引用**，ClickHouse / Postgres / DuckDB /
InfluxDB 3 均支持。

### 4.4 已知限制：远端列名必须是 ASCII 标识符

`metric.time_column` / `value_column` / `group_column` 仍走 `validate_identifier`
（`^[A-Za-z_][A-Za-z0-9_]*$`）。远端列名若含空格/中文/引号，**无法作为指标列**。
这是现有校验的既有约束，本轮不放开（放开需重新审视 SQL 注入面）。

## 5. 校验拆分（D8）

`platform/validation.py` 拆成两个函数：

```python
def validate_readonly_sql(sql: str) -> str:
    """浏览用：必须 SELECT/WITH 开头、单语句、无写关键字。不要求 $timefilter。"""

def validate_query(sql: str) -> str:
    """指标用：validate_readonly_sql + 必须恰好一个 $timefilter。"""
```

`validate_query` 的**语义不变** → 现有调用方（`store.py` 的 `add_metric` /
`update_metric`、`sqlite_source.py`）零改动。

## 6. 数据浏览器

### 6.1 后端端点

```
POST /api/platform/sources/{id}/query
  body: { "sql": "...", "start": "2026-10-30T00:00:00Z", "end": "2026-10-31T00:00:00Z",
          "limit": 100,
          "time_column": "ts", "time_format": "iso_utc", "source_timezone": "UTC" }
  resp: { "columns": [{"name": "ts", "type": "TIMESTAMP"}],
          "rows": [[...]], "elapsed_ms": 12, "truncated": false }
```

- `sql` 走 `validate_readonly_sql`。
- `time_column` / `time_format` / `source_timezone` **仅当 SQL 含 `$timefilter` 时需要**。
- `{start}` / `{end}` 占位符替换成 §4.2 的字面量（若 SQL 里写了）。
- `limit` 作用于浏览预览；**检测取数不受此限**。
- **只保留一个防 OOM 的兜底常量**，不作为设计特性。

**列类型**（D12）：从 pandas dtype 推断 ——
`TIMESTAMP`（datetime64）/ `INTEGER` / `REAL` / `TEXT`（其它）。

### 6.2 错误分类（明确状态码）

| 情形 | 状态码 | 消息来源 |
|---|---|---|
| 本地校验失败（非 SELECT、写关键字、多语句） | 400 | 本地 |
| `$timefilter` 缺 `time_column` | 400 | 本地 |
| 远端 4xx（如 SQL 语法错） | 502 | 透传远端的状态码与消息体 |
| 远端 5xx | 502 | 透传远端的消息 |
| 请求超时 | 504 | 本地 |
| 响应无法解析（非法 JSON/CSV、`rows_path` 不存在） | 502 | 本地说明 + 远端响应片段 |

「远端 SQL 错」与「本地 SQL 非法」都可能出现 —— 用**状态码 + 消息来源**区分，
前端在错误框里标明是本地校验还是远端返回。

### 6.3 前端 UI（数据源详情页新增「浏览数据」）

1. **SQL 编辑器** —— 等宽 textarea + 「执行」按钮（`{start}`/`{end}` 提示）
2. **时间范围选择器** —— 值替换 `{start}` / `{end}`
3. **时间列输入（可选）** —— 仅当 SQL 里含 `$timefilter` 时需要，附说明
4. **结果表格** —— 列名（带推断类型）+ 前 N 行
5. **「用这个结果建指标」** —— 打开指标表单并自动带入：
   - 每个列旁一个下拉（`时间列` / `值列` / `分组列`），点一下即填入对应字段
   - `TIMESTAMP` 类型的列自动推断 `time_format = iso_utc`
   - `INTEGER` 类型的列提示选择 `epoch_s` / `epoch_ms`
   - 显示总行数

### 6.4 kind-aware

SQL 型源显示 SQL 编辑器。**第二层连接器（未来）显示该源专属表单**，不显示编辑器。
本轮只有 SQL 型源，但组件结构留出这个分支（`kind !== 'sqlite' && kind !== 'http'` 的分支）。

## 7. 行数上限（MAX_ROWS）的归属

| 路径 | 现状 | 本轮 |
|---|---|---|
| SQLite 检测取数 | SQL 层 `LIMIT ?` + 超过 10 万行报错 | **不变** |
| HTTP 检测取数 | —— | **不设限**（远端算完再回来） |
| 浏览预览 | —— | 由 `limit` 参数控制 |

⚠️ SQLite 与 HTTP 的这个差异是**有意为之**：SQLite 侧的历史限制是为了防本地内存爆掉，
HTTP 侧数据在远端，不占本地内存。

## 8. 测试策略

### 后端

| 测试 | 内容 |
|---|---|
| 连接器一致性 | sqlite 与 http 跑**同一套用例**：同一段 SQL、同一区间 → 两条路径返回相同的 SeriesBundle 集合。⚠️ 断言用「同集合 + 边界一致」，不写「字节级相等」 |
| 时间替换 | `$timefilter` 两套方言；四种 `time_format` 的字面量生成；`iso_utc` 的 `+00:00` 边界用例 |
| 校验拆分 | `DELETE` / `DROP` / 多语句 / 缺 `$timefilter` 各自被拒；`validate_query` 语义未变 |
| 浏览端点 | 列名/行数/耗时字段；非法 SQL → 400；远端 500 → 502；超时 → 504 |
| 脱敏 | `GET` source / `catalog` 不返回明文密钥；带脱敏值回写时保留原值 |
| kind 校验 | 非法 kind 被拒 |
| 端点契约 | `frontend/src/api/endpoints.test.ts` 的 `EXPECTED_PATHS` 与 `tests/web/test_api_contract.py` 双向守卫同步更新 |

**测试夹具**：pytest 里起一个假 HTTP SQL 端点（`http.server` 或 FastAPI `TestClient`），
返回可控的 JSON / CSV / 错误响应。**这不是 spec 2 的「假远端时序数据库」** ——
它只是测试夹具，不承担「持续产数」职责。

### 前端

- vitest：执行 SQL → 显示列与行；「从结果建指标」带入列名与推断的 `time_format`。
- antd 注意：中文两字按钮自动插空格（断言用 `/执\s*行/`）；`Select` 非原生 select。

## 9. 文档更新

| 文档 | 改动 |
|---|---|
| `docs/ARCHITECTURE.md` | mermaid 与正文中「`sqlite_source.load_series` 是边界」→ 改为「连接器层」 |
| `docs/PLATFORM.md` | 第 410 行「只支持 SQLite 一种数据源」→ 改为「SQLite + HTTP 透传」；新增「数据浏览器」小节 |
| `docs/ROADMAP.md` | 数据源插件化条目 → 标记为「SQL 型已完成（透传），专有型待做」 |

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 透传 SQL 原样发远端，黑名单可绕过 | UI 明示「SQL 将发到 `<url>` 执行」；文档要求只读凭据；平台侧只读校验作第二道防线 |
| 远端慢/不可达 → 检测任务失败 | HTTP 超时默认 30s；失败原因落 `runs` 表（`runner.py` 已有）；告警页显示失败任务 |
| 响应格式千差万别 | 先支持 `json` / `csv` / `jsonl` + 可选 `rows_path`；不够再加 |
| 密钥明文存 `platform.db` | 响应脱敏 + 回写保留原值；文档注明生产应走密钥管理 |
| 远端方言差异（标识符引用、时间字面量） | 只依赖 SQL 标准的双引号标识符 + ISO8601 时间字面量；接非标准远端时在文档里记一笔 |
| 新增依赖破坏离线安装 | 本轮**零新依赖** |

## 11. 与后续 spec 的关系

```
spec 1（本文）  连接器 + 数据浏览器
spec 2           假远端时序数据库（持续产数 + InfluxDB 3 形状的 SQL 端点）+ 活数据
spec 3           检测记录页筛选与分页
spec 4           数据保留与清理策略
贯穿             每个 spec 补 CI；容器化最后做
```

**spec 2 的两条约束**（本轮定下，避免返工）：

1. 假远端写入的是 `data/platform/source.db`，该文件当前 `journal_mode=delete`
   —— 假远端必须**自己开 WAL**（平台侧 store 的 WAL 是 `data/platform.db`，
   与它无关）。平台以 `file:...?mode=ro` 只读打开 WAL 库依赖同目录 `-shm`/`-wal`
   可访问，spec 2 要专门验证这个组合。
2. spec 4 的清理策略要覆盖 spec 2 持续写入的数据 —— 但**不能清掉模拟源的当前窗口**
   （否则演示当场断流）。清理按保留期，且排除模拟源。

## 12. 后续扩展：第二层连接器（预留，不实现）

**能接受 SQL 的时序库 → 第一层（透传），零代码**：

| 源 | SQL 端点 |
|---|---|
| InfluxDB 3 / Cloud Serverless / Dedicated | `POST /api/v3/query_sql`，体 `{"db","q","format"}` |
| ClickHouse | `POST /?query=` |
| TDengine | `POST /rest/sql` |
| Druid / Pinot | SQL-over-HTTP |
| Trino / Presto | REST 接口收 SQL |

**只有专有查询语言的 → 第二层（专用连接器）**：

Prometheus（PromQL）、InfluxDB 2.x（InfluxQL）。**SQL→PromQL 无法自动翻译**
（不是同一种语言）。这类源实现同一个 `fetch` 协议，内部用源专属配置构造查询。

因此指标模型预留：

- `Metric.query` —— SQL 型源用
- `Metric.config`（JSON）—— 专有型源用（bucket / measurement / field / aggregation 等）

两个字段对上层（检测、告警、浏览器）完全等价：连接器的 `fetch` 返回同一张表。
