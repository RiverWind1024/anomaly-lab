import { theme as antdTheme, type ThemeConfig } from 'antd'
import type { ThemeMode } from './useThemeMode'

/**
 * AntD ConfigProvider 的 theme 配置。
 *
 * ⚠️ **AntD v5 不能直接吃 CSS 变量当色值** —— 它要对 colorPrimary 做颜色运算
 *    （派生 hover/active/border 等），`var(--accent)` 传进去会得到一堆错误的色值。
 *    所以必须**运行时从 CSS 变量读出实际色值**再传给 AntD。
 *
 * 读取时机：`data-theme` 已经写到 `<html>` 上之后（useThemeMode 的 effect 先跑）。
 */

/** 从 :root 读一个 CSS 变量的实际值。读不到时返回 fallback。 */
export function readToken(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw || fallback
}

export function buildAntdTheme(mode: ThemeMode): ThemeConfig {
  return {
    // 暗色主题走 AntD 自带的 darkAlgorithm —— 它会连带把容器底色、
    // 分隔线、表格斑马纹等一并调暗，不必逐个手写。
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: readToken('--accent', '#0c5cab'),
      colorSuccess: readToken('--status-normal', '#10b981'),
      colorWarning: readToken('--status-p1', '#f59e0b'),
      colorError: readToken('--status-p0', '#ef4444'),
      colorInfo: readToken('--status-info', '#3b82f6'),
      colorBgBase: readToken('--surface-canvas', '#09090b'),
      colorBgContainer: readToken('--surface-panel', '#111113'),
      colorBgElevated: readToken('--surface-raised', '#1a1a1e'),
      colorBorder: readToken('--border-subtle', '#26262b'),
      colorBorderSecondary: readToken('--border-subtle', '#26262b'),
      colorText: readToken('--text-primary', '#fafafa'),
      colorTextSecondary: readToken('--text-secondary', '#a1a1aa'),
      colorTextTertiary: readToken('--text-tertiary', '#7f7f8b'),
      fontFamily: readToken('--font-sans', 'system-ui, sans-serif'),
      fontFamilyCode: readToken('--font-mono', 'ui-monospace, monospace'),
      borderRadius: Number.parseFloat(readToken('--radius-md', '8px')) || 8,
      borderRadiusLG: Number.parseFloat(readToken('--radius-lg', '12px')) || 12,
    },
    components: {
      Layout: {
        siderBg: readToken('--surface-panel', '#111113'),
        headerBg: readToken('--surface-panel', '#111113'),
        bodyBg: readToken('--surface-canvas', '#09090b'),
      },
      Menu: {
        // AntD 的 Menu 有 dark/light 两套内置调色板，都跟我们的 token 不一样。
        // 这里把两套都按 token 覆盖 —— 侧栏在两个主题下都用同一套表面色。
        itemBg: readToken('--surface-panel', '#111113'),
        subMenuItemBg: readToken('--surface-panel', '#111113'),
        itemSelectedBg: readToken('--accent-subtle', 'rgba(12, 92, 171, 0.24)'),
        itemSelectedColor: readToken('--text-primary', '#fafafa'),
        itemColor: readToken('--text-secondary', '#a1a1aa'),
        itemHoverBg: readToken('--surface-raised', '#1a1a1e'),
        itemHoverColor: readToken('--text-primary', '#fafafa'),
        itemBorderRadius: Number.parseFloat(readToken('--radius-md', '8px')) || 8,
        // 暗色侧栏专用的 dark* 键（Menu theme="dark" 时生效）
        darkItemBg: 'transparent',
        darkSubMenuItemBg: 'transparent',
        darkItemSelectedBg: readToken('--accent-subtle', 'rgba(12, 92, 171, 0.24)'),
        darkItemSelectedColor: readToken('--text-primary', '#fafafa'),
        darkItemColor: readToken('--text-secondary', '#a1a1aa'),
        darkItemHoverBg: readToken('--surface-raised', '#1a1a1e'),
        darkItemHoverColor: readToken('--text-primary', '#fafafa'),
      },
      Table: {
        headerBg: readToken('--surface-raised', '#1a1a1e'),
        headerColor: readToken('--text-secondary', '#a1a1aa'),
        rowHoverBg: readToken('--surface-raised', '#1a1a1e'),
        borderColor: readToken('--border-subtle', '#26262b'),
      },
    },
  }
}
