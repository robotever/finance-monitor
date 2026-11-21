import test from 'node:test'
import assert from 'node:assert/strict'
import {advanceNewsOffset} from '../src/features/live-news/scroll.mjs'
test('scroll advances by elapsed time rather than monitor refresh rate',()=>{
 let sixty=0,high=0
 for(let i=0;i<60;i++)sixty=advanceNewsOffset(sixty,1000/60,1000)
 for(let i=0;i<144;i++)high=advanceNewsOffset(high,1000/144,1000)
 assert.ok(Math.abs(sixty+30)<.001);assert.ok(Math.abs(high-sixty)<.001)
})
test('loop wraps seamlessly at exactly one copy and bounds inactive-tab gaps',()=>{
 assert.equal(advanceNewsOffset(-99,100,100),-2)
 assert.equal(advanceNewsOffset(-20,60000,100),-23)
 assert.equal(advanceNewsOffset(-20,50,0),0)
 assert.equal(advanceNewsOffset(-20,-1,100),-20)
})
