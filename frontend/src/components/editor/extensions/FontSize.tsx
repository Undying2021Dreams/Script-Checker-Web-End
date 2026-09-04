import { Mark, mergeAttributes } from '@tiptap/core'

/**
 * FontSize — a plain text mark storing an inline font-size, same pattern
 * as bold/italic. Applied/cleared via the toolbar's size dropdown.
 */
declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    fontSize: {
      setFontSize: (size: string) => ReturnType
      unsetFontSize: () => ReturnType
    }
  }
}

export const FontSize = Mark.create({
  name: 'fontSize',

  addAttributes() {
    return {
      size: {
        default: null,
        parseHTML: (el: HTMLElement) => el.style.fontSize || null,
        renderHTML: (attrs: Record<string, unknown>) =>
          attrs.size ? { style: `font-size: ${attrs.size}` } : {},
      },
    };
  },

  parseHTML() {
    return [{ style: 'font-size', getAttrs: (value: string) => ({ size: value }) }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes), 0];
  },

  addCommands() {
    return {
      setFontSize:
        (size: string) =>
        ({ chain }) =>
          chain().setMark(this.name, { size }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain().unsetMark(this.name).run(),
    };
  },
});

export default FontSize;
