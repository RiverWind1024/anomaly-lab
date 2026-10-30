import '@testing-library/jest-dom/vitest'

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
