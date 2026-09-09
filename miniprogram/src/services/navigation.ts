import { nextTick } from 'vue'
import { themeState } from './theme'
import { launchCapture } from './capture-entry'
const TAB_PATHS:Array<string|null>=['/pages/home/index','/pages/library/index',null,'/pages/queue/index','/pages/profile/index']
export function switchTab(index:number):void{if(index===2){void launchCapture({scope:'engineering',category:'construction',mode:'direct'});return}const url=TAB_PATHS[index];if(url)uni.switchTab({url})}
export function syncTabBar(index:number):void{const pages=getCurrentPages();const page=pages.length?pages[pages.length-1] as any:null;const apply=()=>page?.getTabBar?.()?.setData?.({selected:index,theme:themeState.resolved});apply();void nextTick(apply)}
