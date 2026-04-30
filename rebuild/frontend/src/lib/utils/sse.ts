/**
 * SSE → AsyncIterable parser for the M2 chat stream.
 *
 * Reads from a `ReadableStream<Uint8Array>` (the body of
 * `POST /api/chats/{id}/messages`) and yields one typed
 * `SSEEvent` per `event: ...\ndata: ...\n\n` frame.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § Stores and
 * state, line 1042 ("a 60-line `ReadableStream → AsyncIterable<{event,
 * data}>` parser"). The parser stays a pure helper at `*.ts` (no
 * runes) so it is unit-testable from `vitest` without a Svelte
 * runtime — the consuming `ActiveChatStore` owns the AbortController.
 *
 * Implementation notes:
 * - One `TextDecoder` is constructed up-front with `{ fatal: false,
 *   ignoreBOM: true }`; every `decode(chunk, { stream: true })` call
 *   carries the `stream: true` flag so a multibyte UTF-8 character
 *   split across two chunks is handled correctly (the decoder buffers
 *   the trailing partial code unit until the next call).
 * - Frames are split on the spec-mandated `\n\n` boundary; SSE
 *   comment lines (`: keep-alive`) are silently dropped at parse
 *   time so the consumer never sees them.
 * - Malformed JSON in a frame is logged via `console.warn` and the
 *   frame is skipped — the stream itself stays alive (the next
 *   `delta` will still land).
 * - Cancellation: the consuming component holds an `AbortController`
 *   whose abort causes `reader.read()` to throw. The parser does not
 *   suppress that error — the caller's `try/catch` in
 *   `ActiveChatStore.send` decides whether to swallow (silent on
 *   user-cancel) or surface (network error toast).
 * - The `unknown` cast on the parsed payload is justified: SSE frames
 *   carry untyped JSON over the wire and runtime validation
 *   (zod/valibot) would be heavy for a backend we own. The
 *   discriminated-union assertion at the call site is sufficient
 *   contract-checking; a payload mismatch surfaces as a TS error in
 *   the consumer when the union widens.
 */

import type { SSEEvent, SSEEventName } from '$lib/types/sse';

const FRAME_SEPARATOR = '\n\n';

/**
 * Parse an SSE byte stream into typed events.
 *
 * The function is a generator: pull events with `for await (const ev of
 * parseSSE(stream)) { ... }`. It returns when the underlying reader
 * signals `done`, when the stream terminates with a partial frame
 * (logged + flushed defensively), or when `reader.read()` throws —
 * abort propagates out untouched so the caller's catch block can
 * distinguish silent cancellation from genuine errors.
 */
export async function* parseSSE(stream: ReadableStream<Uint8Array>): AsyncIterable<SSEEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true });
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        // Flush any decoder-internal partial code unit.
        buffer += decoder.decode();
        // The server always terminates with `\n\n` after the terminal
        // frame, so `buffer` is normally empty here. Defensively flush
        // any trailing complete frame in case a proxy stripped the
        // final newline pair.
        const tail = buffer.trim();
        if (tail.length > 0) {
          const event = parseFrame(tail);
          if (event !== null) yield event;
        }
        return;
      }

      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf(FRAME_SEPARATOR);
      while (separatorIndex !== -1) {
        const rawFrame = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + FRAME_SEPARATOR.length);
        const event = parseFrame(rawFrame);
        if (event !== null) yield event;
        separatorIndex = buffer.indexOf(FRAME_SEPARATOR);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parse a single `event: ...\ndata: ...` frame. Returns `null` for
 * comment-only frames (`: keep-alive`), unknown event names, or
 * malformed JSON payloads — the parser never throws on a single bad
 * frame; the stream stays alive.
 */
function parseFrame(raw: string): SSEEvent | null {
  let event: string | null = null;
  let dataLines: string[] = [];

  for (const line of raw.split('\n')) {
    if (line.length === 0) continue;
    // SSE comment line — silently drop.
    if (line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      // The SSE spec says the leading single space after `data:` is
      // optional and consumed; mirror that to keep JSON parsing
      // tolerant of either `data:{...}` or `data: {...}`.
      const rest = line.slice('data:'.length);
      dataLines.push(rest.startsWith(' ') ? rest.slice(1) : rest);
      continue;
    }
    // Other SSE fields (`id:`, `retry:`) are not used by the M2
    // server; ignore quietly.
  }

  if (event === null || dataLines.length === 0) {
    if (event !== null) {
      console.warn('parseSSE: frame with no data lines', { event });
    }
    return null;
  }

  const payload = dataLines.join('\n');
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch (err) {
    console.warn('parseSSE: malformed JSON in frame', { event, payload, err });
    return null;
  }

  if (!isKnownEventName(event)) {
    console.warn('parseSSE: unknown event name', { event });
    return null;
  }

  // The discriminated union is asserted here. The SSE wire format is
  // not self-describing, so runtime validation would mean shipping a
  // duplicate of `lib/types/sse.ts` — overkill for a backend we own.
  // A genuine schema mismatch surfaces in the consumer as a narrowing
  // failure when the union widens.
  return { event, data: parsed } as SSEEvent;
}

const KNOWN_EVENTS: ReadonlySet<SSEEventName> = new Set<SSEEventName>([
  'start',
  'delta',
  'usage',
  'done',
  'error',
  'cancelled',
  'timeout',
]);

function isKnownEventName(name: string): name is SSEEventName {
  return KNOWN_EVENTS.has(name as SSEEventName);
}
