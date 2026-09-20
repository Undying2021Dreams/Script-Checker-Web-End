import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PaperImage, PaperSurface } from '@/components/Paper'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { CardSkeleton, EmptyState, PageHeader, Pending, StatusPill } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useDeleteSubmissionPage,
  useHandInSubmission,
  useSubmissionPages,
  useUploadSubmission,
} from '@/lib/queries'

/** Something chosen but not yet sent. */
type Queued = {
  key: string
  file: File
  /** One page, or a document that contains all of them. */
  kind: 'page' | 'document'
  /** Shown immediately, from the device's own copy. Pages only. */
  preview?: string
  /** 1-based, as the student said it. Pages only — a document's pages
      identify themselves from the codes printed on them. */
  pageNumber?: number
  status: 'waiting' | 'uploading' | 'failed'
  error?: string
}

let nextKey = 0

/**
 * Where a student assembles a script and hands it in.
 *
 * Uploading straight from a row in a list gave no way to see what had
 * been sent, no way to take a bad page back, and no moment at which the
 * student said "that's my answer". Photographing several pages of
 * handwriting is not one action, so it gets a page of its own.
 *
 * Photographs are queued and sent one at a time in the background. The
 * camera used to be disabled until each upload came back, which meant
 * standing over the desk waiting between pages — the upload is the
 * slow part and the student has nothing to do with it. Sending them
 * one at a time rather than all at once is deliberate: the first
 * upload is what creates the submission, and several racing to create
 * it is the bug that once split one script across four.
 */
export function SubmitPage() {
  const { questionId = '' } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()

  const courseId = params.get('course') ?? ''
  const [submissionId, setSubmissionId] = useState<string | null>(params.get('submission'))
  // The queue worker runs outside React's render, so it reads the id
  // from here rather than from state it may have closed over. Only the
  // worker changes it, and it does so as soon as the server answers —
  // before the state it also sets has been applied.
  const submissionIdRef = useRef(submissionId)

  const [queue, setQueue] = useState<Queued[]>([])
  const sending = useRef(false)
  // Bumped when an upload settles, so the worker looks for more work
  // even when the queue itself did not change shape.
  const [tick, setTick] = useState(0)

  // Held between choosing a photograph and saying which page it is.
  const [asking, setAsking] = useState<{ files: File[]; preview: string } | null>(null)
  const [pageNumber, setPageNumber] = useState('')

  const cameraRef = useRef<HTMLInputElement>(null)
  const imageRef = useRef<HTMLInputElement>(null)
  const pdfRef = useRef<HTMLInputElement>(null)

  const upload = useUploadSubmission(questionId)
  const { data, isLoading } = useSubmissionPages(submissionId)
  const removePage = useDeleteSubmissionPage(submissionId ?? '')
  const handIn = useHandInSubmission(submissionId ?? '')

  const pages = data?.pages ?? []

  // What to offer as the next page number: one past the highest page
  // either sent or waiting, so photographing pages in order is a
  // matter of accepting what is already filled in.
  const suggestedPage = Math.max(
    0,
    ...pages.map((p) => p.page_index + 1),
    ...queue.flatMap((q) => (q.pageNumber != null ? [q.pageNumber] : [])),
  ) + 1

  const clearInputs = () => {
    for (const ref of [cameraRef, imageRef, pdfRef]) {
      if (ref.current) ref.current.value = ''
    }
  }

  /** A camera shot, or an image file — either way, one page. */
  const choosePages = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    clearInputs()
    if (files.length === 0) return

    // Asked here, while the photograph is in hand, rather than after a
    // failed upload has come back to say the codes could not be read.
    // On a phone that answer was needed nearly every time, so waiting
    // to ask for it only added a round trip to every page.
    setPageNumber(String(suggestedPage))
    setAsking({ files, preview: URL.createObjectURL(files[0]) })
  }

  /** A whole script in one file. Nothing to ask: every page carries the
      codes that say which page it is, and the server refuses the
      document outright if they name a different paper. */
  const choosePdf = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = (e.target.files ?? [])[0]
    clearInputs()
    if (!file) return
    setQueue((q) => [...q, { key: `q${nextKey++}`, file, kind: 'document', status: 'waiting' }])
  }

  const enqueue = () => {
    if (!asking) return
    const first = Number(pageNumber)
    if (!Number.isInteger(first) || first < 1) {
      toast.error('Give the page number printed at the bottom of the sheet.')
      return
    }
    setQueue((q) => [
      ...q,
      ...asking.files.map((file, i) => ({
        key: `q${nextKey++}`,
        file,
        kind: 'page' as const,
        preview: i === 0 ? asking.preview : URL.createObjectURL(file),
        pageNumber: first + i,
        status: 'waiting' as const,
      })),
    ])
    setAsking(null)
    setPageNumber('')
  }

  const discardAsked = () => {
    if (asking) URL.revokeObjectURL(asking.preview)
    setAsking(null)
    setPageNumber('')
  }

  const drop = (key: string) =>
    setQueue((q) => {
      const item = q.find((it) => it.key === key)
      if (item?.preview) URL.revokeObjectURL(item.preview)
      return q.filter((it) => it.key !== key)
    })

  // One at a time, in the order they were taken.
  useEffect(() => {
    if (sending.current) return
    const next = queue.find((it) => it.status === 'waiting')
    if (!next) return

    sending.current = true
    setQueue((q) => q.map((it) => (it.key === next.key ? { ...it, status: 'uploading' } : it)))

    void (async () => {
      try {
        const result = await upload.mutateAsync({
          file: next.file,
          // A document is already flat and evenly lit, so it is not
          // treated as a photograph: no straightening, no relighting,
          // and an affine fit rather than a perspective one.
          modality: next.kind === 'document' ? 'scanner' : 'photo',
          submissionId: submissionIdRef.current ?? undefined,
          pageIndexHint: next.pageNumber != null ? next.pageNumber - 1 : undefined,
        })
        submissionIdRef.current = result.submission_id
        setSubmissionId(result.submission_id)
        setQueue((q) => q.filter((it) => it.key !== next.key))
        if (next.preview) URL.revokeObjectURL(next.preview)
      } catch (err) {
        const message = (err as Error).message
        setQueue((q) =>
          q.map((it) => (it.key === next.key ? { ...it, status: 'failed', error: message } : it)),
        )
        toast.error(
          next.kind === 'document' ? `${next.file.name}: ${message}` : `Page ${next.pageNumber}: ${message}`,
        )
      } finally {
        sending.current = false
        setTick((t) => t + 1)
      }
    })()
  }, [queue, tick, upload])

  const submit = async () => {
    try {
      await handIn.mutateAsync()
      toast.success('Handed in')
      navigate(`/courses/${courseId}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const waiting = queue.filter((q) => q.status !== 'failed').length

  return (
    <div className="space-y-5">
      <PageHeader
        title="Your answer"
        back={
          <Link to={`/courses/${courseId}`} className="text-sm text-muted-foreground hover:underline">
            ← Back to the course
          </Link>
        }
        description={
          pages.length > 0
            ? `${pages.length} page${pages.length === 1 ? '' : 's'} ready to hand in` +
              (waiting > 0 ? `, ${waiting} still sending` : '')
            : 'Photograph each page of your answer, then hand it in.'
        }
      />

      <div className="flex flex-wrap gap-2">
        {/* Three ways in, each doing one thing.

            "Take a photo" asks the camera for a picture. On a phone
            that opens the camera; on a desktop the browser ignores the
            request and offers the file picker instead, which is why
            "Upload an image" exists as well — on a desktop it is the
            one that means what it says, and on a phone it reaches the
            gallery rather than the camera.

            None of them are disabled while an upload runs. Waiting for
            the network between pages was the whole complaint. */}
        <Button onClick={() => cameraRef.current?.click()}>Take a photo</Button>
        <Button variant="outline" onClick={() => imageRef.current?.click()}>
          Upload an image
        </Button>
        <Button variant="outline" onClick={() => pdfRef.current?.click()}>
          Upload a PDF
        </Button>
        {waiting > 0 && (
          <StatusPill tone="info">
            <Pending>
              Sending {waiting} item{waiting === 1 ? '' : 's'}
            </Pending>
          </StatusPill>
        )}

        {/* `capture` hands back a single image and can stop a phone
            offering the gallery at all, so the camera gets an input of
            its own. */}
        <input
          ref={cameraRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          onChange={choosePages}
          className="hidden"
        />
        <input
          ref={imageRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={choosePages}
          className="hidden"
        />
        {/* One document, and only a PDF: it is the whole script, so
            there is nothing to number and nothing to combine. */}
        <input
          ref={pdfRef}
          type="file"
          accept="application/pdf"
          onChange={choosePdf}
          className="hidden"
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Photograph or upload one page at a time, or upload a single PDF holding the whole
        script. A PDF's pages sort themselves out from the codes printed on them, so it does
        not ask you anything.
      </p>

      {/* Asked before sending, not after failing. The number is only
          used if the printed codes cannot be read, so a wrong guess on
          a readable page costs nothing. */}
      <Dialog open={!!asking} onOpenChange={(open) => !open && discardAsked()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {(asking?.files.length ?? 0) > 1 ? 'Which page do these start at?' : 'Which page is this?'}
            </DialogTitle>
            <DialogDescription>
              It is printed at the bottom of the sheet. If the codes on the page can be read,
              they are used instead and this is ignored.
            </DialogDescription>
          </DialogHeader>

          {asking && (
            <img
              src={asking.preview}
              alt="The photograph you just took"
              className="max-h-48 w-full rounded-md object-contain"
            />
          )}

          <div className="space-y-2">
            <Label htmlFor="page-number">Page number</Label>
            <Input
              id="page-number"
              value={pageNumber}
              onChange={(e) => setPageNumber(e.target.value)}
              inputMode="numeric"
              autoFocus
              placeholder="e.g. 2"
            />
          </div>

          <DialogFooter>
            <DialogClose render={<Button variant="ghost">Take it again instead</Button>} />
            <Button onClick={enqueue} disabled={!pageNumber.trim()}>
              Add this page
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading && <CardSkeleton rows={3} />}

      {!isLoading && pages.length === 0 && queue.length === 0 && (
        <EmptyState
          title="No pages yet"
          hint="Take a photo of your first page. You can add more, and remove any that came out badly, before handing in."
        />
      )}

      <div className="space-y-4">
        {/* Still on the phone. Shown in the same list as the rest, so a
            page that has been taken is visible whether or not the
            network has caught up with it. */}
        {queue.map((item) => (
          <div key={item.key} className="space-y-2">
            {/* A document has no single picture to show, and its pages
                do not have numbers yet — the server reads those off the
                codes once it opens the file. So it appears by name. */}
            {item.kind === 'document' ? (
              <PaperSurface kind="page" caption="Whole script">
                <div className="px-3 py-4 text-sm">
                  <span className="font-medium">{item.file.name}</span>
                  <span className="ml-2 text-muted-foreground">
                    {Math.round(item.file.size / 1024)} KB
                  </span>
                </div>
              </PaperSurface>
            ) : (
              <PaperSurface kind="student" caption={`Page ${item.pageNumber}`}>
                <img
                  src={item.preview}
                  alt={`Page ${item.pageNumber} of your answer`}
                  className="max-h-[28rem] w-full object-contain opacity-70"
                />
              </PaperSurface>
            )}
            <div className="flex items-center gap-2 px-1">
              {item.status === 'failed' ? (
                <StatusPill tone="danger">{item.error || "Couldn't be sent"}</StatusPill>
              ) : (
                <StatusPill tone="info">
                  <Pending>{item.status === 'uploading' ? 'Sending' : 'Waiting'}</Pending>
                </StatusPill>
              )}
              {item.status === 'failed' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setQueue((q) =>
                      q.map((it) =>
                        it.key === item.key ? { ...it, status: 'waiting', error: undefined } : it,
                      ),
                    )
                  }
                >
                  Try again
                </Button>
              )}
              {item.status !== 'uploading' && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto text-destructive"
                  onClick={() => drop(item.key)}
                >
                  Remove
                </Button>
              )}
            </div>
          </div>
        ))}

        {pages.map((page) => (
          <div key={page.page_index} className="space-y-2">
            {/* The page's own number, not its position in this list. A
                student who photographs page 5 first was shown "Page 1"
                beside the number they had just typed. */}
            <PaperImage
              kind="student"
              path={`/submissions/${submissionId}/images/${page.page_index}`}
              alt={`Page ${page.page_index + 1} of your answer`}
              caption={`Page ${page.page_index + 1}`}
            />
            <div className="flex items-center gap-2 px-1">
              {page.error ? (
                <StatusPill tone="danger">Couldn't be read</StatusPill>
              ) : (
                <StatusPill tone="success">
                  {(page.crops?.length ?? 0)} answer box(es) found
                </StatusPill>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto text-destructive"
                onClick={async () => {
                  try {
                    await removePage.mutateAsync(page.page_index)
                    toast.success('Page removed')
                  } catch (err) {
                    toast.error((err as Error).message)
                  }
                }}
                disabled={removePage.isPending}
              >
                Remove
              </Button>
            </div>
          </div>
        ))}
      </div>

      {pages.length > 0 && (
        <Dialog>
          <DialogTrigger
            render={
              <Button className="w-full sm:w-auto" disabled={waiting > 0}>
                {waiting > 0 ? `Sending ${waiting} page${waiting === 1 ? '' : 's'}…` : 'Hand in my answer'}
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Hand in {pages.length} page{pages.length === 1 ? '' : 's'}?</DialogTitle>
              <DialogDescription>
                Your teacher can mark it once you do. You won't be able to add or remove pages
                afterwards, so check every page of your answer is here first.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="ghost">Not yet</Button>} />
              <Button onClick={submit} disabled={handIn.isPending}>
                {handIn.isPending ? <Pending>Handing in…</Pending> : 'Hand in'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
