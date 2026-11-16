import type { Latest,History,HistoryPoint,View } from './types'
export const VIEWS: {key:View;label:string}[]
export function validateLatest(p:unknown):Latest
export function selectSectorAdapter(enabled:boolean,p:unknown):'v3'|'v4'
export function deriveBoard(p:Latest,now?:Date):Latest & {sourceLabel:string;stale:boolean;freshnessLabel:string;warning:string}
export function buildHistoryMatrix(p:Pick<History,'rows'|'dates'>):{rank:number;cells:({id:string;name:string}&HistoryPoint|null)[]}[]
