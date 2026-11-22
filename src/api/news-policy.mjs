export const NEWS_ITEM_LIMIT = 10

export const ACTIVE_SOURCE_IDS = new Set([
  'ftchinese', 'bloomberg', 'marketwatch',
  'eastmoney', 'wallstreetcn', 'jin10',
  'cankaoxiaoxi', 'mktnews',
])

export function limitNewsItems(items) {
  return Array.isArray(items) ? items.slice(0, NEWS_ITEM_LIMIT) : []
}
