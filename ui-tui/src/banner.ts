import { mix } from '@phi/shared/color'
import type { ThemeColors } from './theme.js'

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))\]([\s\S]*?)(\[\/\])/g

export function parseRichMarkup(markup: string): Line[] {
  const lines: Line[] = []

  for (const raw of markup.split('\n')) {
    const trimmed = raw.trimEnd()

    if (!trimmed) {
      lines.push(['', ' '])

      continue
    }

    const matches = [...trimmed.matchAll(RICH_RE)]

    if (!matches.length) {
      lines.push(['', trimmed])

      continue
    }

    let cursor = 0

    for (const m of matches) {
      const before = trimmed.slice(cursor, m.index)

      if (before) {
        lines.push(['', before])
      }

      lines.push([m[1]!, m[2]!])
      cursor = m.index! + m[0].length
    }

    if (cursor < trimmed.length) {
      lines.push(['', trimmed.slice(cursor)])
    }
  }

  return lines
}

const LOGO_ART = [
  '██████╗ ██╗  ██╗██╗    █████╗  ██████╗ ███████╗███╗   ██╗████████╗',
  '██╔══██╗██║  ██║██║   ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝',
  '██████╔╝███████║██║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ',
  '██╔═══╝ ██╔══██║██║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ',
  '██║     ██║  ██║██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ',
  '╚═╝     ╚═╝  ╚═╝╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   '
]

const MARK_COVERAGE = [
  '000000000000000000000000000000000000000000000000',
  '000000000000000000000000000000000000000000000000',
  '000000000000000000000277777777764100000000000000',
  '0000000000000000000004ffffffffffffd9400000000000',
  '0000000000000000000004fffffffffffffffe7100000000',
  '0000000000000000000004fffffffffffffffffe60000000',
  '0000000000000258abccbcffff866678acfffffffb100000',
  '000000000028cfffffffffffff4000000016dfffffd20000',
  '000000003affffffffffffffff400000000006effffd2000',
  '00000019ffffffffffffffffff4000000000002cffffd100',
  '000003dffffffeb7544446ffff40000000000001bffff900',
  '00005efffffc5100000004ffff400000000000001dffff40',
  '0004fffffe500000000004ffff4000000000000003ffffb0',
  '002effffb1000000000004ffff4000000000000000affff2',
  '00bffffa00000000000004ffff40000000000000003ffff7',
  '05ffffc000000000000004ffff40000000000000000dfffb',
  '0cffff2000000000000004ffff40000000000000000afffd',
  '3ffff90000000000000004ffff400000000000000008fffe',
  '8ffff20000000000000004ffff400000000000000008ffff',
  'bfffd00000000000000004ffff40000000000000000afffe',
  'efffa00000000000000004ffff40000000000000000dfffb',
  'ffff800000000000000004ffff40000000000000002ffff8',
  'efff800000000000000004ffff40000000000000009ffff3',
  'dfffa00000000000000004ffff4000000000000002ffffc0',
  'bfffd00000000000000004ffff400000000000000cffff50',
  '7ffff30000000000000004ffff40000000000000affffb00',
  '2ffffa0000000000000004ffff4000000000001bffffe200',
  '0bffff3000000000000004ffff400000000005efffff4000',
  '04ffffd100000000000004ffff4000000015cfffffe50000',
  '009ffffb10000000000004ffff6444457beffffffd300000',
  '001dffffc2000000000004ffffffffffffffffff91000000',
  '0002dffffe600000000004ffffffffffffffffa300000000',
  '00002dfffffd6100000004fffffffffffffc820000000000',
  '000001bfffffffca876668ffffcbccba8520000000000000',
  '00000006efffffffffffffffff4000000000000000000000',
  '0000000017efffffffffffffff4000000000000000000000',
  '0000000000049dffffffffffff4000000000000000000000',
  '000000000000001467777777772000000000000000000000',
  '000000000000000000000000000000000000000000000000',
  '000000000000000000000000000000000000000000000000'
]

const markCoverageRows = Array.from({ length: MARK_COVERAGE.length / 2 }, (_, row) =>
  Array.from(MARK_COVERAGE[row * 2]!, (value, column) => [
    parseInt(value, 16),
    parseInt(MARK_COVERAGE[row * 2 + 1]![column]!, 16)
  ] as const)
)

const MARK_ART = markCoverageRows.map(row =>
  row.map(([top, bottom]) => top >= 8 ? bottom >= 8 ? '█' : '▀' : bottom >= 8 ? '▄' : ' ').join('')
)

const LOGO_GRADIENT = [0, 0, 1, 1, 2, 2] as const

export interface MarkRun {
  text: string
  color?: string
  backgroundColor?: string
}

export function markPixels(colors: ThemeColors, background?: string): MarkRun[][] | undefined {
  if (!background) return undefined

  const edgeColor = mix(background, colors.primary, 0.5)
  const coverage = (value: number) => value <= 4 ? 0 : value >= 11 ? 2 : 1
  const palette = [background, edgeColor, colors.primary] as const

  return markCoverageRows.map(row => {
    const runs: MarkRun[] = []

    for (const [topSample, bottomSample] of row) {
      const top = coverage(topSample)
      const bottom = coverage(bottomSample)
      const topColor = palette[top]
      const bottomColor = palette[bottom]
      const cell: MarkRun = !top && !bottom
        ? { text: ' ' }
        : top === bottom
          ? { text: '█', color: topColor, backgroundColor: topColor }
          : !bottom
            ? { text: '▀', color: topColor }
            : !top
              ? { text: '▄', color: bottomColor }
              : top > bottom
                ? { text: '▀', color: topColor, backgroundColor: bottomColor }
                : { text: '▄', color: bottomColor, backgroundColor: topColor }
      const previous = runs.at(-1)

      if (previous && previous.color === cell.color && previous.backgroundColor === cell.backgroundColor) {
        previous.text += cell.text
      } else {
        runs.push(cell)
      }
    }

    return runs
  })
}

const colorize = (art: string[], gradient: readonly number[], c: ThemeColors): Line[] => {
  const p = [c.primary, c.accent, c.border, c.muted]

  return art.map((text, i) => [p[gradient[i]!] ?? c.muted, text])
}

export const LOGO_WIDTH = Math.max(...LOGO_ART.map(line => line.length))
export const MARK_WIDTH = Math.max(...MARK_ART.map(line => line.length))

export const logo = (c: ThemeColors, customLogo?: string): Line[] =>
  customLogo ? parseRichMarkup(customLogo) : colorize(LOGO_ART, LOGO_GRADIENT, c)

export const mark = (c: ThemeColors, customHero?: string): Line[] =>
  customHero ? parseRichMarkup(customHero) : MARK_ART.map(text => [c.primary, text])

export const artWidth = (lines: Line[]) => lines.reduce((m, [, t]) => Math.max(m, t.length), 0)

type Line = [string, string]
