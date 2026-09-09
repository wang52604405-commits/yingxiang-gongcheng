# 企业标识官方来源

检索和下载日期：2026-09-09T22:42:28（Asia/Shanghai）。

所有位图取自企业官方站点页面实际引用的原始文件；未使用素材网站、搜索缩略图、生成图片或重绘。除中国交建 SVG 按原始矢量等比栅格化外，PNG 保留下载原始字节。

| 名称 | 官方网站 | 原始资产 | 应用文件 | 尺寸 | SHA256 |
|---|---|---|---|---|---|
| 中国中铁 | [https://www.crec.cn/](https://www.crec.cn/) | [原文件](https://www.crec.cn/uiFramework/commonResource/image/2021053021542376908.png) | `miniprogram/src/static/company-logos/crec.png` | 300 × 44 | `4bc28d338bc17ebbfa90f00280ba6a21f76d61e09c1fee8e506c5b954a295489` |
| 中国铁建 | [https://www.crcc.cn/](https://www.crcc.cn/) | [原文件](https://www.crcc.cn/cms_files/filemanager/49/picture/20263/B69EA7594F818C8BE30542F7E56F999E.png) | `miniprogram/src/static/company-logos/crcc.png` | 1160 × 153 | `f2769a0fb1dd4503862f6236172e305d089acca113e1783845cf4431ccd1ff8d` |
| 中国建筑 | [https://www.cscec.com.cn/](https://www.cscec.com.cn/) | [原文件](https://www.cscec.com.cn/images/P020201228373005410587.png) | `miniprogram/src/static/company-logos/cscec.png` | 305 × 56 | `5c98efcd1c0306cd1e96c0e65145cfe723183c1c55553ae81d5be61ba885d0ba` |
| 中国电建 | [https://www.powerchina.cn/](https://www.powerchina.cn/) | [原文件](https://www.powerchina.cn/cms_files/filemanager/640784126/picture/20265/6F513FB873986087665367E5C76959AD.png) | `miniprogram/src/static/company-logos/powerchina.png` | 1920 × 530 | `64b1e30b55571f5f232a5be6828c8c0b65214017d0bdea15a2a1061a19ed2d37` |
| 中国能建 | [https://www.ceec.net.cn/](https://www.ceec.net.cn/) | [原文件](https://www.ceec.net.cn/picture/0/2109020906053888588.png) | `miniprogram/src/static/company-logos/ceec.png` | 411 × 39 | `a30eb3f8c11c5609ad17341085e8067772e41307fb25ea6b059e93b091f01bc4` |
| 中国交建 | [https://en.ccccltd.cn/](https://en.ccccltd.cn/) | [原文件](https://en.ccccltd.cn/images/ZJJTlogo.svg) | `miniprogram/src/static/company-logos/cccc.png` | 400 × 147 | `1368be85836f402c91c62c3d9042e806a075f646c70773114c9acaff01168658` |

## 官方关联及核验

- 中国中铁：`www.crec.cn` 首页标题“中国中铁 / 中国中铁股份有限公司”；页面头部 `.logo` 直接引用该图，图中为 CREC 地球标识及“中国中铁股份有限公司”。
- 中国铁建：`www.crcc.cn` 首页公共头部脚本 `/cms_files/jcms1/web1/site/script/259/2109021752047717.js` 引用该 PNG；内容为 CRCC 及“中国铁建股份有限公司”。
- 中国建筑：`www.cscec.com.cn` 首页 `menubox_logoFix` 直接引用该图；内容包含 CSCEC 与“中国建筑”，不是建筑科学研究院等同名机构。
- 中国电建：`www.powerchina.cn` 首页头部脚本 `/cms_files/filemanager/640784126/script/20265/B0F6D29C71FD85761D60CFBF30EC4AB9.js` 引用该 PNG，alt 为“中国电建 POWERCHINA”。
- 中国能建：`www.ceec.net.cn` 首页头部脚本 `/script/0/1630468510359.js` 引用该 PNG；内容为 CEEC 与“中国能源建设股份有限公司”。
- 中国交建：中文主站本次返回 HTTP 521，使用同集团官方英文站 `en.ccccltd.cn` 首页 `.logo` 引用的 `/images/ZJJTlogo.svg`。保留原始 SVG；通过 bundled sharp/libvips 按 density 192 原样栅格化为 400×147 PNG，未改动路径、颜色或文字。

已逐个使用图像查看工具检查下载文件，不使用整页截图或横幅充当标识。透明底 PNG 需在界面与水印中按 alpha 通道正常合成，使用 aspectFit/contain，禁止拉伸。

命名严格区分：中国中铁（CREC）≠中国铁建（CRCC）；中国电建（POWERCHINA）≠中国能建（CEEC）。此处“中水”需求暂提供明确命名的“中国电建”，未把中国电建标识冒称为独立 SINOHYDRO 标识。

## 水印功能参考

- [今日水印相机官方 SDK 文档](https://docs.xhey.top/docs/camerasdk)：仅用作相机、水印字段及企业标识能力的功能参考；本项目不复制其界面素材或宣称已接入其 SDK。
