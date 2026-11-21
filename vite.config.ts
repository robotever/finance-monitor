import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

function proxy(target: string, referer?: string) {
  return {
    target,
    changeOrigin: true as const,
    configure: (p: any) => {
      p.on('proxyReq', (req: any) => {
        req.setHeader('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        req.setHeader('Accept', 'application/rss+xml, application/xml, application/json, text/xml, */*')
        if (referer) req.setHeader('Referer', referer)
      })
    },
  }
}

const rw = (prefix: string) => ({ rewrite: (p: string) => p.replace(new RegExp(`^${prefix}`), '') })

export default defineConfig(({ mode }) => ({
  plugins: [vue(), {
    name: 'sector-acceptance-metadata',
    transformIndexHtml(html) {
      const env = loadEnv(mode, process.cwd(), 'VITE_')
      if (mode !== 'sector-acceptance' || env.VITE_SECTOR_ROTATION_ACCEPTANCE !== 'true') return html
      return html.replace('<title>Finance Monitor · 全市场研究终端</title>', '<title>板块轮动临时验收 · 测试数据</title>')
        .replace('<!-- build metadata -->', '<meta name="description" content="临时验收环境，全部为合成测试数据，不代表真实市场信号。" />\n    <meta name="robots" content="noindex,nofollow" />')
    },
  }],
  resolve: { alias: { '@': resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      '/proxy-ftchinese': { ...proxy('http://www.ftchinese.com'),                            ...rw('/proxy-ftchinese') },
      '/proxy-investing': { ...proxy('https://cn.investing.com'),                            ...rw('/proxy-investing') },
      '/proxy-bloomberg': { ...proxy('https://feeds.bloomberg.com'),                          ...rw('/proxy-bloomberg') },
      '/proxy-marketwatch':{ ...proxy('https://feeds.marketwatch.com'),                      ...rw('/proxy-marketwatch') },
      '/proxy-sinafinance':  { ...proxy('https://feed.mix.sina.com.cn', 'https://finance.sina.com.cn'), ...rw('/proxy-sinafinance') },
      '/proxy-eastmoney':    { ...proxy('https://newsapi.eastmoney.com', 'https://finance.eastmoney.com'), ...rw('/proxy-eastmoney') },
      '/proxy-wallstreetcn': { ...proxy('https://api-one.wallstcn.com', 'https://wallstreetcn.com'), ...rw('/proxy-wallstreetcn') },
      '/proxy-jin10':        { ...proxy('https://www.jin10.com', 'https://www.jin10.com'),           ...rw('/proxy-jin10') },
      '/proxy-cankaoxiaoxi': { ...proxy('https://china.cankaoxiaoxi.com'),                           ...rw('/proxy-cankaoxiaoxi') },
      '/proxy-mktnews':      { ...proxy('https://api.mktnews.net', 'https://mktnews.net'),           ...rw('/proxy-mktnews') },
      '/proxy-gelonghui':    { ...proxy('https://www.gelonghui.com', 'https://www.gelonghui.com'),   ...rw('/proxy-gelonghui') },
      '/proxy-fred':         { ...proxy('https://fred.stlouisfed.org', 'https://fred.stlouisfed.org'), ...rw('/proxy-fred') },
    },
  },
}))
