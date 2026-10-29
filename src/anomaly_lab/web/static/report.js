let detailChart;

async function loadSummary() {
  const resp = await fetch('/api/summary');
  const data = await resp.json();
  const rows = data.rows || [];
  const overall = (data.summary && data.summary.overall) || {};
  const container = document.getElementById('summary');
  if (!rows.length) {
    container.innerHTML = '<p>暂无报告，请先运行 evaluate。</p>';
    return;
  }
  const header = `<p>总体：Precision=${fmt(overall.precision)}，Recall=${fmt(overall.recall)}，F1=${fmt(overall.f1)}，Range-F1=${fmt(overall.range_f1)}</p>`;
  const body = rows.map((row, index) => `
    <tr data-index="${index}">
      <td>${row.series_id}</td><td>${row.metric_class}</td><td>${row.detector}</td>
      <td>${fmt(row.precision)}</td><td>${fmt(row.recall)}</td><td>${fmt(row.f1)}</td>
      <td>${fmt(row.range_f1)}</td><td>${row.n_truth}</td><td>${row.n_pred}</td>
    </tr>`).join('');
  container.innerHTML = `${header}<table><thead><tr>
    <th>序列</th><th>形态</th><th>检测器</th><th>Precision</th><th>Recall</th><th>F1</th>
    <th>Range-F1</th><th>真值点</th><th>预测点</th></tr></thead><tbody>${body}</tbody></table>`;
  container.querySelectorAll('tbody tr').forEach(tr => {
    tr.addEventListener('click', () => showDetail(rows[Number(tr.dataset.index)]));
  });
}

function fmt(value) {
  return Number.isFinite(value) ? Number(value).toFixed(3) : '-';
}

async function showDetail(row) {
  const resp = await fetch(`/api/badcases?series_id=${encodeURIComponent(row.series_id)}`);
  const data = await resp.json();
  if (!data.scores) return;
  if (!detailChart) detailChart = echarts.init(document.getElementById('detail'));
  const threshold = Number(data.threshold || 0);
  const thresholdLine = data.scores.map(() => threshold);
  detailChart.setOption({
    title: { text: `${row.series_id} / ${row.metric_class} / ${row.detector}` },
    tooltip: { trigger: 'axis' },
    legend: { top: 28, data: ['数值', '分数', '阈值'] },
    grid: { left: 60, right: 60, top: 70, bottom: 60 },
    dataZoom: [{ type: 'inside' }],
    xAxis: { type: 'category', data: data.timestamps, boundaryGap: false },
    yAxis: [
      { type: 'value', name: 'value', scale: true },
      { type: 'value', name: 'score', min: 0 },
    ],
    series: [
      { name: '数值', type: 'line', showSymbol: false, data: data.values },
      { name: '分数', type: 'line', yAxisIndex: 1, showSymbol: false, data: data.scores },
      { name: '阈值', type: 'line', yAxisIndex: 1, showSymbol: false, data: thresholdLine, lineStyle: { type: 'dashed' } },
    ],
    markArea: data.badcases && data.badcases.length ? {} : undefined,
  }, true);
}

loadSummary();
