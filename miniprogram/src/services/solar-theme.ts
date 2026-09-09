/** NOAA apparent sunrise/sunset threshold; calculations use UTC, independent of phone timezone.
 * https://www.gml.noaa.gov/grad/solcalc/solareqns.PDF
 */
export function solarDaylight(date: Date, latitude: number, longitude: number): boolean | null {
  if (!Number.isFinite(date.getTime()) || !Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null
  const rad = Math.PI / 180
  const year = date.getUTCFullYear()
  const yearStart = Date.UTC(year, 0, 1)
  const days = (Date.UTC(year + 1, 0, 1) - yearStart) / 86400000
  const day = Math.floor((date.getTime() - yearStart) / 86400000) + 1
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600
  const g = 2 * Math.PI / days * (day - 1 + (hour - 12) / 24)
  const eq = 229.18 * (.000075 + .001868 * Math.cos(g) - .032077 * Math.sin(g) - .014615 * Math.cos(2*g) - .040849 * Math.sin(2*g))
  const decl = .006918 - .399912*Math.cos(g) + .070257*Math.sin(g) - .006758*Math.cos(2*g) + .000907*Math.sin(2*g) - .002697*Math.cos(3*g) + .00148*Math.sin(3*g)
  const angle = (hour*60 + eq + 4*longitude) / 4 - 180
  const cosZenith = Math.sin(latitude*rad)*Math.sin(decl) + Math.cos(latitude*rad)*Math.cos(decl)*Math.cos(angle*rad)
  return cosZenith >= Math.cos(90.833*rad)
}
