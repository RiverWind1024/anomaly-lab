let chart;
let catalog = { sources: [], metrics: [], jobs: [], detectors: [] };

async function api(url, options) {
  const resp = await fetch(url, options);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    alert(body.detail || `请求失败: ${resp.status}`);
    throw new Error(body.detail || resp.status);
  }
  return body;
}

function postJson(url, payload) {
  return api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

function parseRules(text) {
  const rules = [];
  for (const line of String(text || '').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [expr, ...rest] = trimmed.split(',');
    const level = rest.join(',').trim();
    if (!level) {
      alert(`规则行缺少等级：${trimmed}`);
      return null;
    }
    const condition = expr.trim();
    // 绝对值条件：>50 / >= 50 / <10 / <= 10
    const absolute = condition.match(/^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$/);
    if (absolute) {
      rules.push({ op: absolute[1], value: Number(absolute[2]), level });
      continue;
    }
    const value = Number(condition);
    if (!Number.isFinite(value) || value <= 0) {
      alert(`规则行格式不对：${trimmed}（应为「倍数, 等级」或「>50, 等级」）`);
      return null;
    }
    rules.push({ multiplier: value, level });
  }
  return rules.length ? rules : null;
}

function formatRules(rules) {
  if (!rules || !rules.length) return '-';
  return rules.map(rule => {
    const condition = rule.multiplier === undefined || rule.multiplier === null
      ? `${rule.op}${rule.value}`
      : `${rule.multiplier}×`;
    return `${condition}→${rule.level}`;
  }).join(' / ');
}

function fillSelect(select, items, valueKey, labelFn, keepValue) {
  const previous = keepValue ? select.value : null;
  select.innerHTML = '';
  for (const item of items) {
    const option = document.createElement('option');
    option.value = item[valueKey];
    option.textContent = labelFn(item);
    select.appendChild(option);
  }
  if (previous) select.value = previous;
}

function renderTables() {
  const srcRows = document.getElementById('src-rows');
  srcRows.innerHTML = catalog.sources.map(s =>
    `<tr><td>${s.id}</td><td>${s.name}</td><td>${s.kind}</td><td>${s.path}</td></tr>`).join('');

  const metricRows = document.getElementById('metric-rows');
  const sourceName = id => (catalog.sources.find(s => s.id === id) || {}).name || id;
  metricRows.innerHTML = catalog.metrics.map(m =>
    `<tr><td>${m.id}</td><td>${m.name}</td><td>${sourceName(m.source_id)}</td>` +
    `<td>${m.group_column || '-'}</td><td>${m.freq}</td></tr>`).join('');

  const jobRows = document.getElementById('job-rows');
  const metricName = id => (catalog.metrics.find(m => m.id === id) || {}).name || id;
  jobRows.innerHTML = catalog.jobs.map(j =>
    `<tr><td>${j.id}</td><td>${j.name}</td><td>${metricName(j.metric_id)}</td>` +
    `<td>${j.detector === 'auto' ? '自动推荐' : j.detector}</td>` +
    `<td>${formatRules(j.alert_rules)}</td><td>${j.interval_seconds}s</td><td>${j.enabled ? '启用' : '停用'}</td>` +
    `<td><button data-run="${j.id}">立即运行</button> ` +
    `<button data-toggle="${j.id}" data-enabled="${j.enabled}">${j.enabled ? '停用' : '启用'}</button></td></tr>`).join('');

  fillSelect(document.getElementById('metric-source'), catalog.sources, 'id', s => `${s.name} (${s.path})`);
  fillSelect(document.getElementById('job-metric'), catalog.metrics, 'id', m => m.name);
  fillSelect(document.getElementById('preview-job'), catalog.jobs, 'id', j => j.name, true);

  for (const button of document.querySelectorAll('[data-run]')) {
    button.addEventListener('click', () => runJob(button.dataset.run));
  }
  for (const button of document.querySelectorAll('[data-toggle]')) {
    button.addEventListener('click', () => toggleJob(button));
  }
}

async function refreshCatalog() {
  catalog = await api('/api/platform/catalog');
  fillSelect(document.getElementById('job-detector'), catalog.detectors, 'name',
    d => `${d.label || d.name} (${d.score_type})`);
  renderTables();
}

async function runJob(jobId) {
  await postJson(`/api/platform/jobs/${jobId}/run`, {});
  await refreshCatalog();
  const jobSelect = document.getElementById('preview-job');
  jobSelect.value = jobId;
  await loadRuns(jobId);
}

async function toggleJob(button) {
  const enabled = button.dataset.enabled !== 'true';
  await api(`/api/platform/jobs/${button.dataset.toggle}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  await refreshCatalog();
}

async function loadRuns(jobId) {
  const data = await api(`/api/platform/jobs/${jobId}/runs`);
  fillSelect(document.getElementById('preview-run'), data.runs, 'id',
    r => `#${r.id} ${r.status} (${r.n_series} 序列 / ${r.n_alerts} 告警)`
       + (r.error ? ` · ${r.error.slice(0, 40)}` : ''), true);
  await loadPreview();
}

async function loadPreview() {
  const jobId = document.getElementById('preview-job').value;
  if (!jobId) return;
  const runId = document.getElementById('preview-run').value;
  const seriesId = document.getElementById('preview-series').value;
  const params = new URLSearchParams();
  if (runId) params.set('run_id', runId);
  if (seriesId) params.set('series_id', seriesId);
  const data = await api(`/api/platform/jobs/${jobId}/preview?${params.toString()}`);

  fillSelect(document.getElementById('preview-series'), data.series, 'series_id',
    s => `${s.series_id} (${s.sufficient === false ? '数据不足' : `${s.n_alerts} 告警`})`, true);
  const hint = document.getElementById('preview-hint');
  if (data.sufficient === false) {
    hint.textContent = `${data.series_id} · 数据不足：${data.insufficient_reason || '有效点太少'}`;
  } else {
    const auto = data.requested_detector === 'auto';
    const shape = auto
      ? ` · 形态 ${data.metric_class || '未判定'}${data.detector_fallback ? '（回退）' : ''}`
      : '';
    hint.textContent =
      `${data.series_id} · ${auto ? `自动 → ${data.detector}` : data.detector}`
      + `${shape} · ${data.score_type} · 规则 ${formatRules(data.alert_rules)}`
      + (data.sampled ? ` · 点数过多，已抽样 ${data.timestamps.length}/${data.original_n}` : '');
    if (auto && data.detector_rationale) {
      hint.title = data.detector_rationale;
    }
  }
  // 预填反馈表单：序列与时间范围取当前预览
  document.getElementById('fb-series').value = data.series_id;
  if (data.timestamps.length) {
    document.getElementById('fb-start').value = data.timestamps[0];
    document.getElementById('fb-end').value = data.timestamps[data.timestamps.length - 1];
  }
  await loadFeedback(jobId);
  render(data);
}

function render(data) {
  if (!chart) chart = echarts.init(document.getElementById('chart'));
  if (!data.values.length) {
    chart.clear();
    return;
  }
  const points = data.values.map((value, index) => ({
    value: [index, value],
    score: data.scores[index],
    severity: data.severity[index],
  }));
  const levels = data.levels || ['正常'];
  const colors = ['#94a3b8', '#eab308', '#f97316', '#dc2626', '#7c3aed'];
  const alertSeries = [];
  for (let level = 1; level < levels.length; level += 1) {
    const items = points.filter(p => p.severity === level).map(p => p.value);
    if (!items.length) continue;
    alertSeries.push({
      name: levels[level],
      type: 'scatter',
      symbolSize: 8 + level * 2,
      itemStyle: { color: colors[Math.min(level, colors.length - 1)] },
      data: items,
    });
  }
  const series = [{
    name: '实际值',
    type: 'line',
    showSymbol: false,
    data: data.values,
  }];
  if (data.baseline) {
    const width = data.upper.map((upper, index) => upper - data.lower[index]);
    series.push({
      name: '基线',
      type: 'line',
      showSymbol: false,
      lineStyle: { type: 'dashed', color: '#94a3b8' },
      data: data.baseline,
    });
    series.push({
      name: '下界',
      type: 'line',
      stack: 'band',
      showSymbol: false,
      lineStyle: { opacity: 0 },
      areaStyle: { opacity: 0 },
      data: data.lower,
    });
    series.push({
      name: '区间',
      type: 'line',
      stack: 'band',
      showSymbol: false,
      lineStyle: { opacity: 0 },
      areaStyle: { color: 'rgba(37, 99, 235, 0.12)' },
      data: width,
    });
  }
  series.push(...alertSeries);

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 30, bottom: 80 },
    xAxis: { type: 'category', data: data.timestamps, boundaryGap: false },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 24 }],
    legend: { data: ['实际值', '基线', ...levels.slice(1)] },
    series,
  }, true);
}

document.getElementById('src-add').addEventListener('click', async () => {
  await postJson('/api/platform/sources', {
    name: document.getElementById('src-name').value,
    path: document.getElementById('src-path').value,
  });
  await refreshCatalog();
});

document.getElementById('metric-add').addEventListener('click', async () => {
  const group = document.getElementById('metric-group-col').value.trim();
  await postJson('/api/platform/metrics', {
    source_id: Number(document.getElementById('metric-source').value),
    name: document.getElementById('metric-name').value,
    query: document.getElementById('metric-query').value,
    time_column: document.getElementById('metric-time-col').value,
    value_column: document.getElementById('metric-value-col').value,
    group_column: group || null,
    time_format: document.getElementById('metric-time-format').value,
    source_timezone: document.getElementById('metric-timezone').value.trim() || 'UTC',
    missing_policy: document.getElementById('metric-missing').value,
    freq: document.getElementById('metric-freq').value,
  });
  await refreshCatalog();
});

document.getElementById('job-add').addEventListener('click', async () => {
  const rules = parseRules(document.getElementById('job-rules').value);
  if (rules === null && String(document.getElementById('job-rules').value).trim()) return;
  await postJson('/api/platform/jobs', {
    metric_id: Number(document.getElementById('job-metric').value),
    name: document.getElementById('job-name').value,
    detector: document.getElementById('job-detector').value,
    window_points: Number(document.getElementById('job-window').value),
    interval_seconds: Number(document.getElementById('job-interval').value),
    alert_rules: rules,
  });
  await refreshCatalog();
});

document.getElementById('job-detector').addEventListener('change', event => {
  const detector = catalog.detectors.find(d => d.name === event.target.value);
  if (!detector) return;
  const base = detector.default_threshold;
  document.getElementById('job-rules').value = `${base}, P1\n${(base * 1.5).toFixed(2)}, P0`;
});

document.getElementById('preview-job').addEventListener('change', async event => {
  await loadRuns(event.target.value);
});
document.getElementById('preview-run').addEventListener('change', loadPreview);
document.getElementById('preview-series').addEventListener('change', loadPreview);
document.getElementById('preview-refresh').addEventListener('click', loadPreview);

// ---------- 反馈与调参 ----------

let lastSuggestion = null;

async function loadFeedback(jobId) {
  if (!jobId) return;
  const data = await api(`/api/platform/jobs/${jobId}/feedback`);
  const rows = document.getElementById('fb-rows');
  rows.innerHTML = data.feedback.map(item =>
    `<tr><td>${item.id}</td><td>${item.series_id}</td>` +
    `<td>${item.start_ts} → ${item.end_ts}</td>` +
    `<td>${item.kind}</td><td>${item.note || ''}</td></tr>`).join('');
}

document.getElementById('fb-add').addEventListener('click', async () => {
  const jobId = document.getElementById('preview-job').value;
  if (!jobId) {
    alert('请先在预览里选择一个任务');
    return;
  }
  await postJson('/api/platform/feedback', {
    job_id: Number(jobId),
    series_id: document.getElementById('fb-series').value.trim(),
    start_ts: document.getElementById('fb-start').value.trim(),
    end_ts: document.getElementById('fb-end').value.trim(),
    kind: document.getElementById('fb-kind').value,
    note: document.getElementById('fb-note').value.trim(),
  });
  await loadFeedback(jobId);
});

document.getElementById('fb-suggest').addEventListener('click', async () => {
  const jobId = document.getElementById('preview-job').value;
  if (!jobId) {
    alert('请先在预览里选择一个任务');
    return;
  }
  const data = await api(`/api/platform/jobs/${jobId}/feedback/suggestion`);
  lastSuggestion = data;
  const hint = document.getElementById('fb-suggestion');
  if (!data.best) {
    hint.textContent = data.reason;
    return;
  }
  const best = data.best;
  const fmt = value => (value === null || value === undefined ? '—' : value.toFixed(2));
  hint.textContent = `${data.reason} ｜ precision ${fmt(best.precision)}`
    + ` / recall ${fmt(best.recall)} / F1 ${fmt(best.f1)}`;
});

document.getElementById('fb-apply').addEventListener('click', async () => {
  const jobId = document.getElementById('preview-job').value;
  if (!lastSuggestion || !lastSuggestion.best) {
    alert('请先点「评估并给建议」');
    return;
  }
  await postJson(`/api/platform/jobs/${jobId}/apply-multiplier`, {
    multiplier: lastSuggestion.suggested_multiplier,
  });
  lastSuggestion = null;
  document.getElementById('fb-suggestion').textContent = '已应用，新的告警倍数见任务列表';
  await refreshCatalog();
  await loadPreview();
});

refreshCatalog().then(() => {
  const jobId = document.getElementById('preview-job').value;
  if (jobId) return loadRuns(jobId);
});
