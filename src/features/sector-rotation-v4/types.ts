export type Universe = 'industry' | 'concept'
export type Axis = 'strength' | 'opportunity' | 'risk'
export type View = 'potential' | 'main' | 'risk'
export interface Component { value: number | null; coverage: number; missing: string[]; parts?: Record<string, Component> }
export interface SectorRow { id: string; name: string; universe: Universe; strength: number | null; opportunity: number | null; risk: number | null; completeness: number; ranks: Record<Axis,number|null>; change1d: Record<Axis,number|null>; heatState: string | null; coldStart: boolean; validCloses: number; improvementEvidence: number; membershipMode: 'current_members_backfill' | 'point_in_time_snapshot'; conceptRole: 'core'|'dynamic'|'candidate'|null; missing: string[]; approximateHistory: boolean; metrics?: Record<string,number|boolean|null>; components?: Record<string,Component> }
export interface Metadata { schemaVersion: 'market-dashboard-v4'; sectorScoringVersion: 'sector-score-v0.3'; sectorUniverseVersion: 'sector-universe-ths-v1'; featureVersion: 'sector-features-ths-v1'; membershipVersion: 'sector-membership-ths-v1'; sourceMode: 'hithink'; batchId: string; observedAt: string; marketDate: string; session: 'close'|'intraday'; officialClose: boolean; membershipModes: string[]; approximateHistory: boolean }
export interface Latest extends Metadata { industry: Record<View,SectorRow[]>; concept: Record<View,SectorRow[]> & {core: SectorRow[];dynamic: SectorRow[]} }
export interface Catalog extends Metadata { universe: Universe; page: number; pageSize: number; q: string; view: View|'all'; role: string; total: number; sectors: SectorRow[] }
export interface HistoryPoint { marketDate: string; score: number|null; rank: number|null }
export interface History extends Metadata { universe: Universe; axis: Axis; days: number; dates: string[]; liveDate?: string|null; rows: {id:string;name:string;values:HistoryPoint[]}[] }
export interface Detail extends Metadata { universe: Universe; id: string; days: number; history: (SectorRow & Pick<Metadata,'observedAt'|'marketDate'|'session'|'officialClose'>)[] }
export interface LoadError { code: string; message: string }
export interface Result<T> { data: T|null; error: LoadError|null }
export interface Options { signal?: AbortSignal; timeoutMs?: number; fetcher?: typeof fetch }
export interface CatalogOptions extends Options {universe: Universe;page?:number;pageSize?:number;q?:string;view?:View|'all';role?:string}
