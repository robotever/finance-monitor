import type { MarketDashboardPayload, MarketDashboardV3Payload, MarketHistoryPayload, MarketHistoryV3Payload, MarketHistoryWindow, MarketLoadOptions, MarketLoadResult,
  SectorLatestOptions, SectorHistoryOptions, SectorDetailOptions, SectorRotationLatest, SectorRotationHistory, SectorRotationDetail } from './types'
export function loadMarketDashboard(fetcher: typeof fetch | undefined, options: MarketLoadOptions & { schemaVersion: 'market-dashboard-v3' }): Promise<MarketLoadResult<MarketDashboardV3Payload>>
export function loadMarketDashboard(fetcher?: typeof fetch, options?: MarketLoadOptions & { schemaVersion?: 'market-dashboard-v2' }): Promise<MarketLoadResult<MarketDashboardPayload>>
export function loadMarketDashboard(fetcher: typeof fetch | undefined, options: MarketLoadOptions): Promise<MarketLoadResult<MarketDashboardPayload | MarketDashboardV3Payload>>
export function loadMarketHistory(window: MarketHistoryWindow, fetcher: typeof fetch | undefined, options: MarketLoadOptions & { schemaVersion: 'market-dashboard-v3' }): Promise<MarketLoadResult<MarketHistoryV3Payload>>
export function loadMarketHistory(window: MarketHistoryWindow, fetcher?: typeof fetch, options?: MarketLoadOptions & { schemaVersion?: 'market-dashboard-v2' }): Promise<MarketLoadResult<MarketHistoryPayload>>
export function loadMarketHistory(window: MarketHistoryWindow, fetcher: typeof fetch | undefined, options: MarketLoadOptions): Promise<MarketLoadResult<MarketHistoryPayload | MarketHistoryV3Payload>>
export function loadSectorRotationLatest(options: SectorLatestOptions): Promise<MarketLoadResult<SectorRotationLatest>>
export function loadSectorRotationHistory(options: SectorHistoryOptions): Promise<MarketLoadResult<SectorRotationHistory>>
export function loadSectorRotationDetail(options: SectorDetailOptions): Promise<MarketLoadResult<SectorRotationDetail>>
