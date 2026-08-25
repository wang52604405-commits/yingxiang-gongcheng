function randomHex(size: number): string {
  const bytes = new Uint8Array(size)
  const cryptoObject = globalThis.crypto
  if (cryptoObject?.getRandomValues) {
    cryptoObject.getRandomValues(bytes)
  } else {
    for (let index = 0; index < size; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  }
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

export function createUuid(): string {
  const hex = randomHex(16).split('')
  hex[12] = '4'
  hex[16] = ((Number.parseInt(hex[16], 16) & 0x3) | 0x8).toString(16)
  return `${hex.slice(0, 8).join('')}-${hex.slice(8, 12).join('')}-${hex.slice(12, 16).join('')}-${hex.slice(16, 20).join('')}-${hex.slice(20).join('')}`
}
