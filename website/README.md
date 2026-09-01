# 工程影像管理平台宣传网站

这是工程影像管理平台的正式宣传网站源码，面向水利、房建、市政、电力四大专业。

## 目录

- `index.html`：首页
- `product.html`：产品介绍
- `usage.html`：使用说明
- `download.html`：下载页
- `contact.html`：联系页
- `assets/`：网站样式、脚本和界面截图
- `site-content.json`：后续统一维护的网站宣传内容

## 维护入口

优先修改 `site-content.json` 中的站点名称、小程序介绍、专业列表和下载链接；页面结构和样式分别在各 HTML 文件及 `assets/style.css` 中维护。交互动效集中在 `assets/site.js`，并兼容系统“减少动态效果”设置。

发布时先上传到服务器临时目录并校验，再覆盖站点静态文件。不得覆盖或删除服务器已有的 `download/` 安装包与教程目录。
