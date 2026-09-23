import { useEffect, useState } from 'react'
import Placeholder from '@tiptap/extension-placeholder'
import StarterKit from '@tiptap/starter-kit'
import { EditorContent, useEditor, type Editor, type JSONContent } from '@tiptap/react'

import { EquationNode } from '@/components/editor/extensions/EquationNode'
import { MathText } from '@/components/MathText'
import { Button } from '@/components/ui/button'
import '@/components/editor/editor.css'

/**
 * Where a teacher writes the comment a student will read.
 *
 * The same editor the paper itself is written in, less the parts only a
 * paper needs — no answer boxes, no model answers, no page layout. What
 * it keeps is the part that matters here: equations, set as you write
 * them.
 *
 * There is no preview any more, and deliberately. A preview exists to
 * tell you what your source will turn into; when the equation is
 * already typeset in front of you there is nothing left to preview, and
 * a second copy of the comment underneath the first was just something
 * else to read.
 *
 * Saved twice over — as this document, and flattened to text with the
 * equations written back as $…$. The flattening is the server's job, so
 * the two cannot drift apart. Anything that only wants the words reads
 * that, a student on an older client included.
 */

const EXTENSIONS = [
  StarterKit.configure({ heading: { levels: [3] } }),
  // Images are the one thing left out. They would have to be stored
  // against the paper, which is the answer key, and then served to
  // students from there — a different access question than this change.
  EquationNode.configure({ onEquationFromImage: null }),
]

function Toolbar({ editor }: { editor: Editor }) {
  const btn = (active: boolean) => `h-7 px-2 text-xs ${active ? 'bg-muted font-semibold' : ''}`

  return (
    <div className="flex flex-wrap gap-1 border-b bg-card px-2 py-1.5">
      <Button
        type="button" variant="ghost" size="sm" title="Bold"
        className={`${btn(editor.isActive('bold'))} font-bold`}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        B
      </Button>
      <Button
        type="button" variant="ghost" size="sm" title="Italic"
        className={`${btn(editor.isActive('italic'))} italic`}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        I
      </Button>
      <Button
        type="button" variant="ghost" size="sm" title="Bulleted list"
        className={btn(editor.isActive('bulletList'))}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        • List
      </Button>
      <Button
        type="button" variant="ghost" size="sm" title="Numbered list"
        className={btn(editor.isActive('orderedList'))}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        1. List
      </Button>
      <Button
        type="button" variant="ghost" size="sm" title="An equation inside the sentence"
        className={btn(false)}
        onClick={() => editor.chain().focus().insertEquation(false).run()}
      >
        Inline equation
      </Button>
      <Button
        type="button" variant="ghost" size="sm" title="An equation on its own line"
        className={btn(false)}
        onClick={() => editor.chain().focus().insertEquation(true).run()}
      >
        Block equation
      </Button>
    </div>
  )
}

export function FeedbackEditor({
  value,
  onChange,
  modelFeedback,
  savedFeedback,
  provider,
  disabled,
}: {
  /** The teacher's comment as a document, if they have written one. */
  value: JSONContent | null
  onChange: (doc: JSONContent | null) => void
  modelFeedback?: string | null
  savedFeedback?: string | null
  provider?: string | null
  disabled?: boolean
}) {
  const [showHistory, setShowHistory] = useState(false)

  const editor = useEditor({
    editable: !disabled,
    extensions: [
      ...EXTENSIONS,
      Placeholder.configure({ placeholder: 'What should the student know about this answer?' }),
    ],
    content: value ?? '',
    onUpdate: ({ editor }) => {
      // An emptied editor still holds a paragraph. Reporting that as a
      // comment would mark the box as decided by a teacher who wrote
      // nothing on it, and freeze it from ever being marked again.
      onChange(editor.getText().trim() === '' ? null : editor.getJSON())
    },
  })

  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [editor, disabled])

  if (!editor) return null

  const hasHistory = !!(modelFeedback || savedFeedback)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label className="text-xs text-muted-foreground">Your feedback (optional)</label>
        {hasHistory && (
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {showHistory ? 'Hide what was written before' : 'What was written before'}
          </button>
        )}
      </div>

      {/* Replacing a comment without being able to read the one you are
          replacing is how a teacher ends up repeating the model, or
          contradicting themselves from last week. */}
      {showHistory && (
        <div className="space-y-2 rounded-lg border bg-muted/40 p-2 text-sm">
          {savedFeedback && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Yours, as last saved
              </p>
              <MathText text={savedFeedback} />
            </div>
          )}
          {modelFeedback && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                The model's{provider ? ` (${provider})` : ''}
              </p>
              <MathText text={modelFeedback} />
            </div>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-md border">
        {!disabled && <Toolbar editor={editor} />}
        <EditorContent editor={editor} className="feedback-doc px-3 py-2 text-sm" />
      </div>
    </div>
  )
}

/**
 * The same comment, read-only — what the student opens.
 *
 * Rendered through the editor rather than a renderer of its own, so
 * what they see is what was written. A second implementation is a
 * second thing to keep in step, and the one that drifts is always the
 * one nobody is looking at.
 */
export function FeedbackView({ doc }: { doc: JSONContent }) {
  const editor = useEditor({ editable: false, extensions: EXTENSIONS, content: doc }, [doc])
  if (!editor) return null
  return <EditorContent editor={editor} className="feedback-doc text-sm" />
}
