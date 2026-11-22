export interface LiveNewsItem {id:string;title:string;url:string;source:string;sourceName:string;publishedAt:number;important:boolean;sources?:string[];category?:'company'|'industry'|'market'|'macro';categoryLabel?:string;relatedStockCount?:number;contextOnly?:boolean}
export interface LiveSource {id:string;name:string;status:'ok'|'empty'|'failed';newestAt:number|null;note?:string}
export interface LiveNewsResponse {localStatus?:{mode:string;lastSuccessAt:number|null;note?:string};archiveItems?:LiveNewsItem[];items:LiveNewsItem[];sources:LiveSource[];fetchedAt:number;policyVersion?:string;categories?:Record<string,number>;filteredCount?:number}
export const NEWS_WINDOW_MS:number
export const SOURCE_NAMES:Record<string,string>
export function parsePublishedAt(value:unknown):number|null
export function freshNews(items:LiveNewsItem[],now?:number,options?:{accept?:(item:LiveNewsItem)=>boolean}):LiveNewsItem[]
export function normalizeFeed(source:string,data:unknown):LiveNewsItem[]
export function collectNews(loader:(source:string)=>Promise<unknown>,now?:number,sources?:string[]):Promise<LiveNewsResponse>

export function activeNews(items:LiveNewsItem[],now?:number):LiveNewsItem[]
