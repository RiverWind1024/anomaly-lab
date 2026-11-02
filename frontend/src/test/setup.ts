import '@testing-library/jest-dom/vitest'

/**
 * jsdom 不实现 `Element.scrollIntoView`。
 *
 * 检测记录页要「把左栏滚动到选中的那条」—— 不 mock 就抛
 * `TypeError: active?.scrollIntoView is not a function`，
 * 而 React 会把它当成渲染错误，把整棵树拆掉。
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    /* jsdom 没有布局，滚动无意义 —— 空实现即可 */
  }
}

/**
 * jsdom 不实现 `window.matchMedia`。
 *
 * AntD 的响应式组件（Descriptions 的 column={{ xs, sm, lg }}、
 * Grid 的 Col/Row 等）会用它来探测断点 —— 不 mock 就直接抛
 * `window.matchMedia is not a function`。
 *
 * 这里给一个最小的可用实现：永远不匹配，但能监听变化。
 */
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

/**
 * jsdom 的 `getComputedStyle(elt, pseudoElt)` 不支持伪元素参数，
 * 会往虚拟控制台刷 `Not implemented` 噪音。
 *
 * rc-table 测滚动条宽度时正好会这么调 —— 丢掉伪元素参数即可。
 */
const originalGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = ((elt: Element, _pseudoElt?: string | null) =>
  originalGetComputedStyle(elt)) as typeof window.getComputedStyle
