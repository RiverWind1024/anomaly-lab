/* ============================================================
   检测记录页共用逻辑
   左栏：记录索引（序列 × 算法），可筛选、可分页；右栏：详情
   —— 与真实应用同一套结构，只是把 AntD 换成原生控件。
   ============================================================ */
;(function () {
  var LABEL = {
    high_zero_ratio: '高零比',
    periodic: '周期',
    sparse_event: '稀疏事件',
    stationary: '平稳',
    step: '阶跃',
    trending: '趋势',
  }

  var KIND = {
    false_negative: { label: '漏报', cls: 'p0' },
    false_positive: { label: '误报', cls: 'p1' },
  }

  var PAGE_SIZE = 20

  function timestampsOf(d) {
    if (d.timestamps) return d.timestamps
    var out = []
    var t = Date.parse(d.t0 + 'Z')
    for (var i = 0; i < d.values.length; i++) {
      out.push(new Date(t).toISOString().slice(0, 19))
      t += d.step_min * 60000
    }
    return out
  }

  function init(opts) {
    var D = window.SAMPLE.detections
    var fmtTime = window.SampleChart.fmtTime

    var listEl = document.getElementById('seriesList')
    var chipsEl = document.getElementById('clsChips')
    var detChipsEl = document.getElementById('detChips')
    var srcChipsEl = document.getElementById('srcChips')
    var timeChipsEl = document.getElementById('timeChips')
    var pagerEl = document.getElementById('pager')
    var detailEl = document.getElementById('detail')
    var metaEl = document.getElementById('seriesMeta')

    var clsFilter = 'all'
    var detFilter = 'all'
    var srcFilter = 'all'
    var timeFilter = 'all'
    var page = 1
    var current = null

    var classes = []
    var detectors = []
    var sources = []
    D.rows.forEach(function (r) {
      if (classes.indexOf(r.metric_class) < 0) classes.push(r.metric_class)
      if (detectors.indexOf(r.detector) < 0) detectors.push(r.detector)
      if (sources.indexOf(r.source) < 0) sources.push(r.source)
    })

    function chip(label, count, active) {
      return (
        '<button type="button" aria-pressed="' + (active ? 'true' : 'false') + '">' +
        label + '<span class="n">' + count + '</span></button>'
      )
    }

    function bind(box, pick) {
      ;[].forEach.call(box.querySelectorAll('button'), function (b, i) {
        b.addEventListener('click', function () {
          pick(i)
          page = 1
          renderChips()
          renderList()
          renderDetail()
        })
      })
    }

    function renderChips() {
      chipsEl.innerHTML =
        chip('全部形态', D.rows.length, clsFilter === 'all') +
        classes.map(function (k) {
          return chip(LABEL[k], D.rows.filter(function (r) { return r.metric_class === k }).length, clsFilter === k)
        }).join('')
      detChipsEl.innerHTML =
        chip('全部算法', D.rows.length, detFilter === 'all') +
        detectors.map(function (k) {
          return chip(k, D.rows.filter(function (r) { return r.detector === k }).length, detFilter === k)
        }).join('')
      srcChipsEl.innerHTML =
        chip('全部来源', D.rows.length, srcFilter === 'all') +
        sources.map(function (k) {
          return chip(k, D.rows.filter(function (r) { return r.source === k }).length, srcFilter === k)
        }).join('')
      timeChipsEl.innerHTML =
        chip('全部时间', D.rows.length, timeFilter === 'all') +
        chip('最近 7 天', D.rows.filter(function (r) { return r.start_ts >= '2026-01-05' }).length, timeFilter === '7d') +
        chip('最近 30 天', D.rows.filter(function (r) { return r.start_ts >= '2026-01-01' }).length, timeFilter === '30d')

      bind(chipsEl, function (i) { clsFilter = i === 0 ? 'all' : classes[i - 1] })
      bind(detChipsEl, function (i) { detFilter = i === 0 ? 'all' : detectors[i - 1] })
      bind(srcChipsEl, function (i) { srcFilter = i === 0 ? 'all' : sources[i - 1] })
      bind(timeChipsEl, function (i) { timeFilter = i === 0 ? 'all' : i === 1 ? '7d' : '30d' })
    }

    function filtered() {
      return D.rows.filter(function (r) {
        if (clsFilter !== 'all' && r.metric_class !== clsFilter) return false
        if (detFilter !== 'all' && r.detector !== detFilter) return false
        if (srcFilter !== 'all' && r.source !== srcFilter) return false
        if (timeFilter === '7d' && r.start_ts < '2026-01-05') return false
        if (timeFilter === '30d' && r.start_ts < '2026-01-01') return false
        return true
      })
    }

    function renderList() {
      var rows = filtered()
      var pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
      if (page > pages) page = pages
      var slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

      listEl.innerHTML = slice.map(function (r) {
        var id = r.series_id + '|' + r.detector
        return (
          '<div class="seriesrow' + (current === id ? ' is-active' : '') + '"' +
            ' role="option" tabindex="0" data-id="' + id + '">' +
            '<span class="seriesrow__id">' + r.series_id + '</span>' +
            '<span class="seriesrow__n">' + r.detector + ' · ' + r.f1.toFixed(3) + '</span>' +
          '</div>'
        )
      }).join('') || '<div class="empty" style="margin:10px"><p class="empty__t">没有匹配的记录</p></div>'

      ;[].forEach.call(listEl.querySelectorAll('.seriesrow'), function (row) {
        function pick() {
          current = row.dataset.id
          renderList()
          renderDetail()
        }
        row.addEventListener('click', pick)
        row.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            pick()
          }
        })
      })

      pagerEl.innerHTML =
        '<button class="btn btn--ghost btn--sm" type="button" id="prev"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>' +
        '<span class="toolbar__note">第 ' + page + ' / ' + pages + ' 页</span>' +
        '<button class="btn btn--ghost btn--sm" type="button" id="next"' + (page >= pages ? ' disabled' : '') + '>下一页</button>'
      var prev = document.getElementById('prev')
      var next = document.getElementById('next')
      prev.addEventListener('click', function () { if (page > 1) { page -= 1; renderList() } })
      next.addEventListener('click', function () { if (page < pages) { page += 1; renderList() } })

      if (metaEl) {
        var truth = rows.reduce(function (a, r) { return a + r.n_truth }, 0)
        metaEl.textContent =
          rows.length + ' 条记录 · ' + truth.toLocaleString('en-US') + ' 个真值异常点'
      }
      return rows
    }

    function currentRow() {
      if (!current) return null
      var parts = current.split('|')
      return D.rows.filter(function (r) {
        return r.series_id === parts[0] && r.detector === parts[1]
      })[0]
    }

    function renderDetail() {
      var row = currentRow()
      if (!row) {
        detailEl.innerHTML =
          '<div class="empty"><p class="empty__t">选一条记录</p>' +
          '<p class="empty__d">左栏是「序列 × 算法」的记录索引</p></div>'
        return
      }
      var d = D.details[row.series_id]
      var ts = timestampsOf(d)
      var marks = d.labels.filter(function (v) { return v === 1 }).length
      var filteredOut = filtered().indexOf(row) < 0

      var head =
        '<div class="panel__head">' +
          '<div>' +
            '<h2 class="panel__title num">' + row.series_id + '</h2>' +
            '<p class="panel__meta num">' + LABEL[row.metric_class] + ' · ' +
              d.values.length + ' 点 · ' + marks + ' 个真值异常点 · ' +
              row.detector + ' / ' + d.score_type + '</p>' +
            (filteredOut
              ? '<p class="panel__meta" style="color: var(--p1)">这条记录不在当前筛选结果里</p>'
              : '') +
          '</div>' +
          '<span class="pill ' + (row.f1 === 0 ? 'pill--p0' : 'pill--ok') + '">F1 ' + row.f1.toFixed(3) + '</span>' +
        '</div>'

      var chart =
        '<div class="legend" aria-hidden="true">' +
          '<span class="legend__item"><i class="swatch swatch--line"></i>信号</span>' +
          '<span class="legend__item"><i class="swatch swatch--mark"></i>真值异常点</span>' +
        '</div>' +
        '<div class="chart chart--series" id="chart"></div>'

      var stats =
        '<dl class="runlog__grid">' +
          '<dt>阈值</dt><dd class="num">' + d.threshold.toFixed(2) + '</dd>' +
          '<dt>Precision</dt><dd class="num">' + row.precision.toFixed(3) + '</dd>' +
          '<dt>Recall</dt><dd class="num">' + row.recall.toFixed(3) + '</dd>' +
          '<dt>F1</dt><dd class="num">' + row.f1.toFixed(3) + '</dd>' +
          '<dt>真值 / 预测</dt><dd class="num">' + row.n_truth + ' / ' + row.n_pred + '</dd>' +
          '<dt>时间范围</dt><dd class="num">' + fmtTime(ts[0]) + ' – ' + fmtTime(ts[ts.length - 1]).slice(6) + '</dd>' +
        '</dl>'

      var bad = d.badcases
      var badBlock =
        '<div class="runlog">' +
          '<div class="runlog__head"><span>检测偏差</span><span class="num">' + bad.length + '</span></div>' +
          (bad.length
            ? '<ul class="eventlist">' + bad.map(function (b) {
                var k = KIND[b.kind] || { label: b.kind, cls: 'p1' }
                return '<li class="event">' +
                  '<span class="pill pill--' + k.cls + '">' + k.label + '</span>' +
                  '<span class="event__main">' +
                    '<span class="event__series">' + b.group + '</span>' +
                    '<span class="event__time">' + b.reason + '</span>' +
                  '</span>' +
                  '<span class="event__score"><span class="num">' +
                    (b.from + 1) + '–' + (b.to + 1) + '</span></span>' +
                '</li>'
              }).join('') + '</ul>'
            : '<div class="empty" style="margin-top:10px">' +
                '<p class="empty__t">没有检测偏差</p>' +
                '<p class="empty__d">这一条既没有漏报也没有误报</p></div>') +
        '</div>'

      detailEl.innerHTML = head + chart + stats + badBlock

      var chartEl = document.getElementById('chart')
      window.SampleChart.seriesChart(chartEl, {
        series_id: row.series_id,
        timestamps: ts,
        values: d.values,
        labels: d.labels,
      })
    }

    renderChips()
    renderList()
    // 默认选第一条，右栏不留空
    var rows = filtered()
    if (rows.length) {
      current = rows[0].series_id + '|' + rows[0].detector
      renderList()
    }
    renderDetail()

    function redraw() {
      var row = currentRow()
      if (!row) return
      var d = D.details[row.series_id]
      window.SampleChart.seriesChart(document.getElementById('chart'), {
        series_id: row.series_id,
        timestamps: timestampsOf(d),
        values: d.values,
        labels: d.labels,
      })
    }

    window.addEventListener('themechange', redraw)
    var raf
    window.addEventListener('resize', function () {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(redraw)
    })
  }

  window.SeriesPage = { init: init }
})()
