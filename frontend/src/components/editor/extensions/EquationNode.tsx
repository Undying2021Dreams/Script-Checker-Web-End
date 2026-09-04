import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import type { NodeViewProps } from '@tiptap/react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'

/**
 * EquationNode — inline or block LaTeX.
 *
 * Stored as { type: 'equation', attrs: { latex, display } }, where
 * display:true is a centered block equation and display:false flows with
 * the text.
 *
 * Clicking a rendered equation opens an editor with a live KaTeX preview
 * and an "extract from an image" path that fills the same textarea via an
 * LLM. Typing and AI extraction share one editing surface deliberately:
 * nothing is inserted without the teacher seeing it rendered first.
 */

const PROVIDERS = [
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude' },
  { value: 'self_hosted', label: 'Self-hosted (open source)' },
]

export type EquationFromImage = (file: File, provider: string) => Promise<string>

function EquationPreview({ latex, display }: { latex: string; display: boolean }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!ref.current) return
    try {
      katex.render(latex || '\\text{empty}', ref.current, {
        throwOnError: true,
        displayMode: display,
      })
      setError(false)
    } catch {
      ref.current.textContent = latex || '(empty equation)'
      setError(true)
    }
  }, [latex, display])

  return (
    <div
      className={`flex min-h-14 items-center overflow-x-auto rounded-md border bg-white px-4 py-5 text-black ${
        error ? 'border-destructive' : ''
      } ${display ? 'justify-center' : 'justify-start'}`}
    >
      <span ref={ref} />
    </div>
  )
}

function EquationEditDialog({
  initialLatex,
  initialDisplay,
  onEquationFromImage,
  onConfirm,
  onCancel,
}: {
  initialLatex: string
  initialDisplay: boolean
  onEquationFromImage?: EquationFromImage | null
  onConfirm: (latex: string, display: boolean) => void
  onCancel: () => void
}) {
  const [latex, setLatex] = useState(initialLatex || '')
  const [display, setDisplay] = useState(!!initialDisplay)
  const [provider, setProvider] = useState('self_hosted')
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleImagePick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !onEquationFromImage) return
    setExtracting(true)
    setExtractError(null)
    try {
      setLatex(await onEquationFromImage(file, provider))
    } catch (err) {
      setExtractError((err as Error).message || 'Extraction failed')
    } finally {
      setExtracting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Equation</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="flex gap-4 text-sm">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" checked={!display} onChange={() => setDisplay(false)} />
              Inline
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" checked={display} onChange={() => setDisplay(true)} />
              Block (own centred line)
            </label>
          </div>

          <textarea
            autoFocus
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            placeholder="e.g. x^2 + y^2 = r^2"
            rows={3}
            className="w-full resize-y rounded-md border bg-transparent px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />

          <Label>Preview</Label>
          <EquationPreview latex={latex} display={display} />

          {onEquationFromImage && (
            <div className="flex items-center gap-2 border-t pt-3">
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="rounded-md border bg-transparent px-2 py-1 text-xs"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
                disabled={extracting}
              >
                {extracting ? 'Reading…' : 'From image'}
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={handleImagePick}
                className="hidden"
              />
            </div>
          )}

          {extractError && <p className="text-sm text-destructive">{extractError}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(latex, display)}>Insert</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EquationView({ node, updateAttributes, editor, selected, extension, getPos }: NodeViewProps) {
  const { latex, display } = node.attrs
  const [editing, setEditing] = useState(!latex) // auto-open on insert
  const [error, setError] = useState(false)
  const renderRef = useRef<HTMLSpanElement>(null)
  const canEdit = editor.isEditable

  useEffect(() => {
    if (editing || !renderRef.current) return
    try {
      katex.render(latex || '\\text{empty}', renderRef.current, {
        throwOnError: true,
        displayMode: display,
      })
      setError(false)
    } catch {
      renderRef.current.textContent = latex || '(empty equation)'
      setError(true)
    }
  }, [latex, display, editing])

  const handleCancel = () => {
    // An equation inserted but never given any LaTeX has nothing worth
    // keeping. Delete this exact node by its own position rather than
    // deleteNode('equation'), which acts on whatever equation the
    // selection happens to be on — unreliable when Cancel is clicked in a
    // dialog rather than on the node itself.
    if (!latex) {
      const pos = getPos()
      if (typeof pos === 'number') {
        editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run()
      }
      return
    }
    setEditing(false)
  }

  return (
    <>
      <NodeViewWrapper
        as={display ? 'div' : 'span'}
        className="eq-node"
        style={{
          display: display ? 'block' : 'inline-block',
          textAlign: display ? 'center' : 'left',
          margin: display ? '8px 0' : 0,
          padding: '2px 4px',
          borderRadius: 4,
          border: error
            ? '1px solid #ef4444'
            : selected
              ? '1px solid #a855f7'
              : '1px solid transparent',
          cursor: canEdit ? 'text' : 'default',
        }}
        onClick={() => canEdit && setEditing(true)}
        title={canEdit ? 'Click to edit' : undefined}
      >
        <span ref={renderRef} />
      </NodeViewWrapper>

      {editing && canEdit && (
        <EquationEditDialog
          initialLatex={latex}
          initialDisplay={display}
          onEquationFromImage={extension.options.onEquationFromImage}
          onConfirm={(newLatex, newDisplay) => {
            updateAttributes({ latex: newLatex, display: newDisplay })
            setEditing(false)
          }}
          onCancel={handleCancel}
        />
      )}
    </>
  )
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    equation: {
      insertEquation: (display?: boolean) => ReturnType
    }
  }
}

export const EquationNode = Node.create({
  name: 'equation',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return {
      onEquationFromImage: null as EquationFromImage | null,
    }
  },

  addAttributes() {
    return {
      latex: { default: '' },
      display: { default: false },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-equation]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { 'data-equation': '' })]
  },

  addNodeView() {
    return ReactNodeViewRenderer(EquationView)
  },

  addCommands() {
    return {
      insertEquation:
        (display = false) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { latex: '', display } }),
    }
  },
})

export default EquationNode
