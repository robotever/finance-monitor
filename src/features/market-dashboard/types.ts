export type MarketScoreAxis = 'strength' | 'heat' | 'risk'
export type MarketFrequency = 'intraday' | 'daily' | 'monthly'
export type MarketStage = '冰点' | '修复' | '震荡' | '扩张' | '过热' | '退潮'
export type MarketHistoryWindow = '1d' | '5d' | '20d' | '90d'
export type MarketComparisonKey = 'change1d' | 'change5d'
export type MarketComparisonUnavailable = 'missingObservation' | 'missingCurrentScores' | 'missingTradingCalendar' | 'missingTargetTradingDate'
export interface LegacyMarketScores { strength: number | null; heat: number | null; risk: number | null }
export type MarketScores = LegacyMarketScores
export interface MarketScoreSummary extends LegacyMarketScores { id: string; completeness: number }
export interface MarketScoreObject extends MarketScoreSummary {
  name?: string
  frequency?: MarketFrequency
  observedAt?: string
  stage?: MarketStage | null
  missing: string[]
  contributors: { label: string; impact: number; evidence?: string }[]
  sourceTimestamps: { source: 'Wind' | 'FRED' | 'MX' | 'Derived'; timestamp: string }[]
  change1d: MarketScores | null
  change5d: MarketScores | null
  comparisonFallback?: 'close'
  comparisonUnavailable?: Partial<Record<MarketComparisonKey, MarketComparisonUnavailable>>
}
export interface MarketDynamicConcept extends MarketScoreObject {
  selectionScore: number
  selectedOn: string
  retainedTradingDays: number
}
export interface MarketConceptsPayload {
  selectionVersion: 'concept-selection-v0.1'
  scoringVersion: 'concept-score-v0.1'
  selectedAt: string
  core: MarketScoreObject[]
  dynamic: MarketDynamicConcept[]
}
export interface MarketSourceMode {
  breadth: 'wind'; styles: 'wind'; industries: 'wind'; concepts: 'wind'; conceptDiscovery: 'mx'
  global: Record<string, 'fred' | 'wind' | 'mx'>
}
export interface MarketDataStatus { completeness: number; stale: boolean; missing: string[] }
export interface MarketObservation {
  observedAt: string
  marketDate: string
  session: 'intraday' | 'close'
  scoringVersion: 'market-score-v0.1'
}
/** Runtime loader enforces 43 market/industry objects plus 25 core and 10 dynamic concepts. */
export interface MarketDashboardPayload extends MarketObservation {
  schemaVersion: 'market-dashboard-v2'
  global: MarketScoreObject
  aShare: MarketScoreObject
  styles: MarketScoreObject[]
  industries: MarketScoreObject[]
  concepts: MarketConceptsPayload
  dataStatus: MarketDataStatus
  sourceMode?: MarketSourceMode
}
export interface MarketHistorySnapshot extends MarketObservation {
  global: MarketScoreSummary
  aShare: MarketScoreSummary
  styles: MarketScoreSummary[]
  industries: MarketScoreSummary[]
  concepts: { selectionVersion: 'concept-selection-v0.1'; scoringVersion: 'concept-score-v0.1';
    selectedAt: string; core: MarketScoreSummary[]; dynamic: MarketScoreSummary[] }
}
export interface MarketHistoryPayload { window: MarketHistoryWindow; snapshots: MarketHistorySnapshot[] }
export type MarketLoadErrorCode = 'NO_SNAPSHOT' | 'HTTP_ERROR' | 'INVALID_JSON' | 'INVALID_SCHEMA' | 'TIMEOUT' | 'ABORTED' | 'NETWORK_ERROR' | 'INVALID_WINDOW' | 'INVALID_QUERY'
export interface MarketLoadError { code: MarketLoadErrorCode; message: string; status?: number }
export type MarketLoadResult<T> = { data: T; error: null } | { data: null; error: MarketLoadError }
export interface MarketLoadOptions { timeoutMs?: number; signal?: AbortSignal; schemaVersion?: 'market-dashboard-v2' | 'market-dashboard-v3' }
export interface MarketViewOptions {
  /** Intraday: 30 minutes; daily: conservative 20 days; monthly: 75 days. */
  staleAfterMs?: Partial<Record<MarketFrequency, number>>
  /** Exact Asia/Shanghai exchange dates; omitted means weekday approximation. */
  tradingDates?: readonly string[]
}
export interface MarketFreshness { stale: boolean; ageMs: number; missingClose: boolean; label: string; oldestSourceAt?: string | null }
export interface MarketImprovement {
  improvementValue: number | null
  improvementWindow: '1d' | '5d' | null
  improvementLabel: string
}
export interface MarketScoreView extends MarketScoreObject, MarketImprovement {
  stage: MarketStage | null
  stageLabel: string
  scoreLabels: Record<MarketScoreAxis, string>
  evidenceInsufficient: boolean
  evidenceLabel: string
  freshness: MarketFreshness
  comparisonBadges: Record<MarketComparisonKey, string>
}
export interface MarketConceptView extends MarketScoreView {
  selectionScore?: number
  selectedOn?: string
  retainedTradingDays?: number
}
export interface MarketIndustryRankings<T extends MarketScoreObject = MarketScoreView> {
  strength: (T & MarketImprovement)[]
  heat: (T & MarketImprovement)[]
  risk: (T & MarketImprovement)[]
  improvement: (T & MarketImprovement)[]
}
export interface MarketDashboardView extends Omit<MarketDashboardPayload, 'global' | 'aShare' | 'styles' | 'industries' | 'concepts'> {
  global: MarketScoreView
  aShare: MarketScoreView
  styles: MarketScoreView[]
  industries: MarketScoreView[]
  concepts: MarketConceptsPayload
  coreConcepts: MarketConceptView[]
  dynamicConcepts: MarketConceptView[]
  conceptRankings: { core: MarketIndustryRankings<MarketConceptView>; dynamic: MarketIndustryRankings<MarketConceptView> }
  freshness: MarketFreshness
  rankings: MarketIndustryRankings
}

export type SectorUniverse = 'industry' | 'concept'
export type SectorAxis = 'strength' | 'opportunity' | 'risk'
export type SectorLeaderboardAxis = 'strength' | 'opportunity'
export type SectorView = 'potential' | 'main' | 'risk'
export type SectorHeatState = 'cold' | 'neutral' | 'warming' | 'active' | 'crowded'
export interface SectorScores { strength: number | null; opportunity: number | null; risk: number | null }
export interface SectorVersions { scoringVersion: 'sector-score-v0.2'; universeVersion: 'sector-universe-v0.1' }
export interface SectorLeaderboard {
  axis: SectorLeaderboardAxis
  topTenStreak: number
  topTenCount15d: number
  rankChange: number | null
}
export interface SectorSummary extends SectorScores {
  id: string
  heatState: SectorHeatState | null
  completeness: number
  ranks: Record<SectorAxis, number | null>
}
export interface SectorRotationRow extends SectorSummary {
  name: string
  coldStart: boolean
  leaderboard: Record<SectorLeaderboardAxis, SectorLeaderboard>
}
export interface SectorRotationLatest extends SectorVersions {
  observedAt: string
  marketDate: string
  session: 'intraday' | 'close'
  universe: SectorUniverse
  view: SectorView
  sectors: (SectorRotationRow & { change1d: SectorScores })[]
}
export interface SectorHistoryPoint { marketDate: string; score: number | null; rank: number | null }
export interface SectorRotationHistory extends SectorVersions {
  universe: SectorUniverse
  axis: SectorLeaderboardAxis
  days: number
  dates: string[]
  rows: { id: string; name: string; values: SectorHistoryPoint[] }[]
}
export interface SectorComponent {
  value: number | null
  coverage: number
  missing: string[]
  usedWeight?: number | null
  totalWeight?: number | null
  effectiveWeight?: number | null
  percentile?: number | null
  parts?: Record<string, SectorComponent>
}
export interface SectorContributor { axis: SectorAxis; component: string; value: number; weight: number; impact: number }
export interface SectorProvenance {
  source: 'Wind'
  observedAt: string
  marketDate: string
  session: 'intraday' | 'close'
  officialClose: boolean
  sectorScoringVersion: 'sector-score-v0.2'
  sectorUniverseVersion: 'sector-universe-v0.1'
}
export interface SectorDetailRow extends SectorRotationRow, SectorVersions {
  observedAt: string
  marketDate: string
  session: 'intraday' | 'close'
  officialClose: boolean
  components: Record<string, SectorComponent>
  missing: string[]
  contributors: SectorContributor[]
  provenance: SectorProvenance
}
export interface SectorRotationDetail extends SectorVersions {
  universe: SectorUniverse
  id: string
  days: number
  history: SectorDetailRow[]
}
export interface SectorRequestOptions extends MarketLoadOptions { universe: SectorUniverse; fetcher?: typeof fetch }
export interface SectorLatestOptions extends SectorRequestOptions { view: SectorView }
export interface SectorHistoryOptions extends SectorRequestOptions { axis: SectorLeaderboardAxis; days?: number }
export interface SectorDetailOptions extends SectorRequestOptions { id: string; days?: number }
export interface SectorProjectedRow extends SectorRotationRow {
  universe: SectorUniverse
  observedAt: string
  axisCompleteness: Record<SectorAxis, number>
  validCloses: number
  improvementEvidence: number
  officialClose: boolean
}
export interface SectorEncodedRow extends SectorProjectedRow { components: Record<string, number>; missing: number[] }
export interface SectorRotationBlock {
  sectorScoringVersion: 'sector-score-v0.2'
  sectorUniverseVersion: 'sector-universe-v0.1'
  observedAt: string
  marketDate: string
  session: 'intraday' | 'close'
  officialClose: boolean
  industries: SectorEncodedRow[]
  concepts: SectorEncodedRow[]
  componentEncoding: 'node-mask-v1'
  componentFields: string[]
  componentPartNames: string[]
  /** Lossless node masks and numeric/missing/part references; decoded by the strict loader validator. */
  componentNodes: (number | null | number[] | [number, number][])[][]
  missingReasons: string[]
  auditDefinitions: {
    weights: Record<SectorAxis, Record<string, number>>
    componentWeights: Record<string, Record<string, number>>
    gates: Record<string, number>
    heat: Record<string, number>
  }
  releaseEligible: boolean
  safeCodes: string[]
}
export interface MarketDashboardV3Payload extends Omit<MarketDashboardPayload, 'schemaVersion' | 'industries' | 'concepts'> {
  schemaVersion: 'market-dashboard-v3'
  sectorScoringVersion: 'sector-score-v0.2'
  sectorUniverseVersion: 'sector-universe-v0.1'
  industries: SectorProjectedRow[]
  concepts: {
    selectionVersion: 'concept-selection-v0.1'
    scoringVersion: 'sector-score-v0.2'
    selectionScoringVersion: 'concept-score-v0.1'
    selectedAt: string
    core: SectorProjectedRow[]
    dynamic: (SectorProjectedRow & { selectionScore: number; selectedOn: string; retainedTradingDays: number })[]
  }
  sectorRotation: SectorRotationBlock
}
export interface MarketHistoryV3Snapshot extends Omit<MarketHistorySnapshot, 'industries' | 'concepts'> {
  schemaVersion: 'market-dashboard-v3'
  sectorScoringVersion: 'sector-score-v0.2'
  sectorUniverseVersion: 'sector-universe-v0.1'
  industries: SectorSummary[]
  concepts: {
    selectionVersion: 'concept-selection-v0.1'
    scoringVersion: 'sector-score-v0.2'
    selectionScoringVersion: 'concept-score-v0.1'
    selectedAt: string
    core: SectorSummary[]
    dynamic: SectorSummary[]
  }
}
export interface MarketHistoryV3Payload { window: MarketHistoryWindow; snapshots: MarketHistoryV3Snapshot[] }
export interface SectorRowView extends SectorRotationRow {
  change1d?: SectorScores
  heatStateLabel: string
  scoreLabels: Record<SectorAxis, string>
  coldStartLabel: string | null
  evidenceInsufficient: boolean
  evidenceLabel: string
  leaderboardLabels: Record<SectorLeaderboardAxis, string>
}
export interface SectorMatrixCell extends SectorHistoryPoint {
  id: string
  name: string
  /** Compact history does not supply returns or score deltas. */
  dailyReturn: null
  change1d: null
}
export interface SectorMatrixView {
  axis: SectorLeaderboardAxis | null
  axisLabel: string
  dates: string[]
  insufficientHistory: boolean
  historyLabel: string
  rows: { rank: number; cells: (SectorMatrixCell | null)[] }[]
}
export interface SectorDetailView extends SectorVersions {
  id: string
  universe: SectorUniverse
  axisLabels: Record<SectorAxis, string>
  series: (Pick<SectorDetailRow, 'observedAt' | 'marketDate' | 'session' | 'officialClose' | 'strength' | 'opportunity' | 'risk' | 'heatState' | 'ranks'> & { heatStateLabel: string })[]
  audit: Pick<SectorDetailRow, 'components' | 'missing' | 'contributors' | 'provenance' | 'scoringVersion' | 'universeVersion'> | null
}
export type SectorLatestResponses = Partial<Record<SectorView, SectorRotationLatest>>
export interface SectorRotationViewOptions extends MarketViewOptions { now?: Date; stale?: boolean; topN?: number; detail?: SectorRotationDetail | null }
export interface SectorRotationView extends SectorVersions {
  /** Only these lists have complete server coverage and authoritative unrounded order. */
  completeViews: SectorView[]
  potential: SectorRowView[]
  main: SectorRowView[]
  risk: SectorRowView[]
  rows: SectorRowView[]
  universe: SectorUniverse
  observedAt: string
  marketDate: string
  viewLabels: Record<SectorView, string>
  sessionLabel: string
  freshness: MarketFreshness
  matrix: SectorMatrixView
  detail: SectorDetailView | null
}
