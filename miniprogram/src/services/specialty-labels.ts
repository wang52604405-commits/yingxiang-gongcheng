export function specialtyLabels(industry?: string) {
  if (industry === '市政工程' || industry === '市政') {
    return { leaf: '分项/检验批', path: '选择单位、分部、分项或检验批' }
  }
  if (industry === '公路工程' || industry === '公路' || industry === 'highway') {
    return { leaf: '分项', path: '选择单位、分部和分项' }
  }
  return { leaf: '单元', path: '选择单位、分部、单元和工序' }
}
