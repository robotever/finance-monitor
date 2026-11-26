import type { TurnoverPayload } from './turnover.mjs'
export type MarketId = 'all' | 'sh' | 'sz' | 'chinext' | 'star'
export type ChartPoint = {date:string;value:number|null}
export function turnoverSeries(points:TurnoverPayload['history']['points'],market:MarketId):ChartPoint[]
export function rangeStart(points:{date:string}[],months:number):number
export function chartGeometry(points:{value:number|null}[]):{path:string;coordinates:({x:number;y:number}|null)[];ticks:{value:number;y:number}[]}
export function resizeWindow(length:number,start:number,end:number,factor:number):{start:number;end:number}
export function moveWindow(length:number,start:number,end:number,direction:number):{start:number;end:number}
export function formatTurnover(value:number|null,signed?:boolean):string
