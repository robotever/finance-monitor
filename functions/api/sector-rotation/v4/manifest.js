import { v4PublishRequest, createV4Manifest } from '../../../_lib/sector-rotation-v4.js'
export const onRequestPost = ({request,env}) => v4PublishRequest(request,env,createV4Manifest)
