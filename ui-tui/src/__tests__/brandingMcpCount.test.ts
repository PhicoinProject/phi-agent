import { PassThrough } from 'stream'

import * as ink from '@phi/ink'
import { renderSync } from '@phi/ink'
import React from 'react'
import { describe, expect, it, vi } from 'vitest'

import { mark, markPixels, MARK_WIDTH } from '../banner.js'
import { SessionPanel } from '../components/branding.js'
import { messages } from '../i18n/runtime.js'
import { DEFAULT_THEME } from '../theme.js'
import type { McpServerStatus, SessionInfo } from '../types.js'

// Invariant under test: the TUI banner's MCP headline counts *connected*
// servers, never configured-but-disabled ones. This mirrors the classic CLI
// banner (`mcp_connected = sum(1 for s in mcp_status if s["connected"])` in
// phi_cli/banner.py) and the "connected" label on the MCP collapse toggle.
//
// Regression: branding.tsx used the raw `info.mcp_servers.length`, so a
// disabled `linear` server alongside a connected `nous-support` server made
// the TUI report "2 MCP" while the classic CLI correctly reported "1 MCP".

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const makeStreams = (columns = 100) => {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()

  Object.assign(stdout, { columns, isTTY: false, rows: 40 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })

  let captured = ''
  stdout.on('data', chunk => {
    captured += chunk.toString()
  })

  return { capture: () => captured, stderr, stdin, stdout }
}

const mcp = (over: Partial<McpServerStatus> & Pick<McpServerStatus, 'name'>): McpServerStatus => ({
  connected: false,
  tools: 0,
  transport: 'http',
  ...over
})

const baseInfo = (mcp_servers: McpServerStatus[]): SessionInfo => ({
  mcp_servers,
  model: 'test-model',
  skills: { core: ['a', 'b'] },
  tools: { file: ['read_file', 'write_file'] }
})

async function renderFooter(info: SessionInfo, columns = 100, background?: string): Promise<string> {
  const streams = makeStreams(columns)
  const stdout = vi.spyOn(process, 'stdout', 'get').mockReturnValue(streams.stdout as NodeJS.WriteStream)
  const backgroundColor = vi.spyOn(ink, 'terminalBackgroundHex').mockReturnValue(background)

  const instance = renderSync(React.createElement(SessionPanel, { info, sid: 'test', t: DEFAULT_THEME }), {
    patchConsole: false,
    stderr: streams.stderr as NodeJS.WriteStream,
    stdin: streams.stdin as NodeJS.ReadStream,
    stdout: streams.stdout as NodeJS.WriteStream
  })

  try {
    await delay(20)

    // Strip ANSI so we can assert on the rendered text content.
    // eslint-disable-next-line no-control-regex
    return streams.capture().replace(/\u001b\[[0-9;]*m/g, '')
  } finally {
    instance.unmount()
    instance.cleanup()
    stdout.mockRestore()
    backgroundColor.mockRestore()
  }
}

describe('branding MCP headline count', () => {
  it('counts only connected servers, not configured-but-disabled ones', async () => {
    const frame = await renderFooter(
      baseInfo([
        mcp({ connected: true, name: 'nous-support', status: 'connected', tools: 6 }),
        mcp({ connected: false, disabled: true, name: 'linear', status: 'disabled' })
      ])
    )

    // One connected server → "1 MCP", never "2 MCP".
    expect(frame).toContain(messages().chatBits.branding.mcpSummary(1))
    expect(frame).not.toContain(messages().chatBits.branding.mcpSummary(2))
  })

  it('drops the MCP segment entirely when no server is connected', async () => {
    const frame = await renderFooter(
      baseInfo([mcp({ connected: false, disabled: true, name: 'linear', status: 'disabled' })])
    )

    // Matches the classic CLI, which only appends "· N MCP" when N > 0.
    expect(frame).not.toContain('MCP servers')
    expect(frame).not.toMatch(/\d MCP\b/)
  })
})

describe('session banner layout', () => {
  const info: SessionInfo = {
    ...baseInfo([]),
    cwd: '/workspace',
    version: '0.1.1',
    skills: {
      core: ['a', 'b'],
      development: ['linting', 'testing'],
      writing: ['notes']
    },
    tools: {
      browser: ['browser_vault_enter_code', 'browser_vault_fill', 'browser_vault_list'],
      code_execution: ['execute_code'],
      delegation: ['delegate_task'],
      file: ['read_file', 'write_file'],
      search: ['web_search'],
      terminal: ['terminal']
    }
  }

  it.each([undefined, '#031117', '#f7f9fb'])(
    'keeps the hero and metadata aligned with background %s', async background => {
    const frame = await renderFooter(info, 150, background)
    const lines = frame.split('\n')
    const labelColumns = ['Model:', 'Workspace:', 'Session:', 'Available Tools', 'Available Skills'].map(label => {
      const line = lines.find(row => row.includes(label))!

      expect(line).toBeDefined()

      return line.indexOf(label)
    })
    const artColumn = Math.min(...lines.filter(row => row.includes('█')).map(row => row.indexOf('█')))

    expect(new Set(labelColumns.slice(0, 3)).size).toBe(1)
    expect(labelColumns.every(column => column > artColumn + 40), frame).toBe(true)
    expect(frame).toContain('9 tools')
    expect(frame).toContain('5 skills')
    expect(frame).toContain('execute_code')
    expect(frame).toContain('delegate_task')
    expect(frame).toContain('core: a, b')
    expect(frame).toContain('development: linting, testing')
    expect(frame).toContain('more toolsets')
    expect(frame).toContain('more categories')
    expect(frame).not.toContain('browser_vault_list')
    expect(frame).not.toContain('terminal:')
    expect(frame).not.toContain('writing:')
    expect(lines.findIndex(row => row.includes('9 tools'))).toBe(
      lines.findIndex(row => row.includes('Phi Agent v')) + mark(DEFAULT_THEME.color).length - 1
    )
  })

  it('retains the version and session metadata without a clipped hero on narrow terminals', async () => {
    const frame = await renderFooter(info, 60)

    for (const text of ['v0.1.1', 'Model:', 'test-model', 'Workspace:', '/workspace', 'Session:', 'test']) {
      expect(frame).toContain(text)
    }

    expect(frame).not.toContain('█')
  })
})

describe('PHI mark sampling', () => {
  it('keeps the staggered halves rotationally balanced without changing the canvas width', () => {
    const lines = mark(DEFAULT_THEME.color).map(([, text]) => text)
    const rotateGlyph = (glyph: string) => glyph === '▀' ? '▄' : glyph === '▄' ? '▀' : glyph
    const rotated = [...lines].reverse().map(line => Array.from(line).reverse().map(rotateGlyph).join(''))

    expect(lines).toEqual(rotated)
    expect(lines.every(line => line.length === MARK_WIDTH)).toBe(true)
    expect(lines.some(line => line !== Array.from(line).reverse().join(''))).toBe(true)
  })

  it('blends sampled edges but leaves empty cells transparent and custom art untouched', () => {
    const background = '#031117'
    const rows = markPixels(DEFAULT_THEME.color, background)!
    const palette = [DEFAULT_THEME.color.primary, DEFAULT_THEME.color.accent, DEFAULT_THEME.color.border]
    const runs = rows.flat()

    expect(rows).toHaveLength(mark(DEFAULT_THEME.color).length)
    expect(rows.every(row => row.map(run => run.text).join('').length === MARK_WIDTH)).toBe(true)
    expect(runs.some(run => run.color && !palette.includes(run.color) && run.color !== background)).toBe(true)
    expect(runs.filter(run => !run.text.trim()).every(run => !run.backgroundColor && !run.color)).toBe(true)
    expect(markPixels(DEFAULT_THEME.color)).toBeUndefined()
    expect(mark(DEFAULT_THEME.color, 'CUSTOM\n  MARK')).toEqual([['', 'CUSTOM'], ['', '  MARK']])
  })

  it.each(['#031117', '#f7f9fb'])('uses one solid ink and one edge tone against %s', background => {
    const theme = { ...DEFAULT_THEME.color, primary: '#18a0ea' }
    const runs = markPixels(theme, background)!.flat()
    const inkColors = new Set(runs.flatMap(run => [run.color, run.backgroundColor]).filter(Boolean))
    const mixedCells = runs.filter(run => run.backgroundColor && run.backgroundColor !== run.color)

    expect(inkColors.size).toBe(2)
    expect(inkColors.has(theme.primary)).toBe(true)
    expect(mark(theme).every(([color]) => color === theme.primary)).toBe(true)
    expect(runs.some(run => run.text.includes('█') && run.color === theme.primary)).toBe(true)
    expect(mixedCells.length).toBeGreaterThan(0)
    expect(mixedCells.every(run => run.color === theme.primary)).toBe(true)
  })
})
