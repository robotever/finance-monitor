import { v4Read } from '../../../_lib/sector-rotation-v4-read.js'

export const onRequestGet = context => v4Read(context, 'latest')
