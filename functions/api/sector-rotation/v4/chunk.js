import { v4PublishRequest, uploadV4Chunk } from '../../../_lib/sector-rotation-v4.js'
export const onRequestPost = ({request,env}) => v4PublishRequest(request,env,uploadV4Chunk)
