const ACTIVE_OWNER_KEY = 'engineering-image:active-queue-owner:v3'
const UPLOAD_PRESET_KEY = 'engineering-image:upload-preset:v1'
const PROJECT_KEY = 'engineering-image:selected-project:v1'
Component({
  data:{selected:0,badge:0,tabs:[
    {path:'/pages/home/index',label:'工作台',icon:'home'},
    {path:'/pages/library/index',label:'影像库',icon:'gallery'},
    {action:'capture',label:'采集',icon:'camera',primary:true},
    {path:'/pages/queue/index',label:'待上传',icon:'upload'},
    {path:'/pages/profile/index',label:'我的',icon:'user'}
  ]},
  lifetimes:{attached(){this.refreshBadge()}},
  pageLifetimes:{show(){this.refreshBadge()}},
  methods:{
    refreshBadge(){const owner=wx.getStorageSync(ACTIVE_OWNER_KEY)||'';const badge=Number(owner?wx.getStorageSync(`engineering-image:queue-count:v3:${owner}`):0)||0;this.setData({badge:Math.min(99,badge)})},
    openCapture(){const owner=wx.getStorageSync(ACTIVE_OWNER_KEY)||'';const projectKey=owner?`${PROJECT_KEY}:account:${owner}`:`${PROJECT_KEY}:unbound`;const project=wx.getStorageSync(projectKey)||{};if(!project.id){wx.showModal({title:'尚未同步工程',content:'请先在原电脑登录同一账号并同步工程。',showCancel:false});return}wx.showActionSheet({itemList:['现场拍照','从手机相册选择'],success:({tapIndex})=>{const source=tapIndex===0?'camera':tapIndex===1?'album':'';if(!source)return;const key=owner?`${UPLOAD_PRESET_KEY}:account:${owner}`:`${UPLOAD_PRESET_KEY}:unbound`;wx.setStorageSync(key,{scope:'engineering',category:'construction',mode:'direct'});wx.navigateTo({url:`/pages/upload/index?source=${source}&autopick=1`})}})},
    activate(event){const index=Number(event.currentTarget.dataset.index);const action=event.currentTarget.dataset.action;const path=event.currentTarget.dataset.path;if(action==='capture'){this.openCapture();return}if(!path||index===this.data.selected)return;this.setData({selected:index});wx.switchTab({url:path})}
  }
})
