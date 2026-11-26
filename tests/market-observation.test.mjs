import test from 'node:test'
import assert from 'node:assert/strict'
import {validateMarketObservation,MARKET_OBSERVATION_VERSION} from '../src/features/market-observation/model.mjs'
import {fixture} from './fixtures/market-observation.mjs'

test('preserves zeros, negative institutional amounts and announced future range ends',()=>{const b=fixture();assert.equal(validateMarketObservation(b),b);assert.equal(b.groups[0].metrics[1].value,1);assert.equal(b.details.dragonTiger.rows[0].netCny,-100)})
test('rejects incomplete capture, duplicate groups and impossible units',()=>{for(const change of [b=>b.scope.received=9,b=>b.groups[1].id='breadth',b=>b.groups[0].metrics[0].value=101,b=>b.groups[0].metrics[1].value=.5,b=>b.groups[2].metrics[0].unit='元',b=>b.snapshotAt='2099-01-01T00:00:00Z',b=>b.privateKey='must-never-publish']){const b=fixture();change(b);assert.throws(()=>validateMarketObservation(b))}})
test('does not accept stale daily dates disguised as this session or leaked URL credentials',()=>{for(const change of [b=>b.previousMarketDate='2026-11-27',b=>b.sources[0].url+='&apikey=secret',b=>b.sources[0].url='http://fuyao.aicubes.cn/api/a-share/prices/snapshot',b=>b.details.dragonTiger.date='2026-11-24',b=>b.details.distribution[0].count=12]){const b=fixture();change(b);assert.throws(()=>validateMarketObservation(b))}})
test('missing detail source distinguished from verified empty result',()=>{const b=fixture();b.details.dragonTiger.status='failed';b.details.dragonTiger.rows=[];b.details.dragonTiger.note='来源未更新';b.groups[1].metrics[0].value=null;b.groups[1].metrics[0].reason='历史不足';assert.ok(validateMarketObservation(b));assert.equal(b.groups[1].metrics[0].value,null)})

test('a numeric indicator cannot claim a zero-sized sample',()=>{const p=fixture();p.groups[2].metrics[3].value=100;p.groups[2].metrics[3].sample=0;assert.throws(()=>validateMarketObservation(p))})
