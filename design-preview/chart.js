/* ============================================================
   异常分数轨迹 + 告警事件条带
   纯 SVG，无依赖；颜色全部取自 CSS token，主题切换时重绘。
   window.SampleChart = { render, fmtTime, relTime }
   ============================================================ */
;(function () {
  var NS = 'http://www.w3.org/2000/svg'
  var HOUR = 3600 * 1000
  var WINDOWS = { all: Infinity, '24': 24, '12': 12, '6': 6 }

  function svgEl(name, attrs) {
    var node = document.createElementNS(NS, name)
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, attrs[k])
      })
    }
    return node
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n)
  }

  // 数据里的时间戳是不带时区的 UTC 文本，补 Z 再解析，避免本地时区偏移。
  function parseTs(ts) {
    if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(ts)) return Date.parse(ts)
    return Date.parse(ts + 'Z')
  }

  function fmtTime(ts) {
    var d = new Date(parseTs(ts))
    return (
      pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()) + ' ' +
      pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes())
    )
  }

  // 相对快照时间，用于“下次运行”；不做实时倒计时，避免样张里出现假的时间流动。
  function relTime(ts) {
    var data = window.SAMPLE && window.SAMPLE.overview
    var snapshot = data && data.snapshot
    if (!snapshot) return fmtTime(ts)
    var diff = Math.round((parseTs(ts) - parseTs(snapshot)) / 1000)
    if (diff <= 0) return '即将'
    if (diff < 60) return diff + ' 秒'
    if (diff < 3600) return Math.round(diff / 60) + ' 分钟'
    if (diff < 86400) {
      var h = Math.floor(diff / 3600)
      var m = Math.round((diff % 3600) / 60)
      return m ? h + ' 小时 ' + m + ' 分' : h + ' 小时'
    }
    return Math.round(diff / 86400) + ' 天'
  }

  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name)
    return (v && v.trim()) || fallback
  }

  function niceStep(spanH, plotW, wideLabel) {
    var steps = [1, 2, 3, 6, 12, 24]
    var labelPx = wideLabel ? 64 : 42
    for (var i = 0; i < steps.length; i++) {
      var count = spanH / steps[i]
      if (count <= 12 && plotW / count >= labelPx) return steps[i]
    }
    return 48
  }

  function render(container, trail, windowKey, events, opts) {
    if (!container || !trail || !trail.timestamps) return

    var width = container.clientWidth
    var height = container.clientHeight
    if (!width || !height) return

    var points = trail.timestamps.map(function (ts, i) {
      return { t: parseTs(ts), s: trail.scores[i], v: trail.values[i], i: i }
    })

    var tMax = points[points.length - 1].t
    var tMin = points[0].t
    var hours = WINDOWS[windowKey] || Infinity
    var from = hours === Infinity ? tMin : tMax - hours * HOUR
    var view = points.filter(function (p) { return p.t >= from })
    if (view.length < 2) view = points.slice(-2)
    var vMin = view[0].t
    var vMax = view[view.length - 1].t

    var p1 = trail.alert_threshold
    var p0 = trail.critical_threshold
    var peak = view.reduce(function (a, b) { return b.s > a.s ? b : a }, view[0])
    var yMax = Math.max(5, Math.ceil((Math.max(peak.s, p0) + 1) / 5) * 5)

    // 版面：左轴标签 / 主图 / P0+P1 条带 / 整点标签
    var padL = width < 420 ? 30 : 36
    var padR = 10
    var padT = 16
    var showStripLabels = width >= 900
    var strips = !(opts && opts.strips === false)
    var axis = !(opts && opts.axis === false)
    var plotBottom = height - (showStripLabels ? 44 : strips ? 34 : 24)
    var plotW = Math.max(20, width - padL - padR)
    var plotH = Math.max(24, plotBottom - padT)

    function x(t) {
      return padL + ((t - vMin) / (vMax - vMin || 1)) * plotW
    }
    function y(score) {
      return padT + (1 - score / yMax) * plotH
    }

    var chart = container.querySelector('svg')
    if (chart) chart.remove()
    var tip = container.querySelector('.chart__tip')
    if (tip) tip.setAttribute('data-on', '0')

    var root = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: width,
      height: height,
      role: 'img',
      'aria-label':
        trail.series + ' 异常分数轨迹：' + view.length + ' 个点，最高 ' +
        peak.s.toFixed(2) + 'σ，P1 阈值 ' + p1 + '，P0 阈值 ' + p0,
    })
    container.appendChild(root)

    var ink3 = css('--ink-3', '#7f7f8b')
    var grid = css('--grid', 'rgba(255,255,255,.07)')
    var line = css('--line', '#26262b')
    var chartHue = css('--chart', '#6da8e3')
    var chartFill = css('--chart-fill', 'rgba(109,168,227,.09)')
    var p1c = css('--p1', '#f59e0b')
    var p0c = css('--p0', '#ef4444')
    var ink = css('--ink', '#fafafa')
    var panel = css('--panel', '#111113')

    // ── 横向网格 + y 轴刻度 ──
    var tickStep = yMax / 3
    for (var g = 0; g <= 3; g++) {
      var gv = tickStep * g
      var gy = y(gv)
      root.appendChild(
        svgEl('line', {
          x1: padL, x2: width - padR, y1: gy, y2: gy,
          stroke: grid, 'stroke-width': 1,
        })
      )
      if (g > 0 && axis) {
        root.appendChild(
          svgEl('text', {
            x: padL - 7, y: gy, fill: ink3, 'text-anchor': 'end',
            'dominant-baseline': 'middle',
          })
        ).textContent = String(Math.round(gv))
      }
    }

    // 基线
    root.appendChild(
      svgEl('line', {
        x1: padL, x2: width - padR, y1: plotBottom, y2: plotBottom,
        stroke: line, 'stroke-width': 1,
      })
    )

    // ── 两条阈值：P1 先画，P0 压在它下面更醒目 ──
    ;[
      { v: p1, c: p1c, name: 'P1' },
      { v: p0, c: p0c, name: 'P0' },
    ].forEach(function (th) {
      var ty = y(th.v)
      root.appendChild(
        svgEl('line', {
          x1: padL, x2: width - padR, y1: ty, y2: ty,
          stroke: th.c, 'stroke-width': 1, 'stroke-dasharray': '4 4',
          'stroke-opacity': 0.55,
        })
      )
      if (width >= 560 && axis) {
        root.appendChild(
          svgEl('text', {
            x: width - padR - 2,
            y: th.v === p0 ? Math.max(padT + 12, ty - 6) : Math.min(plotBottom - 2, ty + 12),
            fill: th.c,
            'text-anchor': 'end',
          })
        ).textContent = th.name + ' ' + th.v
      }
    })

    // ── 曲线下的极淡底 + 曲线 ──
    var d = view.map(function (p, i) {
      return (i ? 'L' : 'M') + x(p.t).toFixed(2) + ' ' + y(p.s).toFixed(2)
    })
    var area = d.join(' ') +
      ' L' + x(vMax).toFixed(2) + ' ' + plotBottom +
      ' L' + x(vMin).toFixed(2) + ' ' + plotBottom + ' Z'
    root.appendChild(svgEl('path', { d: area, fill: chartFill }))
    root.appendChild(
      svgEl('path', {
        d: d.join(' '),
        fill: 'none',
        stroke: chartHue,
        'stroke-width': 1.75,
        'stroke-linejoin': 'round',
        'stroke-linecap': 'round',
      })
    )

    // ── 告警事件条带：P0 一行、P1 一行，事件来自 /alerts 的合并区间 ──
    var stripH = 6
    var p0RowY = plotBottom + 5
    var p1RowY = p0RowY + stripH + (showStripLabels ? 10 : 3)

    if (strips) {
      function track(rowY) {
        root.appendChild(
          svgEl('rect', {
            x: padL, y: rowY, width: plotW, height: stripH, rx: 1,
            fill: grid, 'fill-opacity': 0.5,
          })
        )
      }
      track(p0RowY)
      track(p1RowY)

      ;(events || []).forEach(function (e) {
        var start = Math.max(vMin, parseTs(e.start))
        var end = Math.min(vMax, parseTs(e.end || e.start))
        if (end < vMin || start > vMax) return
        var ex = x(start)
        var ew = Math.max(3, x(end) - ex)
        var isP0 = e.level_index >= 2
        root.appendChild(
          svgEl('rect', {
            x: Math.min(ex, width - padR - ew), y: isP0 ? p0RowY : p1RowY,
            width: ew, height: stripH, rx: 1,
            fill: isP0 ? p0c : p1c,
          })
        )
      })

      // 条带左侧标签只在宽屏显示；窄屏靠上方图例识别
      if (showStripLabels) {
        ;[
          { y: p0RowY, t: 'P0', c: p0c },
          { y: p1RowY, t: 'P1', c: p1c },
        ].forEach(function (row) {
          root.appendChild(
            svgEl('text', {
              x: padL - 7, y: row.y + stripH - 1, fill: row.c,
              'text-anchor': 'end', 'font-size': 11,
            })
          ).textContent = row.t
        })
      }
    }

    // ── 峰值标注 ──
    if (peak.s >= p1 && axis) {
      var py = y(peak.s)
      root.appendChild(
        svgEl('circle', {
          cx: x(peak.t), cy: py, r: 3.2, fill: chartHue,
          stroke: panel, 'stroke-width': 1.5,
        })
      )
      var label = peak.s.toFixed(2) + 'σ · ' + fmtTime(trail.timestamps[peak.i])
      // 标注宽度按等宽字估算，避免在窄屏压到 y 轴刻度
      var halfLabel = label.length * 3.5
      var px = Math.min(
        Math.max(x(peak.t), padL + halfLabel + 6),
        width - padR - halfLabel - 6
      )
      var ly = Math.max(padT + 11, py - 9)
      if (width < 460) ly = Math.min(py - 6, padT + 16)
      root.appendChild(
        svgEl('text', {
          x: px, y: ly, fill: ink,
          'text-anchor': 'middle', 'font-size': 11, 'font-weight': 500,
        })
      ).textContent = label
    }

    // ── x 轴：整点刻度，不画短竖线 ──
    var spanH = (vMax - vMin) / HOUR
    var wideLabel = spanH > 18
    var stepH = niceStep(spanH, plotW, wideLabel)
    var tickMs = stepH * HOUR
    var tickAt = Math.ceil(vMin / tickMs) * tickMs
    var ticks = []
    for (var n = 0; tickAt <= vMax && n < 12; n++, tickAt += tickMs) {
      ticks.push(tickAt)
    }
    if (!ticks.length) ticks = [vMin, vMax]
    ticks.forEach(function (t, i) {
      if (!axis) return
      var tx = x(t)
      var text = wideLabel ? fmtTime(new Date(t).toISOString()) : fmtTime(new Date(t).toISOString()).slice(6)
      // 首尾标签只在真的会超出画布时才改变对齐，避免与相邻刻度挤在一起
      var half = text.length * 3.35
      var anchor = 'middle'
      if (i === 0 && tx - half < 2) anchor = 'start'
      if (i === ticks.length - 1 && tx + half > width - 2) anchor = 'end'
      root.appendChild(
        svgEl('text', {
          x: tx, y: height - 4, fill: ink3, 'text-anchor': anchor,
        })
      ).textContent = text
    })

    // ── 悬停：十字线 + 最近点 + 提示 ──
    var cross = svgEl('g', { opacity: 0, 'pointer-events': 'none' })
    var crossLine = svgEl('line', {
      y1: padT, y2: plotBottom, stroke: ink3, 'stroke-width': 1,
      'stroke-dasharray': '3 3', 'stroke-opacity': 0.7,
    })
    var crossDot = svgEl('circle', {
      r: 3, fill: chartHue, stroke: panel, 'stroke-width': 1.5,
    })
    cross.appendChild(crossLine)
    cross.appendChild(crossDot)
    root.appendChild(cross)

    var hit = svgEl('rect', {
      x: padL, y: padT, width: plotW, height: plotH,
      fill: 'transparent',
    })
    root.appendChild(hit)

    function hide() {
      cross.setAttribute('opacity', '0')
      if (tip) tip.setAttribute('data-on', '0')
    }

    function onMove(ev) {
      var box = root.getBoundingClientRect()
      var scale = width / box.width
      var px = (ev.clientX - box.left) * scale
      var t = vMin + ((px - padL) / plotW) * (vMax - vMin)
      var best = view[0]
      for (var i = 1; i < view.length; i++) {
        if (Math.abs(view[i].t - t) < Math.abs(best.t - t)) best = view[i]
      }
      var bx = x(best.t)
      cross.setAttribute('opacity', '1')
      crossLine.setAttribute('x1', bx)
      crossLine.setAttribute('x2', bx)
      crossDot.setAttribute('cx', bx)
      crossDot.setAttribute('cy', y(best.s))

      if (!tip) {
        tip = document.createElement('div')
        tip.className = 'chart__tip'
        tip.setAttribute('aria-hidden', 'true')
        container.appendChild(tip)
      }
      tip.innerHTML =
        '<p><span>' + fmtTime(trail.timestamps[best.i]) + ' UTC</span><span class="v">' + best.s.toFixed(2) + 'σ</span></p>' +
        '<p><span>原始值</span><span class="v">' + best.v.toFixed(3) + '</span></p>'
      tip.setAttribute('data-on', '1')
      var left = Math.min(Math.max(bx, 76), width - 76)
      tip.style.left = left + 'px'
    }

    hit.addEventListener('pointermove', onMove)
    hit.addEventListener('pointerleave', hide)
  }

  /* ============================================================
     序列曲线：原始信号 + 真值异常标记
     用于「检测记录」「标注」两页 —— 画的是信号本身，不是分数。
     ============================================================ */
  function seriesChart(container, d) {
    if (!container || !d || !d.timestamps) return

    var width = container.clientWidth
    var height = container.clientHeight
    if (!width || !height) return

    var n = d.timestamps.length
    var t0 = parseTs(d.timestamps[0])
    var t1 = parseTs(d.timestamps[n - 1])
    var vMin = Math.min.apply(null, d.values)
    var vMax = Math.max.apply(null, d.values)
    var span = (vMax - vMin) || 1
    vMin -= span * 0.08
    vMax += span * 0.08

    var padL = width < 420 ? 30 : 38
    var padR = 10
    var padT = 14
    var padB = 22
    var plotW = Math.max(20, width - padL - padR)
    var plotH = Math.max(24, height - padT - padB)

    function x(t) {
      return padL + ((t - t0) / (t1 - t0 || 1)) * plotW
    }
    function y(v) {
      return padT + (1 - (v - vMin) / (vMax - vMin)) * plotH
    }

    var old = container.querySelector('svg')
    if (old) old.remove()
    var tip = container.querySelector('.chart__tip')
    if (tip) tip.setAttribute('data-on', '0')

    var ink3 = css('--ink-3', '#7f7f8b')
    var grid = css('--grid', 'rgba(255,255,255,.07)')
    var line = css('--line', '#26262b')
    var chartHue = css('--chart', '#6da8e3')
    var chartFill = css('--chart-fill', 'rgba(109,168,227,.09)')
    var p0c = css('--p0', '#ef4444')
    var ink = css('--ink', '#fafafa')
    var panel = css('--panel', '#111113')

    var root = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: width,
      height: height,
      role: 'img',
      'aria-label':
        d.series_id + ' 原始信号：' + n + ' 个点，' +
        (d.labels || []).filter(function (v) { return v === 1 }).length + ' 个真值异常点',
    })
    container.appendChild(root)

    // 网格 + y 轴刻度
    for (var g = 0; g <= 3; g++) {
      var gv = vMin + ((vMax - vMin) * g) / 3
      var gy = y(gv)
      root.appendChild(
        svgEl('line', { x1: padL, x2: width - padR, y1: gy, y2: gy, stroke: grid, 'stroke-width': 1 })
      )
      if (g > 0 && g < 3) {
        root.appendChild(
          svgEl('text', {
            x: padL - 7, y: gy, fill: ink3, 'text-anchor': 'end', 'dominant-baseline': 'middle',
          })
        ).textContent = gv.toFixed(1)
      }
    }
    root.appendChild(
      svgEl('line', { x1: padL, x2: width - padR, y1: plotH + padT, y2: plotH + padT, stroke: line, 'stroke-width': 1 })
    )

    // 信号
    var path = d.timestamps.map(function (ts, i) {
      return (i ? 'L' : 'M') + x(parseTs(ts)).toFixed(2) + ' ' + y(d.values[i]).toFixed(2)
    }).join(' ')
    root.appendChild(
      svgEl('path', {
        d: path + ' L' + (padL + plotW).toFixed(2) + ' ' + (padT + plotH) +
          ' L' + padL + ' ' + (padT + plotH) + ' Z',
        fill: chartFill,
      })
    )
    root.appendChild(
      svgEl('path', {
        d: path, fill: 'none', stroke: chartHue, 'stroke-width': 1.5,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      })
    )

    // 真值异常：贴在底边的一排红条
    var marks = 0
    for (var i = 0; i < n; i++) {
      if (!d.labels || d.labels[i] !== 1) continue
      marks += 1
      var mx = x(parseTs(d.timestamps[i]))
      root.appendChild(
        svgEl('rect', {
          x: mx - 1, y: padT + plotH - 9, width: 2, height: 9, fill: p0c,
        })
      )
    }

    // x 轴：每 6 小时一个刻度
    var spanH = (t1 - t0) / HOUR
    var stepH = niceStep(spanH, plotW, spanH > 18)
    var tickMs = stepH * HOUR
    var tickAt = Math.ceil(t0 / tickMs) * tickMs
    for (var tk = tickAt; tk <= t1; tk += tickMs) {
      var tx = x(tk)
      var text = spanH > 18 ? fmtTime(new Date(tk).toISOString()) : fmtTime(new Date(tk).toISOString()).slice(6)
      root.appendChild(
        svgEl('text', { x: tx, y: height - 4, fill: ink3, 'text-anchor': 'middle' })
      ).textContent = text
    }

    // 悬停
    var cross = svgEl('g', { opacity: 0, 'pointer-events': 'none' })
    var crossLine = svgEl('line', { y1: padT, y2: padT + plotH, stroke: ink3, 'stroke-width': 1, 'stroke-dasharray': '3 3' })
    var crossDot = svgEl('circle', { r: 3, fill: chartHue, stroke: panel, 'stroke-width': 1.5 })
    cross.appendChild(crossLine)
    cross.appendChild(crossDot)
    root.appendChild(cross)

    var hit = svgEl('rect', { x: padL, y: padT, width: plotW, height: plotH, fill: 'transparent' })
    root.appendChild(hit)

    function hide() {
      cross.setAttribute('opacity', '0')
      if (tip) tip.setAttribute('data-on', '0')
    }

    hit.addEventListener('pointermove', function (ev) {
      var box = root.getBoundingClientRect()
      var scale = width / box.width
      var px = (ev.clientX - box.left) * scale
      var t = t0 + ((px - padL) / plotW) * (t1 - t0)
      var best = 0
      for (var k = 1; k < n; k++) {
        if (Math.abs(parseTs(d.timestamps[k]) - t) < Math.abs(parseTs(d.timestamps[best]) - t)) best = k
      }
      var bx = x(parseTs(d.timestamps[best]))
      cross.setAttribute('opacity', '1')
      crossLine.setAttribute('x1', bx)
      crossLine.setAttribute('x2', bx)
      crossDot.setAttribute('cx', bx)
      crossDot.setAttribute('cy', y(d.values[best]))
      if (!tip) {
        tip = document.createElement('div')
        tip.className = 'chart__tip'
        tip.setAttribute('aria-hidden', 'true')
        container.appendChild(tip)
      }
      tip.innerHTML =
        '<p><span>' + fmtTime(d.timestamps[best]) + '</span><span class="v">' +
        d.values[best].toFixed(3) + '</span></p>' +
        '<p><span>真值</span><span class="v">' +
        (d.labels && d.labels[best] === 1 ? '异常点' : '正常') + '</span></p>'
      tip.setAttribute('data-on', '1')
      tip.style.left = Math.min(Math.max(bx, 76), width - 76) + 'px'
    })
    hit.addEventListener('pointerleave', hide)

    // 刷选用的取点工具：把屏幕坐标换成点索引
    container.__pick = function (clientX) {
      var box = root.getBoundingClientRect()
      var scale = width / box.width
      var px = (clientX - box.left) * scale
      var t = t0 + ((px - padL) / plotW) * (t1 - t0)
      var best = 0
      for (var k = 1; k < n; k++) {
        if (Math.abs(parseTs(d.timestamps[k]) - t) < Math.abs(parseTs(d.timestamps[best]) - t)) best = k
      }
      return best
    }
    // 索引 → 画布横坐标（刷选高亮用）
    container.__geom = function (index) {
      return x(parseTs(d.timestamps[index]))
    }
  }

  window.SampleChart = {
    render: render,
    seriesChart: seriesChart,
    fmtTime: fmtTime,
    relTime: relTime,
  }
})()
