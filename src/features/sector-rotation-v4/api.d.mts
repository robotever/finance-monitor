import type {Options,Universe,Axis,Latest,Catalog,History,Detail,Result,CatalogOptions} from './types'
export function loadHithinkLatest(options?:Options):Promise<Result<Latest>>
export function loadHithinkCatalog(options:CatalogOptions):Promise<Result<Catalog>>
export function loadHithinkHistory(options:Options & {universe:Universe;axis:Axis;days?:number}):Promise<Result<History>>
export function loadHithinkDetail(options:Options & {universe:Universe;id:string;days?:number}):Promise<Result<Detail>>
