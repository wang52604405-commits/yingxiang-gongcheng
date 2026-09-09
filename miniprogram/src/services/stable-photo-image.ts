import { reactive } from 'vue'

/** Keep the decoded previous image visible until the new signed URL has loaded. */
export function createStablePhotoImage() {
  const state = reactive({ slots: [{ url: '', id: 0 }, { url: '', id: 0 }], displayed: -1 })
  let context = ''
  let latestUrl = ''
  let serial = 0
  function setSource(url: string, nextContext: string) {
    if (context !== nextContext) {
      context = nextContext
      latestUrl = ''
      state.displayed = -1
      state.slots = [{ url: '', id: ++serial }, { url: '', id: ++serial }]
    }
    if (latestUrl === url) return
    latestUrl = url
    if (!url) {
      state.displayed = -1
      state.slots = [{ url: '', id: ++serial }, { url: '', id: ++serial }]
      return
    }
    const index = state.displayed === 0 ? 1 : 0
    state.slots[index] = { url, id: ++serial }
  }
  function loaded(index: number, id: number) {
    const slot = state.slots[index]
    if (slot?.id !== id || slot.url !== latestUrl) return
    state.displayed = index
    const previous = index === 0 ? 1 : 0
    state.slots[previous] = { url: '', id: ++serial }
  }
  function failed(index: number, id: number) {
    if (state.slots[index]?.id !== id) return
    // A failed replacement must not hide the working old photo. A later refreshed
    // signature can retry; stale callbacks cannot touch another account's photo.
    if (state.displayed !== index) state.slots[index] = { url: '', id: ++serial }
  }
  return { state, setSource, loaded, failed }
}
