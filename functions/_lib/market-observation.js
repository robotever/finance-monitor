import {validateMarketObservation} from '../../src/features/market-observation/model.mjs'
export const OBSERVATION_QUERY='SELECT payload_json FROM market_observation_latest WHERE id=1'
export async function readMarketObservation(db){if(!db)return null;try{const row=await db.prepare(OBSERVATION_QUERY).first();return row?validateMarketObservation(JSON.parse(row.payload_json)):null}catch{return null}}
