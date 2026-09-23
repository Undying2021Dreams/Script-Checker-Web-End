import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CardSkeleton, PageHeader, Pending } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useMe, useSetAvatar, useUpdateProfile } from '@/lib/queries'

/**
 * A person's own account.
 *
 * Two things are editable and the rest is not, which is the whole
 * design. A name arrives from Entra ID as whatever the institution put
 * in Active Directory — often an initial and a surname — and it appears
 * beside every mark this person gives or receives, so they may correct
 * it. Email and role come from sign-in and from the deployment's
 * teacher list: either would be a way to grant yourself a course.
 */
export function ProfilePage() {
  const { data: me, isLoading } = useMe()
  const update = useUpdateProfile()
  const setAvatar = useSetAvatar()
  const fileRef = useRef<HTMLInputElement>(null)

  const [name, setName] = useState('')
  const [institution, setInstitution] = useState('')

  // Seeded once the account arrives, not on every render, or typing
  // would be overwritten by the copy already on screen.
  useEffect(() => {
    if (!me) return
    setName(me.display_name)
    setInstitution(me.institution ?? '')
  }, [me])

  if (isLoading) return <CardSkeleton rows={4} />
  if (!me) return null

  const dirty = name.trim() !== me.display_name || institution.trim() !== (me.institution ?? '')

  const save = async () => {
    try {
      await update.mutateAsync({ display_name: name.trim(), institution: institution.trim() })
      toast.success('Profile saved')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const pickPicture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (fileRef.current) fileRef.current.value = ''
    if (!file) return
    try {
      await setAvatar.mutateAsync(file)
      toast.success('Picture updated')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Your profile" description="How you appear to everyone else." />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Picture</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4">
          <Avatar userId={me.id} name={me.display_name} hasPicture={me.has_avatar} size={72} />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline" size="sm"
              disabled={setAvatar.isPending}
              onClick={() => fileRef.current?.click()}
            >
              {setAvatar.isPending ? <Pending>Uploading…</Pending> : 'Choose a picture'}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={pickPicture}
              className="hidden"
            />
          </div>
          <p className="w-full text-xs text-muted-foreground">
            Squared and shrunk to 256px when you upload it, so a phone photograph is fine.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
            <p className="text-xs text-muted-foreground">
              This is the name beside every mark you give or receive.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="institution">Institution</Label>
            <Input
              id="institution"
              value={institution}
              onChange={(e) => setInstitution(e.target.value)}
              placeholder="e.g. BUET"
            />
          </div>

          <div className="space-y-2 border-t pt-3 text-sm">
            <p>
              <span className="text-muted-foreground">Email: </span>
              {me.email}
            </p>
            <p>
              <span className="text-muted-foreground">Role: </span>
              {me.role}
            </p>
            <p className="text-xs text-muted-foreground">
              Both come from your Microsoft sign-in and cannot be changed here.
            </p>
          </div>

          <Button onClick={save} disabled={!dirty || update.isPending}>
            {update.isPending ? <Pending>Saving…</Pending> : 'Save changes'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
