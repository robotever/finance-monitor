export interface Instrument {id:string;name:string;code?:string;symbol?:string;provider:string;unit?:string;description:string;session?:string}
export interface MarketQuote {price:number;previousClose:number;changePercent:number;marketDate:string;observedAt:string;points:{time:string;price:number}[];status:string;provider:string;fetchedAt:number}
export const INSTRUMENTS:Instrument[]
export function widgetConfig(id:string):Record<string,unknown>
export function parseMinute(data:unknown,code:string,now?:number):MarketQuote
export function chartX(time:string,session?:string):number
export function chartGeometry(points:{time:string;price:number}[],previousClose:number,session?:string):{min:number;max:number;baseline:number;lastX:number;path:string}|null

export function parseDaily(data:unknown,code:string,now?:number):MarketQuote

export function parseDollar(quoteText:string,historyText:string,now?:number):MarketQuote
