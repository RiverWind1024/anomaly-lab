let chart;
let current = null;

async function loadSeries() {
  const resp = await fetch('/api/series');
  const items = await resp.json();
  const select = document.getElementById('series-select');
  select.innerHTML = '';
  for (const item of items) {
    const option = document.createElement('option');
    option.value = item.series_id;
    option.textContent = `${item.series_id} (${item.metric_class}, n=${item.n})`;
    select.appendChild(option);
  }
  if (items.length) {
    select.value = items[0].series_id;
    await loadSeriesData(items[0].series_id);
  }
}

async function loadSeriesData(seriesId) {
  const [valuesResp, annResp] = await Promise.all([
    fetch(`/api/series/${seriesId}/values`),
    fetch(`/api/annotate/${seriesId}`),
  ]);
  const data = await valuesResp.json();
  const annotations = (await annResp.json()).intervals || [];
  current = data;
  render(data, annotations);
}

function render(data, annotations) {
  if (!chart) chart = echarts.init(document.getElementById('chart'));
  const areas = annotations.map(item => [
    { xAxis: item.start, itemStyle: { color: 'rgba(239,68,68,0.25)' } },
    { xAxis: item.end },
  ]);
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 30, bottom: 80 },
    xAxis: { type: 'category', data: data.timestamps, boundaryGap: false },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 24 }],
    series: [{
      type: 'line',
      showSymbol: false,
      data: data.values,
      markArea: { silent: true, data: areas },
    }],
    toolbox: { feature: { restore: {} } },
    brush: { xAxisIndex: 0, brushMode: 'single', throttleType: 'debounce', throttleDelay: 300 },
  }, true);
  chart.off('brushSelected');
  chart.on('brushSelected', async params => {
    const selected = params.batch && params.batch[0] && params.batch[0].selected;
    if (!selected || !selected.length) return;
    const range = selected[0].coordRange;
    if (!range || range.length < 2) return;
    const start = Math.min(...range);
    const end = Math.max(...range);
    const type = prompt('异常类型（spike/contextual/drift/freq_shift/variance_shift/flatline）', 'spike');
    if (!type) return;
    await fetch(`/api/annotate/${current.series_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intervals: [{ start, end, type }] }),
    });
    chart.dispatchAction({ type: 'brush', areas: [] });
    await loadSeriesData(current.series_id);
  });
}

document.getElementById('series-select').addEventListener('change', event => {
  loadSeriesData(event.target.value);
});
document.getElementById('reload').addEventListener('click', loadSeries);
loadSeries();
