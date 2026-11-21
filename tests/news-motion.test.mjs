import test from 'node:test'
import assert from 'node:assert/strict'
import {resolveNewsMotion} from '../src/features/live-news/motion.mjs'
test('system reduced motion starts static unless the user explicitly chose play',()=>{
 assert.deepEqual(resolveNewsMotion(null,true),{paused:true,allowMotion:false})
 assert.deepEqual(resolveNewsMotion('play',true),{paused:false,allowMotion:true})
})
test('explicit pause is preserved across reload and ordinary autoplay remains enabled',()=>{
 assert.deepEqual(resolveNewsMotion('pause',false),{paused:true,allowMotion:false})
 assert.deepEqual(resolveNewsMotion(null,false),{paused:false,allowMotion:false})
 assert.deepEqual(resolveNewsMotion('invalid',true),{paused:true,allowMotion:false})
})
