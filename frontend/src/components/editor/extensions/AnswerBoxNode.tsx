import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import type { NodeViewProps } from '@tiptap/react'
import { useState } from 'react'

/**
 * AnswerBoxNode — a tagged placeholder marking where the student writes.
 *
 * Its job is to carry the metadata the extraction and grading pipeline
 * needs in order to know which sub-part a cropped answer region belongs
 * to: { id, label, points, widthPercent, minHeight }.
 *
 * `id` is generated on insert and is deliberately stable: the same value
 * threads through editor node -> answer_boxes row -> QR payload printed
 * on the page -> extraction manifest -> the mark. Regenerating it would
 * orphan every scan of an already-printed paper.
 */

function uuid() {
  return 'ab_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

function AnswerBoxView({ node, updateAttributes, editor }: NodeViewProps) {
  const { label, points, id, widthPercent, minHeight } = node.attrs
  const canEdit = editor.isEditable
  const [editingLabel, setEditingLabel] = useState(false)

  return (
    <NodeViewWrapper
      className="answer-box-node"
      style={{
        display: 'block',
        margin: '14px 0',
        border: '2px dashed #f97316',
        background: 'rgba(249,115,22,0.05)',
        borderRadius: 8,
        minHeight,
        width: `${widthPercent}%`,
        boxSizing: 'border-box',
        position: 'relative',
        padding: '10px 12px 16px',
      }}
      contentEditable={false}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: '#f97316',
            background: '#fff',
            border: '1px solid #f97316',
            borderRadius: 4,
            padding: '2px 6px',
            letterSpacing: 0.3,
          }}
        >
          ☐ ANSWER
        </span>

        {editingLabel && canEdit ? (
          <input
            autoFocus
            defaultValue={label}
            onBlur={(e) => {
              updateAttributes({ label: e.target.value })
              setEditingLabel(false)
            }}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            style={{ fontSize: 12, border: '1px solid #ddd', borderRadius: 4, padding: '2px 6px', width: 70 }}
          />
        ) : (
          <span
            onClick={() => canEdit && setEditingLabel(true)}
            style={{ fontSize: 12, fontWeight: 600, cursor: canEdit ? 'text' : 'default' }}
            title={canEdit ? 'Click to rename (e.g. 1a, 2b)' : undefined}
          >
            {label || 'unlabeled'}
          </span>
        )}

        {/* Marks are required, and shown as missing until set.
            They used to be read out of the marking scheme at finalize,
            which got real schemes wrong in ways nobody saw until a mark
            had been given — a wrong total looks exactly like a right
            one. The teacher states it; the scheme only suggests. */}
        <span
          style={{
            fontSize: 11,
            color: points == null ? '#b42318' : '#888',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          marks:
          {canEdit ? (
            <input
              type="number"
              min={0}
              value={points ?? ''}
              placeholder="—"
              onChange={(e) => {
                const raw = e.target.value.trim()
                // Empty means "not decided yet", which is a different
                // thing from a part worth nothing.
                updateAttributes({ points: raw === '' ? null : Number(raw) })
              }}
              style={{
                width: 48,
                fontSize: 11,
                border: `1px solid ${points == null ? '#f0a5a0' : '#ddd'}`,
                borderRadius: 4,
                padding: '1px 4px',
              }}
            />
          ) : (
            <strong>{points ?? '—'}</strong>
          )}
          {points == null && <span>required</span>}
        </span>

        {canEdit && (
          <>
            <span style={{ fontSize: 11, color: '#888', display: 'flex', alignItems: 'center', gap: 4 }}>
              width:
              <select
                value={widthPercent}
                onChange={(e) => updateAttributes({ widthPercent: Number(e.target.value) })}
                style={{ fontSize: 11, border: '1px solid #ddd', borderRadius: 4, padding: '1px 2px' }}
              >
                <option value={25}>25%</option>
                <option value={50}>50%</option>
                <option value={75}>75%</option>
                <option value={100}>100%</option>
              </select>
            </span>

            <span
              style={{
                fontSize: 11,
                color: '#888',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                marginLeft: 'auto',
              }}
            >
              height:
              <button
                type="button"
                onClick={() => updateAttributes({ minHeight: Math.max(60, minHeight - 40) })}
                style={{ fontSize: 11, width: 20, cursor: 'pointer' }}
              >
                −
              </button>
              <input
                type="number"
                min={60}
                value={minHeight}
                onChange={(e) =>
                  updateAttributes({ minHeight: Math.max(60, Number(e.target.value) || 60) })
                }
                style={{
                  width: 50,
                  fontSize: 11,
                  border: '1px solid #ddd',
                  borderRadius: 4,
                  padding: '1px 4px',
                  textAlign: 'center',
                }}
              />
              px
              <button
                type="button"
                onClick={() => updateAttributes({ minHeight: minHeight + 40 })}
                style={{ fontSize: 11, width: 20, cursor: 'pointer' }}
              >
                +
              </button>
            </span>
          </>
        )}
      </div>

      <div style={{ fontSize: 11, color: '#999', fontFamily: 'monospace' }}>
        id: {id?.slice(0, 14)}…
      </div>
    </NodeViewWrapper>
  )
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    answerBox: {
      insertAnswerBox: (label?: string) => ReturnType
    }
  }
}

export const AnswerBoxNode = Node.create({
  name: 'answerBox',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      id: { default: null },
      label: { default: '' },
      // Null, not 1. A new box has no marks until the teacher says
      // what it is worth — defaulting to one is how a ten-mark scheme
      // came to be marked out of one.
      points: { default: null },
      widthPercent: { default: 100 }, // 25 | 50 | 75 | 100
      minHeight: { default: 90 },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-answer-box]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-answer-box': '' })]
  },

  addNodeView() {
    return ReactNodeViewRenderer(AnswerBoxView)
  },

  addCommands() {
    return {
      insertAnswerBox:
        (label = '') =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { id: uuid(), label, points: null },
          }),
    }
  },
})

export default AnswerBoxNode
