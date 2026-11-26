import test from 'node:test'
import assert from 'node:assert/strict'
import { turnoverSeries, rangeStart, chartGeometry, resizeWindow, moveWindow, formatTurnover } from '../src/features/market-observation/turnover-chart.mjs'

test('series selects a market and converts yuan to hundred-million yuan without filling missing observations', () => {
 const rows = [{date:'2026-01-01', all:1e12, star:0}, {date:'2026-01-02', all:null, star:2e8}]
 assert.deepEqual(turnoverSeries(rows,'all'), [{date:'2026-01-01',value:10000},{date:'2026-01-02',value:null}])
 assert.deepEqual(turnoverSeries(rows,'star').map(p=>p.value), [0,2])
 assert.equal(rows[0].all,1e12)
})

test('calendar range clamps month-end cutoff and uses last real observation instead of today', () => {
 const rows=['2025-03-30','2025-03-31','2026-02-27','2026-02-28','2026-03-31'].map(date=>({date}))
 assert.equal(rangeStart(rows,1),3)
 assert.equal(rangeStart(rows,12),1)
 assert.equal(rangeStart([],12),0)
})

test('chart breaks at nulls and keeps zero, singleton and all-missing ranges drawable safely', () => {
 const g=chartGeometry([{value:2},{value:null},{value:0},{value:4}])
 assert.equal(g.path.match(/M/g).length,2)
 assert.equal(g.path.match(/L/g).length,1)
 assert.equal(g.coordinates[1],null)
 assert.equal(g.coordinates[2].y,192)
 assert.equal(g.ticks[0].value,0)
 assert.ok(!/NaN|Infinity/.test(g.path))
 const single=chartGeometry([{value:0}]);assert.ok(single.coordinates[0].x>=90 && single.coordinates[0].x<=624)
 assert.ok(Number.isFinite(single.coordinates[0].y))
 assert.equal(chartGeometry([{value:null}]).path,'')
})

test('zoom and pan preserve bounded windows including fewer than five observations', () => {
 assert.deepEqual(resizeWindow(100,0,100,.5),{start:25,end:75})
 assert.deepEqual(moveWindow(100,25,75,1),{start:42,end:92})
 assert.deepEqual(moveWindow(100,42,92,1),{start:50,end:100})
 assert.deepEqual(resizeWindow(3,0,3,.1),{start:0,end:3})
 assert.deepEqual(resizeWindow(0,0,0,.5),{start:0,end:0})
})

test('table formatting distinguishes positive, negative, zero and missing yuan', () => {
 assert.equal(formatTurnover(123456789,true),'+1.23')
 assert.equal(formatTurnover(-123456789,true),'-1.23')
 assert.equal(formatTurnover(0,true),'0.00')
 assert.equal(formatTurnover(null,true),'—')
})
