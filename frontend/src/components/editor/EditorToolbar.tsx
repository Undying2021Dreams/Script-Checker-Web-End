import type { Editor } from '@tiptap/react'
import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'

interface Props {
  editor: Editor | null
  isFinalized: boolean
  onInsertImage: () => void
}

export function EditorToolbar({ editor, isFinalized, onInsertImage }: Props) {
  if (!editor) return null

  const Btn = ({
    onClick,
    active,
    title,
    children,
  }: {
    onClick: () => void
    active?: boolean
    title: string
    children: ReactNode
  }) => (
    <Button
      type="button"
      size="sm"
      variant={active ? 'default' : 'outline'}
      // Keep the editor's selection — losing it would apply formatting to
      // nothing once focus moves to the button.
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      disabled={isFinalized}
      title={title}
    >
      {children}
    </Button>
  )

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-1.5 border-b bg-card px-3 py-2">
      <Btn onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive('bold')} title="Bold">
        <span className="font-bold">B</span>
      </Btn>
      <Btn onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive('italic')} title="Italic">
        <span className="italic">i</span>
      </Btn>
      <Btn
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        active={editor.isActive('heading', { level: 2 })}
        title="Heading"
      >
        H
      </Btn>
      <Btn
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        active={editor.isActive('bulletList')}
        title="Bullet list"
      >
        • List
      </Btn>
      <Btn
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        active={editor.isActive('orderedList')}
        title="Numbered list"
      >
        1. List
      </Btn>

      <select
        onChange={(e) => {
          const val = e.target.value
          if (val === 'default') editor.chain().focus().unsetFontSize().run()
          else editor.chain().focus().setFontSize(val).run()
        }}
        defaultValue="default"
        disabled={isFinalized}
        className="rounded-md border bg-transparent px-2 py-1 text-xs"
        title="Font size"
      >
        <option value="default">Size: Normal</option>
        <option value="12px">Small</option>
        <option value="18px">Large</option>
        <option value="22px">X-Large</option>
        <option value="28px">Heading</option>
      </select>

      <Separator orientation="vertical" className="mx-1 h-6" />

      <Btn onClick={() => editor.chain().focus().insertEquation(false).run()} title="Insert inline equation">
        ∑ Inline
      </Btn>
      <Btn onClick={() => editor.chain().focus().insertEquation(true).run()} title="Insert centred equation">
        ∑ Block
      </Btn>
      <Btn onClick={onInsertImage} title="Upload image">
        Image
      </Btn>
      <Btn onClick={() => editor.chain().focus().insertAnswerBox('').run()} title="Insert answer box for students">
        ☐ Answer box
      </Btn>
      <Btn
        onClick={() => editor.chain().focus().insertGroundTruthBox('').run()}
        title="Insert the model answer for this part"
      >
        🎯 Model answer
      </Btn>

      {isFinalized && (
        <Badge variant="secondary" className="ml-auto">
          Finalized — read only
        </Badge>
      )}
    </div>
  )
}

export default EditorToolbar
