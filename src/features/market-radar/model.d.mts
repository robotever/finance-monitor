export type Axis='strength'|'heat'|'risk'
export interface Bar {date:string;close:number;volume:number|null}
export interface Factor {key:string;label:string;value:number|null;unit:string;score:number|null;weight:number}
export interface ScorePoint {date:string;strength:number|null;heat:number|null;risk:number|null}
export interface InputEvidence {date:string;up:number|null;down:number|null;flat:number|null;total:number|null;mainNetFlow:number|null;turnover:number|null;fundRatio:number|null;fundMatched:number|null;fundExpected:number|null;membershipMode:string|null;membershipAsOf:string|null;sources:string[];scope:string}
export interface RadarObject extends ScorePoint {inputEvidence?:InputEvidence|null;scoreVersion?:string;id:string;name:string;indexName?:string;code?:string;status:string;change1d:Record<Axis,number|null>|null;change5d:Record<Axis,number|null>|null;history:ScorePoint[];factors:Record<Axis,Factor[]>;return5:number|null;volumeRatio:number|null}
export interface Radar {version:string;checkedAt:number;frequency:string;global:RadarObject;ashare:RadarObject;styles:RadarObject[];asOf:string|null;commonDate:string|null;issues:{id:string;name:string;status:string;date:string|null}[];reconstructedHistory:boolean;inputBatch?:{marketDate:string;observedAt:string}|null;sources?:{id:string;name:string;status:string;observedAt:string|null}[];sourceErrors?:number}
export const RADAR_VERSION:string
export const INDEXES:{id:string;name:string;indexName?:string;code:string;kind:string;market:string}[]
export function parseRadarBars(data:unknown,code:string):Bar[]
export function completedBars<T extends {date:string}>(rows:T[],market?:string,now?:number):T[]
export function indexScoreSeries(rows:Bar[],benchmark?:Bar[],limit?:number,evidence?:object):ScorePoint[]
export function globalScoreSeries(raw:Record<string,{date:string;value:number}[]>,limit?:number):ScorePoint[]
export function deriveRadar(index?:Record<string,{status:string;bars:Bar[]}>,global?:object,now?:number,realInputs?:object):Radar
