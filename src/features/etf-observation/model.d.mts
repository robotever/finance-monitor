export type EtfPoint={date:string;shares:number|null;nav:number|null;splitFactor:number|null}
export type EtfIdentity={code:string;name:string;exchange:string}
export type EtfBundle={schemaVersion:'etf-observation-v1';capBasis:'circulating-a-share';generatedAt:string;sessions:string[];funds:(EtfIdentity&{points:EtfPoint[]})[];marketCaps:{date:string;value:number}[];indexCloses:{date:string;value:number}[];sources:{id:string;url:string;note?:string}[];notes?:string[];cached?:boolean}
export type EtfFundView=EtfIdentity&{date:string|null;shares:number|null;change1d:number|null;change5d:number|null;change20d:number|null;nav:number|null;assetsCny:number|null;flow1d:number|null;flow5d:number|null;flow20d:number|null}
export type EtfSeriesPoint={date:string;assetsCny:number|null;capCny:number|null;ratioPct:number|null;estimatedFlowCny:number|null;fundCount:number}
export type EtfView={date:string|null;generatedAt:string;funds:EtfFundView[];series:EtfSeriesPoint[];ratioPct:number|null;assetsCny:number|null;flow1d:number|null;flow5d:number|null;flow20d:number|null;cached:boolean;notes:string[];scope:string}
export const CORE_ETFS:readonly EtfIdentity[]
export const ETF_VERSION:'etf-observation-v1'
export function validateEtfBundle(b:unknown,now?:number):EtfBundle
export function deriveEtfObservation(b:unknown):EtfView
export function parseSseShares(raw:unknown,code:string):{date:string;shares:number}[]
export function parseSzseShares(raw:unknown,code:string):{date:string;shares:number}[]
