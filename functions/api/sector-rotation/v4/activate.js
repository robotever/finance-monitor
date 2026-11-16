import { v4PublishRequest, activateV4Manifest } from '../../../_lib/sector-rotation-v4.js'
export const onRequestPost = ({request,env}) => v4PublishRequest(request,env,activateV4Manifest)
