import { describe, expect, it } from 'vitest'
import { createStablePhotoImage } from '@/services/stable-photo-image'

describe('signed image URL replacement without a blank frame', () => {
  it('keeps the loaded original until the replacement has decoded', () => {
    const image = createStablePhotoImage()
    image.setSource('photo?token=old', 'A:P:1')
    image.loaded(0, image.state.slots[0].id)
    expect(image.state.displayed).toBe(0)
    image.setSource('photo?token=new', 'A:P:1')
    expect(image.state.slots[image.state.displayed].url).toBe('photo?token=old')
    const pendingId = image.state.slots[1].id
    image.loaded(1, pendingId)
    expect(image.state.slots[image.state.displayed].url).toBe('photo?token=new')
    expect(image.state.slots[0].url).toBe('')
  })

  it('retains old successful image after failed refresh and accepts a later fresh URL', () => {
    const image = createStablePhotoImage()
    image.setSource('local.jpg', 'A:P:1')
    image.loaded(0, image.state.slots[0].id)
    image.setSource('expired', 'A:P:1')
    image.failed(1, image.state.slots[1].id)
    expect(image.state.slots[image.state.displayed].url).toBe('local.jpg')
    image.setSource('fresh', 'A:P:1')
    image.loaded(1, image.state.slots[1].id)
    expect(image.state.slots[image.state.displayed].url).toBe('fresh')
  })

  it('isolates another account/project immediately and ignores stale load callbacks', () => {
    const image = createStablePhotoImage()
    image.setSource('A-photo', 'A:P:1')
    const oldId = image.state.slots[0].id
    image.loaded(0, oldId)
    image.setSource('B-photo', 'B:Q:1')
    expect(image.state.displayed).toBe(-1)
    expect(image.state.slots.some((slot) => slot.url === 'A-photo')).toBe(false)
    image.loaded(0, oldId)
    expect(image.state.displayed).toBe(-1)
    image.loaded(0, image.state.slots[0].id)
    expect(image.state.slots[image.state.displayed].url).toBe('B-photo')
  })

  it('does not show an intermediate signed URL after a newer response arrives', () => {
    const image = createStablePhotoImage()
    image.setSource('first', 'A:P:1')
    const stale = image.state.slots[0].id
    image.setSource('latest', 'A:P:1')
    image.loaded(0, stale)
    expect(image.state.displayed).toBe(-1)
    image.loaded(0, image.state.slots[0].id)
    expect(image.state.slots[image.state.displayed].url).toBe('latest')
  })
})
