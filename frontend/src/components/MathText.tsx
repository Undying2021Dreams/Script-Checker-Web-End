import { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

/**
 * Model prose with the maths typeset.
 *
 * Every LLM in this app writes maths in LaTeX whether asked to or not —
 * it is how the training data writes maths — so feedback arrived on
 * screen reading "substituting gives $2(1)+2=4\neq 5$". Telling the
 * model to stop is the wrong fix: the notation is genuinely the clearest
 * way to say what it means, and a teacher comparing a mark against a
 * script should see it set properly.
 *
 * Both delimiter conventions are accepted because both turn up: $…$ and
 * $$…$$ from the models, \(…\) and \[…\] from anything that has seen the
 * question documents, which use those.
 */

// Display forms first: $$…$$ has to win over $…$, which would otherwise
// match its opening delimiter and swallow the expression.
const SEGMENT = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'math'; value: string; display: boolean }

function parse(text: string): Segment[] {
  const segments: Segment[] = []
  let cursor = 0

  for (const match of text.matchAll(SEGMENT)) {
    const start = match.index ?? 0
    if (start > cursor) segments.push({ kind: 'text', value: text.slice(cursor, start) })

    const [, blockDollar, blockBracket, inlineDollar, inlineParen] = match
    segments.push({
      kind: 'math',
      value: blockDollar ?? blockBracket ?? inlineDollar ?? inlineParen ?? '',
      display: blockDollar !== undefined || blockBracket !== undefined,
    })
    cursor = start + match[0].length
  }

  if (cursor < text.length) segments.push({ kind: 'text', value: text.slice(cursor) })

  // Nothing was delimited, but the whole thing is plainly an equation.
  //
  // A teacher pasting `\sigma(\mathbf{z})_i = \frac{e^{z_i}}{\sum_j
  // e^{z_j}}` into a comment means an equation; they should not have to
  // know that this renderer wants dollars around it, and being shown
  // their own source back is a silly answer in a mathematics marking
  // tool.
  //
  // Deliberately all-or-nothing. Prose with an undelimited fragment in
  // it — "check your \frac{1}{2}" — is left alone, because rendering
  // the sentence as maths would set the English in italic variables and
  // look worse than the source did. Mixed content is what $…$ is for.
  if (segments.length === 1 && segments[0].kind === 'text' && isBareMaths(text)) {
    return [{ kind: 'math', value: text.trim(), display: true }]
  }

  return segments
}

/** Whether a run of text with no delimiters is an equation and nothing
 *  else: it has LaTeX in it, and no ordinary sentence around it. */
function isBareMaths(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed) return false
  // A control sequence, or a superscript/subscript — braced or not,
  // since `x^2` is as much an equation as `x^{2}`.
  if (!/\\[a-zA-Z]+|[\^_](?:\{|[A-Za-z0-9])/.test(trimmed)) return false
  // Three plain words in a row means a sentence, not a formula.
  // `\text{...}` is excluded first so a legitimate label inside an
  // equation doesn't look like prose.
  const withoutLatex = trimmed
    .replace(/\\(?:text|mathrm|mathbf|operatorname)\{[^}]*\}/g, ' ')
    .replace(/\\[a-zA-Z]+/g, ' ')
  return !/[a-zA-Z]{2,}\s+[a-zA-Z]{2,}\s+[a-zA-Z]{2,}/.test(withoutLatex)
}

export function MathText({ text, className }: { text: string; className?: string }) {
  const segments = useMemo(() => parse(text), [text])

  // Models lay their reasoning out over several lines and the breaks
  // carry meaning — a marking scheme is a numbered list. Without this
  // they collapse into one run-on paragraph.
  return (
    <span className={['whitespace-pre-wrap', className].filter(Boolean).join(' ')}>
      {segments.map((segment, i) => {
        if (segment.kind === 'text') return <span key={i}>{segment.value}</span>

        let html: string
        try {
          html = katex.renderToString(segment.value, {
            displayMode: segment.display,
            // A model can emit something that isn't valid LaTeX. Showing
            // the source in red beats throwing away the sentence around
            // it, which is what an exception here would do.
            throwOnError: false,
            strict: false,
            // This text came from a model. `trust` is what lets \href and
            // \htmlClass through, so it stays off.
            trust: false,
          })
        } catch {
          return <span key={i}>{segment.value}</span>
        }

        return <span key={i} dangerouslySetInnerHTML={{ __html: html }} />
      })}
    </span>
  )
}
