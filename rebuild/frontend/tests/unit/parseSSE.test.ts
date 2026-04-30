/**
 * Vitest unit suite for `lib/utils/sse.ts` — the streaming SSE
 * `ReadableStream → AsyncIterable<SSEEvent>` parser used by
 * `ActiveChatStore.send()`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1061): "parseSSE.test.ts — feed it
 *     byte chunks split mid-event, mid-line, mid-multibyte UTF-8."
 *   - § SSE streaming (lines 660-668): the seven-event taxonomy this
 *     parser must accept.
 *
 * Implementation notes:
 *   - Every fixture builds the byte stream by hand (split-points are
 *     the whole point of this suite). The `ReadableStream` from
 *     `Uint8Array[]` constructor pattern is the closest analogue to
 *     a real `fetch().body` we get in Node 20+.
 *   - The fatal-on-malformed branch: `parseFrame` logs and returns
 *     `null`; the parser keeps consuming the stream so the next valid
 *     frame still lands. Tests assert on both the dropped frame AND
 *     the surviving subsequent frame so a regression that bails on
 *     bad JSON can't slip through.
 *
 * Cross-runtime behaviour: `TextDecoder` is universal in modern Node
 * (≥18) and every browser the rebuild targets; no shims required.
 */

import { describe, expect, it, vi } from 'vitest';

import { parseSSE } from '../../src/lib/utils/sse';
import type { SSEEvent } from '../../src/lib/types/sse';

/**
 * Build a `ReadableStream<Uint8Array>` from a list of byte chunks.
 * Each chunk is enqueued in order so the parser sees exactly the
 * fragmentation under test.
 */
function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

/** Small convenience: encode a string into a Uint8Array via UTF-8. */
function bytes(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

/**
 * Materialise the parser into an array. The parser is an
 * `AsyncIterable<SSEEvent>`; the helper here drains it so spec
 * assertions can index into the result.
 */
async function collect(stream: ReadableStream<Uint8Array>): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  for await (const event of parseSSE(stream)) events.push(event);
  return events;
}

describe('parseSSE', () => {
  it('parses a well-formed event stream', async () => {
    const stream = streamOf([
      bytes(
        `event: start\ndata: ${JSON.stringify({
          user_message_id: 'u1',
          assistant_message_id: 'a1',
        })}\n\n`,
      ),
      bytes(`event: delta\ndata: ${JSON.stringify({ content: 'Hi' })}\n\n`),
      bytes(
        `event: done\ndata: ${JSON.stringify({
          assistant_message_id: 'a1',
          finish_reason: 'stop',
        })}\n\n`,
      ),
    ]);

    const events = await collect(stream);

    expect(events).toHaveLength(3);
    expect(events[0]!.event).toBe('start');
    expect(events[1]!.event).toBe('delta');
    expect(events[2]!.event).toBe('done');
    if (events[1]!.event === 'delta') {
      expect(events[1]!.data.content).toBe('Hi');
    }
  });

  it('handles an event split across two chunks (split mid-event)', async () => {
    const full =
      `event: delta\ndata: ${JSON.stringify({ content: 'Hello' })}\n\n` +
      `event: done\ndata: ${JSON.stringify({
        assistant_message_id: 'a1',
        finish_reason: 'stop',
      })}\n\n`;
    // Split inside the first frame's `data:` JSON payload — the
    // parser must buffer until the `\n\n` boundary lands in chunk 2.
    const splitAt = full.indexOf('"Hello') + 3;
    const stream = streamOf([bytes(full.slice(0, splitAt)), bytes(full.slice(splitAt))]);

    const events = await collect(stream);

    expect(events).toHaveLength(2);
    if (events[0]!.event === 'delta') {
      expect(events[0]!.data.content).toBe('Hello');
    }
  });

  it('handles a single line split across chunks (split mid-line, before newline)', async () => {
    // Splitting before `\n` in the middle of `data: {...}` exercises
    // the "buffer until you see the separator" branch.
    const frame = `event: delta\ndata: ${JSON.stringify({ content: 'token' })}\n\n`;
    // Split right between `data:` and the JSON payload so chunk 1
    // ends mid-line and chunk 2 carries the JSON + the terminator.
    const stream = streamOf([
      bytes(frame.slice(0, frame.indexOf('data:') + 'data:'.length)),
      bytes(frame.slice(frame.indexOf('data:') + 'data:'.length)),
    ]);

    const events = await collect(stream);

    expect(events).toHaveLength(1);
    if (events[0]!.event === 'delta') {
      expect(events[0]!.data.content).toBe('token');
    }
  });

  it('handles a multibyte UTF-8 codepoint split across chunks', async () => {
    // 🚀 (U+1F680) is a 4-byte UTF-8 sequence: F0 9F 9A 80.
    const frame = `event: delta\ndata: ${JSON.stringify({ content: '🚀 launch' })}\n\n`;
    const buf = bytes(frame);

    // Find the first byte of the rocket sequence and split mid-codepoint
    // (after byte 1 of 4 — F0). Without `TextDecoder({ stream: true })`
    // the first half would decode to the U+FFFD replacement character
    // and the assistant content would render garbled.
    const rocketByteIndex = buf.findIndex((b) => b === 0xf0);
    expect(rocketByteIndex, 'fixture must include the 0xF0 rocket lead byte').toBeGreaterThan(0);
    const splitAt = rocketByteIndex + 2; // mid-codepoint

    const stream = streamOf([buf.slice(0, splitAt), buf.slice(splitAt)]);
    const events = await collect(stream);

    expect(events).toHaveLength(1);
    if (events[0]!.event === 'delta') {
      // The rocket survives intact; no replacement character.
      expect(events[0]!.data.content).toBe('🚀 launch');
      expect(events[0]!.data.content).not.toContain('\uFFFD');
    }
  });

  it('ignores SSE comment frames (`: keep-alive\\n\\n`) without breaking the stream', async () => {
    const stream = streamOf([
      bytes(': keep-alive\n\n'),
      bytes(`event: delta\ndata: ${JSON.stringify({ content: 'after-comment' })}\n\n`),
    ]);

    const events = await collect(stream);

    expect(events).toHaveLength(1);
    expect(events[0]!.event).toBe('delta');
  });

  it('logs and skips malformed JSON without breaking the stream', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const stream = streamOf([
      // Frame 1: malformed JSON — the parser must skip it.
      bytes(`event: delta\ndata: {not valid json\n\n`),
      // Frame 2: valid follow-up — must still be yielded.
      bytes(`event: delta\ndata: ${JSON.stringify({ content: 'survived' })}\n\n`),
    ]);

    const events = await collect(stream);

    expect(events).toHaveLength(1);
    if (events[0]!.event === 'delta') {
      expect(events[0]!.data.content).toBe('survived');
    }
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('terminates cleanly when the underlying reader signals done', async () => {
    // Empty stream: parser yields nothing and returns without throwing.
    const stream = streamOf([]);
    const events = await collect(stream);
    expect(events).toEqual([]);
  });

  it('propagates an underlying-reader error (abort) out of the iterator', async () => {
    // A stream that errors on first read mimics an `AbortController.abort()`
    // on a real `fetch().body`. The parser does NOT swallow this; the
    // consuming `ActiveChatStore.send` catch handler is responsible for
    // sniffing `AbortError` vs surfacing the failure.
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const err = new Error('aborted');
        // Mirror the DOMException "AbortError" name shape so the
        // consumer's `isAbortError` sniff would fire too.
        (err as Error & { name: string }).name = 'AbortError';
        controller.error(err);
      },
    });

    await expect(collect(stream)).rejects.toMatchObject({
      name: 'AbortError',
      message: 'aborted',
    });
  });

  it('drops unknown event names (defence-in-depth narrowing)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const stream = streamOf([
      bytes(`event: shenanigans\ndata: ${JSON.stringify({ x: 1 })}\n\n`),
      bytes(`event: delta\ndata: ${JSON.stringify({ content: 'ok' })}\n\n`),
    ]);

    const events = await collect(stream);

    expect(events).toHaveLength(1);
    expect(events[0]!.event).toBe('delta');
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
