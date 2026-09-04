import Image from '@tiptap/extension-image'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import type { NodeViewProps } from '@tiptap/react'

import { AuthedImage, toApiPath } from '@/components/AuthedImage'

/**
 * The stock Image extension, but displayed through AuthedImage.
 *
 * Question figures are served from an endpoint that requires a bearer
 * token, which a plain <img src> can't supply — the teacher would upload
 * a figure and see a broken image. This only changes how the node is
 * *displayed*: the src stored in the document is untouched, so what gets
 * saved, exported and inlined server-side at render time is unaffected.
 */

function ImageView({ node }: NodeViewProps) {
  const src: string = node.attrs.src || ''
  const alt: string = node.attrs.alt || ''
  const apiPath = toApiPath(src)

  return (
    <NodeViewWrapper as="div" className="question-image-wrapper">
      {apiPath ? (
        <AuthedImage path={apiPath} alt={alt} className="question-image" />
      ) : (
        // Blob URLs (an upload still in flight) and genuinely external
        // images need no token and load directly.
        <img src={src} alt={alt} className="question-image" />
      )}
    </NodeViewWrapper>
  )
}

export const AuthedImageNode = Image.extend({
  addNodeView() {
    return ReactNodeViewRenderer(ImageView)
  },
})

export default AuthedImageNode
