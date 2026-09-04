import Placeholder from '@tiptap/extension-placeholder'
import { EditorContent, useEditor } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from 'react'

import EditorToolbar from './EditorToolbar'
import './editor.css'
import AnswerBoxNode from './extensions/AnswerBoxNode'
import AuthedImageNode from './extensions/AuthedImageNode'
import EquationNode from './extensions/EquationNode'
import FontSize from './extensions/FontSize'
import GroundTruthBoxNode from './extensions/GroundTruthBoxNode'
import type { Question, QuestionDocPayload } from '@/lib/types'

/**
 * QuestionEditor — the teacher writes a normal flowing document rather
 * than placing blocks on a fixed canvas. It's shown inside a page-shaped
 * container purely as an affordance; there's no fixed height, so
 * multi-page falls out of CSS page breaks at export time.
 *
 * onDocChange fires (debounced) with the doc plus the answer and model
 * answer boxes indexed out of it, so the backend can persist both without
 * re-parsing ProseMirror server-side.
 */

export interface QuestionEditorHandle {
  applyAnswerBoxPoints: (pointsById: Record<string, number>) => void
}

interface Props {
  question: Question | null
  onDocChange?: (payload: QuestionDocPayload) => void
  onUploadImage?: (file: File, questionId?: string) => Promise<string>
  onEquationFromImage?: (file: File, provider: string, questionId?: string) => Promise<string>
}

function extractPayload(editor: Editor): QuestionDocPayload {
  const answerBoxes: QuestionDocPayload['answer_boxes'] = []
  const groundTruthBoxes: QuestionDocPayload['ground_truth_boxes'] = []

  editor.state.doc.descendants((node) => {
    if (node.type.name === 'answerBox') {
      answerBoxes.push({ id: node.attrs.id, label: node.attrs.label, points: node.attrs.points })
    }
    if (node.type.name === 'groundTruthBox') {
      groundTruthBoxes.push({ id: node.attrs.id, label: node.attrs.label })
    }
  })

  return {
    content: editor.getJSON(),
    answer_boxes: answerBoxes,
    ground_truth_boxes: groundTruthBoxes,
  }
}

export const QuestionEditor = forwardRef<QuestionEditorHandle, Props>(function QuestionEditor(
  { question, onDocChange, onUploadImage, onEquationFromImage },
  ref,
) {
  const isFinalized = question?.state === 'finalized'
  const loadedIdRef = useRef<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const editor = useEditor({
    editable: !isFinalized,
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Placeholder.configure({
        placeholder:
          'Start typing the question… use the toolbar to insert equations, images, answer boxes, or model answers.',
      }),
      AuthedImageNode.configure({ inline: false, HTMLAttributes: { class: 'question-image' } }),
      EquationNode.configure({
        onEquationFromImage: onEquationFromImage
          ? (file: File, provider: string) =>
              onEquationFromImage(file, provider, question?.question_id)
          : null,
      }),
      AnswerBoxNode,
      GroundTruthBoxNode.configure({
        onUploadImage: onUploadImage
          ? (file: File) => onUploadImage(file, question?.question_id)
          : null,
      }),
      FontSize,
    ],
    content: question?.content || '',
    onUpdate: ({ editor }) => {
      if (!onDocChange) return
      clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => onDocChange(extractPayload(editor)), 500)
    },
  })

  // Only reload content when the question itself changes. Without this
  // guard, our own save echoing back would clobber edits made in the
  // meantime.
  useEffect(() => {
    if (!editor || !question) return
    if (loadedIdRef.current === question.question_id) return
    loadedIdRef.current = question.question_id
    editor.commands.setContent(question.content || '', { emitUpdate: false })
    editor.setEditable(!isFinalized)
  }, [editor, question, isFinalized])

  useEffect(() => {
    editor?.setEditable(!isFinalized)
  }, [editor, isFinalized])

  useImperativeHandle(
    ref,
    () => ({
      // Walks the doc for each id rather than trusting positions captured
      // earlier — the doc may have changed since the suggestions were made.
      applyAnswerBoxPoints(pointsById) {
        if (!editor) return
        editor.state.doc.descendants((node, pos) => {
          if (node.type.name === 'answerBox' && pointsById[node.attrs.id] != null) {
            editor
              .chain()
              .command(({ tr }) => {
                tr.setNodeAttribute(pos, 'points', pointsById[node.attrs.id])
                return true
              })
              .run()
          }
        })
      },
    }),
    [editor],
  )

  const handleInsertImage = useCallback(() => {
    if (!editor || isFinalized) return
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        // Falls back to a local blob URL so the editor still works if no
        // upload handler was supplied.
        const url = onUploadImage
          ? await onUploadImage(file, question?.question_id)
          : URL.createObjectURL(file)
        editor.chain().focus().setImage({ src: url, alt: file.name }).run()
      } catch (err) {
        console.error('Image upload failed:', err)
      }
    }
    input.click()
  }, [editor, isFinalized, onUploadImage, question?.question_id])

  if (!editor) return null

  return (
    <div className="overflow-hidden rounded-lg border">
      <EditorToolbar editor={editor} isFinalized={!!isFinalized} onInsertImage={handleInsertImage} />
      <div className="max-h-[70vh] overflow-y-auto bg-muted/40 p-6">
        <div className="doc-page mx-auto bg-white text-black shadow-sm">
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  )
})

export default QuestionEditor
