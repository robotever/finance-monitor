import type { MarketConceptView, MarketDashboardPayload, MarketDashboardView, MarketFrequency, MarketIndustryRankings, MarketScoreObject, MarketViewOptions } from './types'
export const DEFAULT_STALE_AFTER_MS: Readonly<Record<MarketFrequency, number>>
export function deriveMarketDashboardView(payload: MarketDashboardPayload, now?: Date, options?: MarketViewOptions): MarketDashboardView
export function rankIndustries<T extends MarketScoreObject>(industries: readonly T[]): MarketIndustryRankings<T>
export function rankConcepts<T extends MarketConceptView>(concepts: readonly T[]): MarketIndustryRankings<T>
import type { SectorRotationLatest, SectorLatestResponses, SectorRotationHistory, SectorRotationViewOptions, SectorRotationView } from './types'
export function deriveSectorRotationView(latest: SectorRotationLatest | SectorLatestResponses, history?: SectorRotationHistory | null, options?: SectorRotationViewOptions): SectorRotationView
