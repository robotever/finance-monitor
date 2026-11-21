export interface Point {date:string;value:number}
export type State='normal'|'watch'|'stress'|'unknown'
export interface Metric {id:string;label:string;unit:string;source:string;frequency:string;value:number|null;date:string|null;stale:boolean;failed:boolean;change5:number|null;return5:number|null;changeWindow?:number|null;windowLabel?:string;percentile:number|null;sampleCount?:number;history:Point[]}
export interface RiskCard {id:string;title:string;state:State;label:string;metrics:Metric[];reason:string;impact:string;trend:Point[];trendLabel:string;partial:boolean;coverage:string|null;alignedReturns?:{id:string;value:number}[];alignedDate?:string|null}
export interface Source {id:string;name:string;status:string;lastSuccessAt:number|null;observedAt:string|null;cached?:boolean;safeErrorCode?:string}
export interface RiskModel {version:string;checkedAt:number;state:State;summary:string;confirmations:string[];assessable:number;total:number;watchCount:number;stressCount:number;unknownCount:number;cards:RiskCard[];sources?:Source[];sourceErrors?:number}
export const RISK_VERSION:string
export const RULES:Readonly<Record<string,number[]>>
export const METRICS:Record<string,Record<string,string>>
export function normalizeSeries(points:Point[],now?:number):Point[]
export function alignSpread(a:Point[],b:Point[],scale?:number):Point[]
export function metricSummary(points:Point[],definition:Record<string,string>,now?:number,failed?:boolean):Metric
export function buildRiskModel(raw?:Record<string,Point[]>,failed?:string[],now?:number):RiskModel
