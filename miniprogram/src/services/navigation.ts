import { launchCapture } from './capture-entry'
const TAB_PATHS:Array<string|null>=['/pages/home/index','/pages/library/index',null,'/pages/queue/index','/pages/profile/index']
export function switchTab(index:number):void{if(index===2){void launchCapture({scope:'engineering',category:'construction',mode:'direct'});return}const url=TAB_PATHS[index];if(url)uni.switchTab({url})}
export function syncTabBar(index:number):void{const page=getCurrentPages().at(-1) as any;page?.getTabBar?.()?.setData?.({selected:index})}
