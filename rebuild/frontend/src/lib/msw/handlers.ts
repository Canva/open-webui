import { http, HttpResponse } from 'msw';
import type { User } from '$lib/types/user';

/**
 * The fixture user returned by the mocked `/api/me`. Matches the shape of
 * `app/schemas/user.py::UserRead` and uses a deterministic UUIDv7-shaped id
 * so snapshot tests stay stable across runs. `created_at` is epoch ms
 * (project-wide convention from rebuild.md §4).
 */
const fixtureUser: User = {
  id: '01900000-0000-7000-8000-000000000000',
  email: 'alice@canva.com',
  name: 'Alice Example',
  timezone: 'UTC',
  created_at: 1_704_067_200_000,
};

export const handlers = [http.get('*/api/me', () => HttpResponse.json(fixtureUser))];
