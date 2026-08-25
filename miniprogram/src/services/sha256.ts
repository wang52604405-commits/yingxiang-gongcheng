const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

const rotateRight = (value: number, bits: number) => (value >>> bits) | (value << (32 - bits))

export class IncrementalSha256 {
  private readonly hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ])
  private readonly words = new Uint32Array(64)
  private remainder = new Uint8Array(0)
  private byteLength = 0
  private finalized = false

  private processBlock(bytes: Uint8Array, offset: number): void {
    const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 64)
    const { words, hash } = this
    for (let index = 0; index < 16; index += 1) words[index] = view.getUint32(index * 4, false)
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotateRight(words[index - 15], 7) ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >>> 3)
      const s1 = rotateRight(words[index - 2], 17) ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >>> 10)
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0
    }

    let [a, b, c, d, e, f, g, h] = hash
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25)
      const choice = (e & f) ^ (~e & g)
      const temp1 = (h + sum1 + choice + K[index] + words[index]) >>> 0
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22)
      const majority = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (sum0 + majority) >>> 0
      h = g
      g = f
      f = e
      e = (d + temp1) >>> 0
      d = c
      c = b
      b = a
      a = (temp1 + temp2) >>> 0
    }

    hash[0] = (hash[0] + a) >>> 0
    hash[1] = (hash[1] + b) >>> 0
    hash[2] = (hash[2] + c) >>> 0
    hash[3] = (hash[3] + d) >>> 0
    hash[4] = (hash[4] + e) >>> 0
    hash[5] = (hash[5] + f) >>> 0
    hash[6] = (hash[6] + g) >>> 0
    hash[7] = (hash[7] + h) >>> 0
  }

  update(input: Uint8Array): this {
    if (this.finalized) throw new Error('SHA-256 已完成，不能继续写入')
    if (!input.byteLength) return this
    this.byteLength += input.byteLength
    let offset = 0
    if (this.remainder.byteLength) {
      const needed = 64 - this.remainder.byteLength
      if (input.byteLength < needed) {
        const merged = new Uint8Array(this.remainder.byteLength + input.byteLength)
        merged.set(this.remainder)
        merged.set(input, this.remainder.byteLength)
        this.remainder = merged
        return this
      }
      const block = new Uint8Array(64)
      block.set(this.remainder)
      block.set(input.subarray(0, needed), this.remainder.byteLength)
      this.processBlock(block, 0)
      this.remainder = new Uint8Array(0)
      offset = needed
    }
    while (offset + 64 <= input.byteLength) {
      this.processBlock(input, offset)
      offset += 64
    }
    if (offset < input.byteLength) this.remainder = input.slice(offset)
    return this
  }

  digestHex(): string {
    if (this.finalized) throw new Error('SHA-256 结果已经读取')
    const paddedLength = this.remainder.byteLength < 56 ? 64 : 128
    const padded = new Uint8Array(paddedLength)
    padded.set(this.remainder)
    padded[this.remainder.byteLength] = 0x80
    const bitLength = this.byteLength * 8
    const view = new DataView(padded.buffer)
    view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x1_0000_0000), false)
    view.setUint32(paddedLength - 4, bitLength >>> 0, false)
    for (let offset = 0; offset < paddedLength; offset += 64) this.processBlock(padded, offset)
    this.finalized = true
    return Array.from(this.hash, (value) => value.toString(16).padStart(8, '0')).join('')
  }
}

export function sha256Hex(input: ArrayBuffer): string {
  return new IncrementalSha256().update(new Uint8Array(input)).digestHex()
}

export function readFileBuffer(filePath: string): Promise<ArrayBuffer> {
  const wxApi = (globalThis as { wx?: any }).wx
  if (!wxApi?.getFileSystemManager) return Promise.reject(new Error('当前环境无法读取照片文件'))
  return new Promise((resolve, reject) => {
    wxApi.getFileSystemManager().readFile({
      filePath,
      success: (result: { data: ArrayBuffer }) => resolve(result.data),
      fail: (error: unknown) => reject(error),
    })
  })
}

export function readFilePrefix(filePath: string, maxBytes = 2 * 1024 * 1024): Promise<ArrayBuffer> {
  if (!Number.isInteger(maxBytes) || maxBytes <= 0) return Promise.reject(new Error('读取长度必须大于 0'))
  const wxApi = (globalThis as { wx?: any }).wx
  const fs = wxApi?.getFileSystemManager?.()
  if (!fs) return Promise.reject(new Error('当前环境无法读取照片文件'))
  if (fs.open && fs.read && fs.close) {
    return openFile(fs, filePath).then(async (fd) => {
      try {
        const chunk = await readChunk(fs, fd, 0, maxBytes)
        return chunk.data.slice(0, chunk.bytesRead)
      } finally {
        await closeFile(fs, fd)
      }
    })
  }
  return new Promise((resolve, reject) => fs.readFile({
    filePath,
    position: 0,
    length: maxBytes,
    success: (result: { data: ArrayBuffer }) => resolve(result.data),
    fail: reject,
  }))
}

export async function hashFile(filePath: string): Promise<string> {
  return hashFileInChunks(filePath)
}

const DEFAULT_CHUNK_SIZE = 1024 * 1024

function openFile(fs: any, filePath: string): Promise<string | number> {
  return new Promise((resolve, reject) => fs.open({ filePath, flag: 'r', success: (result: { fd: string | number }) => resolve(result.fd), fail: reject }))
}

function readChunk(fs: any, fd: string | number, position: number, length: number): Promise<{ bytesRead: number; data: ArrayBuffer }> {
  const buffer = new ArrayBuffer(length)
  return new Promise((resolve, reject) => fs.read({
    fd,
    arrayBuffer: buffer,
    offset: 0,
    length,
    position,
    success: (result: { bytesRead: number; arrayBuffer?: ArrayBuffer }) => resolve({ bytesRead: Number(result.bytesRead || 0), data: result.arrayBuffer || buffer }),
    fail: reject,
  }))
}

function closeFile(fs: any, fd: string | number): Promise<void> {
  return new Promise((resolve) => fs.close({ fd, success: () => resolve(), fail: () => resolve() }))
}

export async function readFileChunk(filePath: string, position: number, length: number): Promise<ArrayBuffer> {
  if (!Number.isInteger(position) || position < 0 || !Number.isInteger(length) || length <= 0) throw new Error('照片分片范围无效')
  const wxApi = (globalThis as { wx?: any }).wx
  const fs = wxApi?.getFileSystemManager?.()
  if (!fs?.open || !fs?.read || !fs?.close) throw new Error('当前微信基础库不支持原图分片读取，请升级微信后重试')
  const fd = await openFile(fs, filePath)
  try {
    const chunk = await readChunk(fs, fd, position, length)
    return chunk.bytesRead === chunk.data.byteLength ? chunk.data : chunk.data.slice(0, chunk.bytesRead)
  } finally {
    await closeFile(fs, fd)
  }
}

export async function hashFileInChunks(filePath: string, chunkSize = DEFAULT_CHUNK_SIZE): Promise<string> {
  if (!Number.isInteger(chunkSize) || chunkSize < 64) throw new Error('SHA-256 分块大小必须至少为 64 字节')
  const wxApi = (globalThis as { wx?: any }).wx
  const fs = wxApi?.getFileSystemManager?.()
  if (!fs?.open || !fs?.read || !fs?.close) return sha256Hex(await readFileBuffer(filePath))
  const fd = await openFile(fs, filePath)
  const hasher = new IncrementalSha256()
  let position = 0
  try {
    while (true) {
      const chunk = await readChunk(fs, fd, position, chunkSize)
      if (!chunk.bytesRead) break
      hasher.update(new Uint8Array(chunk.data, 0, chunk.bytesRead))
      position += chunk.bytesRead
    }
    return hasher.digestHex()
  } finally {
    await closeFile(fs, fd)
  }
}
