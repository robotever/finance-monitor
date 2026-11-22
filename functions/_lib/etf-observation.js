import {validateEtfBundle,deriveEtfObservation} from '../../src/features/etf-observation/model.mjs'
export const ETF_QUERY='SELECT payload_json FROM etf_observation_latest WHERE id=1'
export async function readEtfObservation(db){
 if(!db)return null
 try{const row=await db.prepare(ETF_QUERY).first();return row?validateEtfBundle(JSON.parse(row.payload_json)):null}catch{return null}
}
export function publicationDate(payload){const date=deriveEtfObservation(payload).date;if(!date)throw Error('NO_COMPLETE_ETF_DATE');return date}
