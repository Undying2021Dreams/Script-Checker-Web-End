import { useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PaperImage } from '@/components/Paper'
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

/**
 * Where a student assembles a script and hands it in.
 *
 * Uploading straight from a row in a list gave no way to see what had
 * been sent, no way to take a bad page back, and no moment at which the
 * student said "that's my answer". Photographing several pages of
 * handwriting is not one action, so it gets a page of its own.
 *
 * Pages upload as they are added rather than being held until the end.
 * A phone on a patchy connection is the normal case, and losing four
 * photographs because the last one failed would be far worse than
 * uploading them one at a time. What the student controls is what the
 * script contains, and when it is finished.
 */
export function SubmitPage() {
  const { questionId = '' } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()

  const courseId = params.get('course') ?? ''
  const [submissionId, setSubmissionId] = useState<string | null>(params.get('submission'))
  // Held while asking which page an unreadable photograph belongs to.
  const [naming, setNaming] = useState<{ file: File; message: string } | null>(null)
  const [namedPage, setNamedPage] = useState('')

  const cameraRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = useUploadSubmission(questionId)
  const { data, isLoading } = useSubmissionPages(submissionId)
  const removePage = useDeleteSubmissionPage(submissionId ?? '')
  const handIn = useHandInSubmission(submissionId ?? '')

  const pages = data?.pages ?? []

  const send = async (file: File, id: string | undefined, pageIndex?: number) => {
    const result = await upload.mutateAsync({ file, modality: 'photo', submissionId: id, pageIndex })
    setSubmissionId(result.submission_id)
    return result.submission_id
  }

  const addFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length === 0) return

    let id = submissionId ?? undefined
    let done = 0
    try {
      for (const file of files) {
        id = await send(file, id)
        done += 1
      }
      toast.success(files.length === 1 ? 'Page added' : `${files.length} pages added`)
    } catch (err) {
      const message = (err as Error).message
      // The page could not identify itself and nothing is wrong with the
      // photograph as such, so offer the way out the paper provides:
      // read the printed page number and say which one it is.
      if (/which page/i.test(message)) {
        setNaming({ file: files[done], message })
      } else {
        toast.error(
          done > 0 ? `Added ${done} of ${files.length}, then: ${message}` : message,
        )
      }
    } finally {
      if (cameraRef.current) cameraRef.current.value = ''
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const addNamedPage = async () => {
    if (!naming) return
    const n = Number(namedPage)
    if (!Number.isInteger(n) || n < 1) {
      toast.error('Give the page number printed at the bottom of the sheet.')
      return
    }
    try {
      // Printed as "Page 1 of n"; stored from zero.
      await send(naming.file, submissionId ?? undefined, n - 1)
      toast.success(`Added as page ${n}`)
      setNaming(null)
      setNamedPage('')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const submit = async () => {
    try {
      await handIn.mutateAsync()
      toast.success('Handed in')
      navigate(`/courses/${courseId}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

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
            ? `${pages.length} page${pages.length === 1 ? '' : 's'} ready to hand in`
            : 'Photograph each page of your answer, then hand it in.'
        }
      />

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => cameraRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Pending>Adding…</Pending> : 'Take a photo'}
        </Button>
        <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          Choose files
        </Button>

        {/* One photo at a time from the camera; as many as you like from
            the picker. `capture` hands back a single image and can stop
            a phone offering the library at all, so they are separate. */}
        <input
          ref={cameraRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          onChange={addFiles}
          className="hidden"
        />
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          multiple
          onChange={addFiles}
          className="hidden"
        />
      </div>

      {/* The photograph is fine; its printed codes just could not be
          read. The sheet says which page it is, so ask rather than
          refuse outright. */}
      <Dialog open={!!naming} onOpenChange={(open) => !open && setNaming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Which page is this?</DialogTitle>
            <DialogDescription>
              {naming?.message} Look at the bottom of the sheet — it is printed there.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="page-number">Page number</Label>
            <Input
              id="page-number"
              value={namedPage}
              onChange={(e) => setNamedPage(e.target.value)}
              inputMode="numeric"
              placeholder="e.g. 2"
            />
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost">Take it again instead</Button>} />
            <Button onClick={addNamedPage} disabled={upload.isPending || !namedPage.trim()}>
              {upload.isPending ? <Pending>Adding…</Pending> : 'Add this page'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading && <CardSkeleton rows={3} />}

      {!isLoading && pages.length === 0 && (
        <EmptyState
          title="No pages yet"
          hint="Take a photo of your first page. You can add more, and remove any that came out badly, before handing in."
        />
      )}

      <div className="space-y-4">
        {pages.map((page, i) => (
          <div key={page.page_index} className="space-y-2">
            <PaperImage
              kind="student"
              path={`/submissions/${submissionId}/images/${page.page_index}`}
              alt={`Page ${i + 1} of your answer`}
              caption={`Page ${i + 1}`}
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
          <DialogTrigger render={<Button className="w-full sm:w-auto">Hand in my answer</Button>} />
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
