import { apiFetchBlobUrl } from '@/lib/api'

/**
 * Fetch a PDF the API will only hand over with a bearer token, and put
 * it in front of the person.
 *
 * The obvious version — await the fetch, then `window.open` — is
 * blocked by the popup blocker, because by the time it runs the click
 * is over and the browser no longer counts the call as something the
 * person asked for. It fails *silently*: no error, no tab, nothing to
 * see. Which is exactly what it looked like from the outside — a
 * spinner that finished and produced nothing, four times over.
 *
 * So the tab is opened while the click is still in hand, and pointed at
 * the file once it arrives. If popups are blocked outright there is no
 * tab to point, and the file is saved instead of lost.
 */
export async function openAuthedPdf(
  path: string,
  filename: string,
): Promise<'tab' | 'download'> {
  const tab = window.open('', '_blank')
  let url: string | null = null
  try {
    url = await apiFetchBlobUrl(path)
    if (tab && !tab.closed) {
      tab.location.href = url
      return 'tab'
    }
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    return 'download'
  } catch (err) {
    tab?.close()
    throw err
  } finally {
    // Long enough for the tab to have loaded it; the download has
    // already read it by the time click() returns.
    const created = url
    if (created) setTimeout(() => URL.revokeObjectURL(created), 60_000)
  }
}
