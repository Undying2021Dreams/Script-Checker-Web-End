import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import type { NodeViewProps } from '@tiptap/react'
import { useState } from 'react'

export type UploadImage = (file: File) => Promise<string>

function uuid() {
  return 'gt_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function GroundTruthBoxView({ node, updateAttributes, editor, extension, getPos }: NodeViewProps) {
  const { label, id } = node.attrs;
  const canEdit = editor.isEditable;
  const [editingLabel, setEditingLabel] = useState(false);

  const handleInsertImage = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const uploadFn = extension.options.onUploadImage;
        const url = uploadFn ? await uploadFn(file) : URL.createObjectURL(file);
        // Insert at the end of this box's own content, not wherever the
        // main document's selection happens to be — the toolbar's global
        // image button can't target a specific ground truth box.
        const pos = getPos();
        if (typeof pos !== 'number') return;
        const endPos = pos + node.nodeSize - 1;
        editor.chain().focus().insertContentAt(endPos, {
          type: 'image',
          attrs: { src: url, alt: file.name },
        }).run();
      } catch (err) {
        console.error('Ground truth image upload failed:', err);
      }
    };
    input.click();
  };

  return (
    <NodeViewWrapper
      className="ground-truth-box-node"
      style={{
        display: 'block',
        margin: '14px 0',
        border: '2px dashed #22c55e',
        background: 'rgba(34,197,94,0.05)',
        borderRadius: 8,
        minHeight: 90,
        width: '100%',
        boxSizing: 'border-box',
        position: 'relative',
        padding: '10px 12px 16px',
      }}
    >
      <div
        contentEditable={false}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 4,
          flexWrap: 'wrap',
          userSelect: 'none',
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: '#22c55e',
            background: '#fff',
            border: '1px solid #22c55e',
            borderRadius: 4,
            padding: '2px 6px',
            letterSpacing: 0.3,
          }}
        >
          🎯 GROUND TRUTH
        </span>

        {editingLabel && canEdit ? (
          <input
            autoFocus
            defaultValue={label}
            onBlur={(e) => { updateAttributes({ label: e.target.value }); setEditingLabel(false); }}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            style={{ fontSize: 12, border: '1px solid #ddd', borderRadius: 4, padding: '2px 6px', width: 120 }}
          />
        ) : (
          <span
            onClick={() => canEdit && setEditingLabel(true)}
            style={{ fontSize: 12, fontWeight: 600, cursor: canEdit ? 'text' : 'default' }}
            title={canEdit ? 'Click to rename' : undefined}
          >
            {label || 'Sample Solution'}
          </span>
        )}

        <span style={{ fontSize: 11, color: '#888', fontFamily: 'monospace' }}>
          id: {id?.slice(0, 14)}…
        </span>

        {canEdit && (
          <button
            type="button"
            onClick={handleInsertImage}
            title="Insert image into this sample solution"
            style={{
              fontSize: 11,
              border: '1px solid #22c55e',
              color: '#22c55e',
              background: '#fff',
              borderRadius: 4,
              padding: '2px 6px',
              cursor: 'pointer',
              marginLeft: 'auto',
            }}
          >
            🖼 Image
          </button>
        )}
      </div>

      <NodeViewContent className="gt-content" style={{ paddingTop: 4 }} />
    </NodeViewWrapper>
  );
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    groundTruthBox: {
      insertGroundTruthBox: (label?: string) => ReturnType
    }
  }
}

export const GroundTruthBoxNode = Node.create({
  name: 'groundTruthBox',
  group: 'block',
  content: 'block+',
  selectable: true,
  draggable: true,

  addOptions() {
    return {
      // (file: File) => Promise<url> — supplied by QuestionEditor via
      // .configure() so this node view can upload images the same way
      // the main toolbar does, without owning any upload/API logic itself.
      onUploadImage: null as UploadImage | null,
    };
  },

  addAttributes() {
    return {
      id: { default: null },
      label: { default: 'Sample Solution' },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-ground-truth-box]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-ground-truth-box': '' })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(GroundTruthBoxView);
  },

  addKeyboardShortcuts() {
    return {
      Enter: ({ editor }) => {
        const { $from } = editor.state.selection;
        let insideGT = false;
        for (let d = $from.depth; d > 0; d--) {
          if ($from.node(d).type.name === 'groundTruthBox') {
            insideGT = true;
            break;
          }
        }
        if (!insideGT) return false;

        const parent = $from.parent;
        if (parent.type.name === 'paragraph' && parent.content.size === 0) {
          return true;
        }
        return false;
      },
    };
  },

  addCommands() {
    return {
      insertGroundTruthBox:
        (label = 'Sample Solution') =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { id: uuid(), label },
            content: [{ type: 'paragraph' }],
          }),
    };
  },
});

export default GroundTruthBoxNode;
