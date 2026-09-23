// tests/scan-ats-full-json-offer.test.mjs — the --json contract's per-offer
// shape (job-enrichment audit, #3811). This is what the backend automation
// path reads directly; it must preserve description/externalId when the
// provider's list API already returned them for free, without turning
// data/pipeline.md (the local CLI's format, tested separately) into a JD
// store.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatJsonOffer } from '../scan-ats-full.mjs';

test('formatJsonOffer preserves description and externalId when the provider supplied them', () => {
  const offer = {
    company: 'Acme',
    title: 'Staff Engineer',
    url: 'https://jobs.lever.co/acme/1',
    location: 'Remote — Europe',
    postedAt: Date.parse('2026-07-01T00:00:00Z'),
    source: 'lever-full',
    description: 'Build the platform.',
    id: 'lever-abc-123',
  };
  const out = formatJsonOffer(offer);
  assert.equal(out.description, 'Build the platform.');
  assert.equal(out.externalId, 'lever-abc-123');
  assert.equal(out.location, 'Remote — Europe');
  assert.equal(out.postedAt, '2026-07-01');
  assert.equal(out.source, 'lever-full');
});

test('formatJsonOffer emits null (not undefined/absent) for description/externalId when the provider had none', () => {
  const offer = { company: 'Acme', title: 'Ghost Role', url: 'https://jobs.lever.co/acme/2', source: 'lever-full' };
  const out = formatJsonOffer(offer);
  assert.equal(out.description, null);
  assert.equal(out.externalId, null);
  assert.equal(out.location, null);
  assert.equal(out.postedAt, null);
});

test('formatJsonOffer never leaks provider-internal fields (salary, blacklisted metadata) beyond the documented contract', () => {
  const offer = { company: 'Acme', title: 'Role', url: 'https://jobs.lever.co/acme/3', source: 'lever-full', salary: { min: 1, max: 2 } };
  const out = formatJsonOffer(offer);
  assert.equal('salary' in out, false);
});

test('JSON.stringify of formatJsonOffer output round-trips through JSON.parse unchanged (the real stdout contract)', () => {
  const offer = { company: 'Acme', title: 'Role', url: 'https://x/1', source: 'greenhouse-full', description: 'JD text here', id: '999' };
  const roundtripped = JSON.parse(JSON.stringify(formatJsonOffer(offer)));
  assert.equal(roundtripped.description, 'JD text here');
  assert.equal(roundtripped.externalId, '999');
});
