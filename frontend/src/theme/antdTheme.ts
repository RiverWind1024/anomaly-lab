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
      // ⚠️ **不要**把 AntD 的 fontSize 设成 13 ——
      //    AntD 的字号刻度是从它派生的（`fontSizeSM = fontSize - 3`），
      //    设成 13 会让「小号」那一档掉到 10px（Tag、small 按钮全变 10px）。
      //    正文 13px 由 ui.css 的组件覆写负责。
      controlHeight: 32,
      lineHeight: 1.5,
    },
    components: {
      Layout: {
        siderBg: readToken('--surface-canvas', '#09090b'),
        headerBg: readToken('--surface-canvas', '#09090b'),
        bodyBg: readToken('--surface-canvas', '#09090b'),
      },
      Menu: {
        // AntD 的 Menu 有 dark/light 两套内置调色板，都跟我们的 token 不一样。
        // 这里把两套都按 token 覆盖 —— 侧栏在两个主题下都用外框色。
        itemBg: readToken('--surface-canvas', '#09090b'),
        subMenuItemBg: readToken('--surface-canvas', '#09090b'),
        // 选中态：**不铺色**，靠文字变亮 + 左侧 1px accent 线标记（见 AppLayout.css）
        itemSelectedBg: 'transparent',
        itemSelectedColor: readToken('--text-primary', '#fafafa'),
        itemColor: readToken('--text-secondary', '#a1a1aa'),
        itemHoverBg: 'transparent',
        itemHoverColor: readToken('--text-primary', '#fafafa'),
        itemBorderRadius: 6,
        itemHeight: 34,
        itemMarginInline: 0,
        iconMarginInlineEnd: 10,
        iconSize: 16,
        collapsedIconSize: 16,
        // 暗色侧栏专用的 dark* 键（Menu theme="dark" 时生效）
        darkItemBg: 'transparent',
        darkSubMenuItemBg: 'transparent',
        darkItemSelectedBg: 'transparent',
        darkItemSelectedColor: readToken('--text-primary', '#fafafa'),
        darkItemColor: readToken('--text-secondary', '#a1a1aa'),
        darkItemHoverBg: 'transparent',
        darkItemHoverColor: readToken('--text-primary', '#fafafa'),
      },
      Table: {
        // ⚠️ 表头**不铺底色** —— 表头只有 12px 的灰字 + 一条线（app-screens §7.2）
        headerBg: 'transparent',
        headerColor: readToken('--text-secondary', '#a1a1aa'),
        headerSplitColor: 'transparent',
        borderColor: readToken('--border-subtle', '#26262b'),
        rowHoverBg: readToken('--surface-raised', '#1a1a1e'),
        cellPaddingBlock: 11,
        cellPaddingInline: 12,
        cellPaddingBlockSM: 9,
        cellPaddingInlineSM: 12,
        headerBorderRadius: 0,
      },
      Card: {
        colorBorderSecondary: readToken('--border-subtle', '#26262b'),
        borderRadiusLG: Number.parseFloat(readToken('--radius-md', '8px')) || 8,
        headerHeight: 46,
        headerFontSize: 15,
      },
      Tag: {
        // 状态标签统一走 .pill（见 ui.css），AntD 的 Tag 只留给中性用途
        defaultBg: 'transparent',
        defaultColor: readToken('--text-secondary', '#a1a1aa'),
        borderRadiusSM: 4,
      },
      Button: {
        borderRadius: 6,
        controlHeight: 32,
        fontSize: 13,
        defaultBg: readToken('--surface-panel', '#111113'),
        defaultBorderColor: readToken('--border-subtle', '#26262b'),
        defaultShadow: 'none',
        primaryShadow: 'none',
      },
      Select: {
        optionSelectedBg: readToken('--accent-subtle', 'rgba(12, 92, 171, 0.24)'),
      },
      Drawer: {
        colorBgElevated: readToken('--surface-panel', '#111113'),
      },
    },
  }
}
