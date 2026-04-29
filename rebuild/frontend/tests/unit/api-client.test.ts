import { describe, expect, it, vi } from 'vitest';
import { apiFetch, ApiError } from '../../src/lib/api/client';
import type { User } from '../../src/lib/types/user';

// Stub the SvelteKit-generated `$env/static/public` module so `apiFetch`
// resolves to a same-origin URL during the unit test. Vitest replaces the
// import via this hoisted mock; the production module is not imported.
vi.mock('$env/static/public', () => ({ PUBLIC_API_BASE_URL: '' }));

const fixtureUser: User = {
  id: '01900000-0000-7000-8000-000000000000',
  email: 'alice@canva.com',
  name: 'Alice Example',
  timezone: 'UTC',
  created_at: 1_704_067_200_000,
};

describe('apiFetch', () => {
  it('deserialises a UserRead-shaped response from a stubbed fetch', async () => {
    const fetchStub = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(fixtureUser), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const user = await apiFetch<User>('/api/me', {}, fetchStub as unknown as typeof fetch);

    expect(user).toEqual(fixtureUser);
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });

  it('honors content-type by sending application/json on outgoing requests', async () => {
    const fetchStub = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(fixtureUser), { status: 200 }));

    await apiFetch<User>('/api/me', {}, fetchStub as unknown as typeof fetch);

    const callArgs = fetchStub.mock.calls[0];
    expect(callArgs).toBeDefined();
    const init = callArgs![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['content-type']).toBe('application/json');
  });

  it('preserves caller-supplied headers (and lets them override defaults)', async () => {
    const fetchStub = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(fixtureUser), { status: 200 }));

    await apiFetch<User>(
      '/api/me',
      { headers: { 'x-custom': 'hello', 'content-type': 'application/json; charset=utf-8' } },
      fetchStub as unknown as typeof fetch,
    );

    const callArgs = fetchStub.mock.calls[0];
    const init = callArgs![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers['x-custom']).toBe('hello');
    expect(headers['content-type']).toBe('application/json; charset=utf-8');
  });

  it('throws ApiError with status === 401 on a 401 response', async () => {
    const fetchStub = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'missing trusted header' }), {
        status: 401,
        statusText: 'Unauthorized',
        headers: { 'content-type': 'application/json' },
      }),
    );

    await expect(
      apiFetch<User>('/api/me', {}, fetchStub as unknown as typeof fetch),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
    });
  });

  it('exposes the response body on ApiError.detail when JSON is returned', async () => {
    const fetchStub = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'forbidden' }), {
        status: 403,
        headers: { 'content-type': 'application/json' },
      }),
    );

    try {
      await apiFetch<User>('/api/me', {}, fetchStub as unknown as typeof fetch);
      throw new Error('apiFetch should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(403);
      expect(apiErr.detail).toEqual({ detail: 'forbidden' });
    }
  });

  it('returns ApiError with undefined detail when the body is non-JSON', async () => {
    const fetchStub = vi.fn().mockResolvedValue(new Response('plain text', { status: 500 }));

    try {
      await apiFetch<User>('/api/me', {}, fetchStub as unknown as typeof fetch);
      throw new Error('apiFetch should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).detail).toBeUndefined();
    }
  });
});
