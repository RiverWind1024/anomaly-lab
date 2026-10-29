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
    `<tr><td>${j.id}</td><td>${j.name}</td><td>${metricName(j.metric_id)}</td><td>${j.detector}</td>` +
    `<td>${j.alert_threshold} / ${j.critical_threshold}</td><td>${j.interval_seconds}s</td>` +
    `<td>${j.enabled ? '启用' : '停用'}</td>` +
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
    d => `${d.name} (${d.score_type})`);
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
    r => `#${r.id} ${r.status} (${r.n_series} 序列 / ${r.n_alerts} 告警)`, true);
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
    s => `${s.series_id} (${s.n_alerts} 告警)`, true);
  document.getElementById('preview-hint').textContent =
    `${data.series_id} · ${data.detector} · ${data.score_type} · P1>${data.alert_threshold} · P0>${data.critical_threshold}`;
  render(data);
}

function render(data) {
  if (!chart) chart = echarts.init(document.getElementById('chart'));
  const points = data.values.map((value, index) => ({
    value: [index, value],
    score: data.scores[index],
    severity: data.severity[index],
  }));
  const p1 = points.filter(p => p.severity === 1).map(p => p.value);
  const p0 = points.filter(p => p.severity === 2).map(p => p.value);
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
  series.push({
    name: 'P1',
    type: 'scatter',
    symbolSize: 8,
    itemStyle: { color: '#f59e0b' },
    data: p1,
  });
  series.push({
    name: 'P0',
    type: 'scatter',
    symbolSize: 10,
    itemStyle: { color: '#dc2626' },
    data: p0,
  });

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 30, bottom: 80 },
    xAxis: { type: 'category', data: data.timestamps, boundaryGap: false },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 24 }],
    legend: { data: ['实际值', '基线', 'P1', 'P0'] },
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
    freq: document.getElementById('metric-freq').value,
  });
  await refreshCatalog();
});

document.getElementById('job-add').addEventListener('click', async () => {
  await postJson('/api/platform/jobs', {
    metric_id: Number(document.getElementById('job-metric').value),
    name: document.getElementById('job-name').value,
    detector: document.getElementById('job-detector').value,
    alert_threshold: Number(document.getElementById('job-alert').value),
    critical_threshold: Number(document.getElementById('job-critical').value),
    window_points: Number(document.getElementById('job-window').value),
    interval_seconds: Number(document.getElementById('job-interval').value),
  });
  await refreshCatalog();
});

document.getElementById('job-detector').addEventListener('change', event => {
  const detector = catalog.detectors.find(d => d.name === event.target.value);
  if (!detector) return;
  document.getElementById('job-alert').value = detector.default_threshold;
  document.getElementById('job-critical').value = (detector.default_threshold * 1.5).toFixed(2);
});

document.getElementById('preview-job').addEventListener('change', async event => {
  await loadRuns(event.target.value);
});
document.getElementById('preview-run').addEventListener('change', loadPreview);
document.getElementById('preview-series').addEventListener('change', loadPreview);
document.getElementById('preview-refresh').addEventListener('click', loadPreview);

refreshCatalog().then(() => {
  const jobId = document.getElementById('preview-job').value;
  if (jobId) return loadRuns(jobId);
});
