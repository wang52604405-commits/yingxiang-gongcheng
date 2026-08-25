const ACTIVE_OWNER_KEY = 'engineering-image:active-queue-owner:v3'

Component({
  data: {
    selected: 0,
    badge: 0,
    tabs: [
      { path: '/pages/home/index', label: '工作台', icon: 'home' },
      { path: '/pages/library/index', label: '影像库', icon: 'gallery' },
      { path: '/pages/upload/index', label: '上传', icon: 'camera', primary: true },
      { path: '/pages/queue/index', label: '待上传', icon: 'upload' },
      { path: '/pages/profile/index', label: '我的', icon: 'user' }
    ]
  },
  lifetimes: {
    attached() {
      this.refreshBadge()
    }
  },
  pageLifetimes: {
    show() {
      this.refreshBadge()
    }
  },
  methods: {
    refreshBadge() {
      const owner = wx.getStorageSync(ACTIVE_OWNER_KEY) || ''
      const badge = Number(owner ? wx.getStorageSync(`engineering-image:queue-count:v3:${owner}`) : 0) || 0
      this.setData({ badge: Math.min(99, badge) })
    },
    switchTab(event) {
      const index = Number(event.currentTarget.dataset.index)
      const path = event.currentTarget.dataset.path
      if (!path || index === this.data.selected) return
      this.setData({ selected: index })
      wx.switchTab({ url: path })
    }
  }
})
