export type TurnoverId='all'|'sh'|'sz'|'chinext'|'star'
export type TurnoverPoint={date:string;all:number|null;sh:number|null;sz:number|null;chinext:number|null;star:number|null}
export type TurnoverPayload={version:'turnover-structure-v1';date:string;previousDate:string;asOf:string;comparisonTime:string|null;rows:{id:TurnoverId;name:string;comparisonMode:'same-minute'|'daily-close'|'unavailable';currentCny:number|null;currentAsOf:string;previousSameTimeCny:number|null;changeCny:number|null;changePct:number|null;comparisonAsOf:string|null;reason:string|null}[];history:{startDate:string;endDate:string;asOf:string;points:TurnoverPoint[]};sources:{id:string;url:string;asOf:string}[];notes:string[]}
export function validateTurnover(p:unknown,now?:number):TurnoverPayload
