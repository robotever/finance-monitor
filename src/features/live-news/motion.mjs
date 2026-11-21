// An explicit per-site play choice may override reduced motion for this ticker.
export const NEWS_MOTION_KEY='newsmonitor.rail.motion.v1'
export function resolveNewsMotion(choice,reduced){
 return {paused:choice==='pause'||choice!=='play'&&reduced,allowMotion:choice==='play'}
}
