export interface LiveNewsItem {id:string;title:string;url:string;source:string;sourceName:string;publishedAt:number;important:boolean;sources?:string[]}
export interface LiveSource {id:string;name:string;status:'ok'|'empty'|'failed';newestAt:number|null}
export interface LiveNewsResponse {items:LiveNewsItem[];sources:LiveSource[];fetchedAt:number}
export const NEWS_WINDOW_MS:number
export const SOURCE_NAMES:Record<string,string>
export function parsePublishedAt(value:unknown):number|null
export function freshNews(items:LiveNewsItem[],now?:number):LiveNewsItem[]
export function normalizeFeed(source:string,data:unknown):LiveNewsItem[]
export function collectNews(loader:(source:string)=>Promise<unknown>,now?:number,sources?:string[]):Promise<LiveNewsResponse>

export function activeNews(items:LiveNewsItem[],now?:number):LiveNewsItem[]
