/** Official website assets. Provenance: docs/company-logo-sources.md. */
export interface CompanyLogo {
  id: string
  name: string
  path: string
  sourceUrl: string
  symbolCrop: { x: number; y: number; width: number; height: number }
}

export const COMPANY_LOGOS: CompanyLogo[] = [
  {
    "id": "crec",
    "symbolCrop": { "x": 0, "y": 0, "width": 56, "height": 44 },
    "name": "中国中铁",
    "path": "/static/company-logos/crec.png",
    "sourceUrl": "https://www.crec.cn/uiFramework/commonResource/image/2021053021542376908.png"
  },
  {
    "id": "crcc",
    "symbolCrop": { "x": 17, "y": 1, "width": 157, "height": 107 },
    "name": "中国铁建",
    "path": "/static/company-logos/crcc.png",
    "sourceUrl": "https://www.crcc.cn/cms_files/filemanager/49/picture/20263/B69EA7594F818C8BE30542F7E56F999E.png"
  },
  {
    "id": "cscec",
    "symbolCrop": { "x": 0, "y": 0, "width": 56, "height": 56 },
    "name": "中国建筑",
    "path": "/static/company-logos/cscec.png",
    "sourceUrl": "https://www.cscec.com.cn/images/P020201228373005410587.png"
  },
  {
    "id": "powerchina",
    "symbolCrop": { "x": 0, "y": 0, "width": 688, "height": 530 },
    "name": "中国电建",
    "path": "/static/company-logos/powerchina.png",
    "sourceUrl": "https://www.powerchina.cn/cms_files/filemanager/640784126/picture/20265/6F513FB873986087665367E5C76959AD.png"
  },
  {
    "id": "ceec",
    "symbolCrop": { "x": 0, "y": 0, "width": 109, "height": 39 },
    "name": "中国能建",
    "path": "/static/company-logos/ceec.png",
    "sourceUrl": "https://www.ceec.net.cn/picture/0/2109020906053888588.png"
  },
  {
    "id": "cccc",
    "symbolCrop": { "x": 0, "y": 0, "width": 138, "height": 147 },
    "name": "中国交建",
    "path": "/static/company-logos/cccc.png",
    "sourceUrl": "https://en.ccccltd.cn/images/ZJJTlogo.svg"
  }
]
