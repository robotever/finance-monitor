import type {LiveNewsItem} from './model.mjs'
export type NewsCategory='company'|'industry'|'market'|'macro'
export const NEWS_POLICY_VERSION:string
export const CATEGORY_LABELS:Record<NewsCategory,string>
export function classifyFinancialNews(item:LiveNewsItem):NewsCategory|null
export function financeNewsPolicy(items:LiveNewsItem[]):LiveNewsItem[]
export function marketObservation(id:string,quote:unknown,origin:string,now?:number):LiveNewsItem|null

export function selectFinancialNews(items:LiveNewsItem[],now?:number):LiveNewsItem[]
export function mergeFinancialNews(incoming:LiveNewsItem[],previous:LiveNewsItem[],now?:number):LiveNewsItem[]
export function mediaUnavailable(sources:{id:string;status:string}[]):boolean
