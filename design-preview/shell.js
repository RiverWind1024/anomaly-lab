/* ============================================================
   样张外壳：侧栏 / 手机顶栏 / 抽屉 / 主题
   所有页面共用一套导航，导航指向 5199 的静态页，
   侧栏底部保留「在真实应用中打开」回到 5173。
   window.SAMPLE.page = { key, scope: [[k, v], ...] }
   ============================================================ */
;(function () {
  var S = (window.SAMPLE = window.SAMPLE || {})

  var NAV = [
    { key: 'overview', label: '概览', href: 'index.html', app: '/' },
    { key: 'sources', label: '数据源', href: 'sources.html', app: '/sources' },
    { key: 'jobs', label: '检测任务', href: 'jobs.html', app: '/jobs' },
    { key: 'alerts', label: '告警中心', href: 'alerts.html', app: '/alerts' },
    { key: 'evaluation', label: '评估报告', href: 'evaluation.html', app: '/evaluation' },
    { key: 'detections', label: '检测记录', href: 'detections.html', app: '/detections' },
    { key: 'annotate', label: '标注', href: 'annotate.html', app: '/annotate' },
  ]

  var APP = 'http://127.0.0.1:5173'

  function el(tag, cls, html) {
    var n = document.createElement(tag)
    if (cls) n.className = cls
    if (html !== undefined) n.innerHTML = html
    return n
  }

  function navHtml(active) {
    return NAV.map(function (item) {
      var n = (S.counts && S.counts[item.key]) || item.count
      var count = n ? ' <span class="nav__count num">' + n + '</span>' : ''
      return (
        '<a class="nav__item' + (item.key === active ? ' is-active' : '') + '"' +
        ' href="' + item.href + '"' +
        (item.key === active ? ' aria-current="page"' : '') +
        '>' + item.label + count + '</a>'
      )
    }).join('')
  }

  function build() {
    var cfg = S.page || { key: 'overview' }
    var shell = document.querySelector('.shell')
    var main = shell.querySelector('main')
    if (!shell || !main) return

    // 侧栏：品牌 + 导航 + 主题。不放作用域 —— 数据源/指标是常量，
    // 常量不占首屏，每页的发现句已经说明这一屏在看什么。
    var rail = el('aside', 'rail')
    rail.setAttribute('aria-label', '主导航')
    rail.innerHTML =
      '<a class="brand" href="index.html" aria-label="anomaly lab 首页">' +
        '<svg class="brand__mark" viewBox="0 0 24 24" aria-hidden="true">' +
          '<path d="M2 17.5 6 17.5 8.6 9.5 11.4 14.5 14.2 6.5 17 12.5 22 12.5" fill="none" ' +
            'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />' +
          '<circle cx="17" cy="12.5" r="2.1" class="brand__spark" />' +
        '</svg>' +
        '<span class="brand__name">anomaly<span class="brand__dot">·</span>lab</span>' +
      '</a>' +
      '<nav class="nav" aria-label="页面">' + navHtml(cfg.key) + '</nav>' +
      '<div class="rail__foot">' +
        '<button class="theme" type="button" id="themeToggle" aria-pressed="true">' +
          '<span class="theme__dot" aria-hidden="true"></span><span id="themeLabel">暗色</span>' +
        '</button>' +
        '<a class="applink" href="' + APP + appPath(cfg.key) + '" target="_blank" rel="noreferrer">' +
          '在真实应用中打开' +
        '</a>' +
        '<p class="stamp num" id="railStamp"></p>' +
      '</div>'

    // 手机顶栏
    var topbar = el('header', 'topbar')
    topbar.innerHTML =
      '<button class="topbar__menu" type="button" id="menuOpen" aria-expanded="false" aria-controls="navsheet">' +
        '<svg viewBox="0 0 20 20" aria-hidden="true">' +
          '<path d="M3 5h14M3 10h14M3 15h14" fill="none" stroke="currentColor" ' +
            'stroke-width="1.5" stroke-linecap="round" />' +
        '</svg><span class="sr-only">打开导航</span>' +
      '</button>' +
      '<span class="topbar__brand">anomaly<span class="brand__dot">·</span>lab</span>' +
      '<span class="topbar__page">' + pageLabel(cfg.key) + '</span>'

    // 手机抽屉
    var sheet = el('div', 'navsheet')
    sheet.id = 'navsheet'
    sheet.hidden = true
    sheet.innerHTML =
      '<div class="navsheet__head">' +
        '<span class="navsheet__scope">' + pageLabel(cfg.key) + ' · 样张</span>' +
        '<button class="navsheet__close" type="button" id="menuClose">关闭</button>' +
      '</div>' +
      '<nav class="navsheet__nav" aria-label="页面">' + navHtml(cfg.key) + '</nav>' +
      '<div class="navsheet__foot">' +
        '<button class="theme" type="button" id="themeToggleSheet" aria-pressed="true">' +
          '<span class="theme__dot" aria-hidden="true"></span><span id="themeLabelSheet">暗色</span>' +
        '</button>' +
        '<a class="applink" href="' + APP + appPath(cfg.key) + '" target="_blank" rel="noreferrer">' +
          '在真实应用中打开' +
        '</a>' +
        '<p class="stamp num" id="railStampSheet"></p>' +
      '</div>'

    shell.insertBefore(rail, main)
    shell.insertBefore(topbar, main)
    shell.insertBefore(sheet, main)
  }

  function appPath(key) {
    var item = NAV.filter(function (n) { return n.key === key })[0]
    return item ? item.app : '/'
  }

  function pageLabel(key) {
    var item = NAV.filter(function (n) { return n.key === key })[0]
    return item ? item.label : ''
  }

  // ── 主题 ──
  function initTheme() {
    var root = document.documentElement
    var btn = document.getElementById('themeToggle')
    var btnSheet = document.getElementById('themeToggleSheet')
    var label = document.getElementById('themeLabel')
    var labelSheet = document.getElementById('themeLabelSheet')

    function sync() {
      var dark = root.getAttribute('data-theme') !== 'light'
      ;[btn, btnSheet].forEach(function (b) {
        if (b) b.setAttribute('aria-pressed', dark ? 'true' : 'false')
      })
      if (label) label.textContent = dark ? '暗色' : '浅色'
      if (labelSheet) labelSheet.textContent = dark ? '暗色' : '浅色'
      window.dispatchEvent(new CustomEvent('themechange', { detail: { dark: dark } }))
    }

    function toggle() {
      var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light'
      root.setAttribute('data-theme', next)
      try { localStorage.setItem('anomaly-lab-sample-theme', next) } catch (e) {}
      sync()
    }

    ;[btn, btnSheet].forEach(function (b) {
      if (b) b.addEventListener('click', toggle)
    })
    sync()
  }

  // ── 手机抽屉 ──
  function initMenu() {
    var sheet = document.getElementById('navsheet')
    var open = document.getElementById('menuOpen')
    var close = document.getElementById('menuClose')
    if (!sheet || !open) return

    function setMenu(show) {
      sheet.hidden = !show
      open.setAttribute('aria-expanded', show ? 'true' : 'false')
      document.body.classList.toggle('is-locked', show)
    }
    open.addEventListener('click', function () { setMenu(true) })
    if (close) close.addEventListener('click', function () { setMenu(false) })
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !sheet.hidden) setMenu(false)
    })
  }

  // 快照时间：各页脚本填
  function setStamp(text) {
    ;['railStamp', 'railStampSheet'].forEach(function (id) {
      var n = document.getElementById(id)
      if (n) n.textContent = text
    })
  }

  S.setStamp = setStamp
  S.NAV = NAV
  S.APP = APP

  build()
  initTheme()
  initMenu()
})()
