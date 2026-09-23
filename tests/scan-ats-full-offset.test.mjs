// tests/scan-ats-full-offset.test.mjs — deterministic --offset rotation for
// sampleCompanies (Phase 5 follow-up §C). Manual Explore keeps using
// --shuffle (existing, unaffected behavior below); automated morning
// rotation uses --offset for a persistent, gap-free cursor across runs.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sampleCompanies } from '../scan-ats-full.mjs';

const LIST = Array.from({ length: 10 }, (_, i) => `company-${i}`);

test('no offset, no shuffle: the natural prefix (existing behavior unchanged)', () => {
  assert.deepEqual(sampleCompanies(LIST, 3), ['company-0', 'company-1', 'company-2']);
});

test('offset mid-list, no wraparound needed', () => {
  assert.deepEqual(sampleCompanies(LIST, 3, false, 3), ['company-3', 'company-4', 'company-5']);
});

test('offset + limit exactly reaches the end', () => {
  assert.deepEqual(sampleCompanies(LIST, 3, false, 7), ['company-7', 'company-8', 'company-9']);
});

test('offset + limit crosses the end: wraps to the beginning within the same call', () => {
  assert.deepEqual(sampleCompanies(LIST, 4, false, 8), ['company-8', 'company-9', 'company-0', 'company-1']);
});

test('offset normalizes past the dataset length (dataset shrank since the cursor was saved)', () => {
  // offset=23 on a 10-item list -> 23 % 10 = 3
  assert.deepEqual(sampleCompanies(LIST, 2, false, 23), ['company-3', 'company-4']);
});

test('offset of exactly the list length wraps to the start', () => {
  assert.deepEqual(sampleCompanies(LIST, 2, false, 10), ['company-0', 'company-1']);
});

test('limit larger than the dataset returns every company exactly once regardless of offset', () => {
  const result = sampleCompanies(LIST, 50, false, 5);
  assert.equal(new Set(result).size, LIST.length);
  assert.equal(result.length, LIST.length);
});

test('shuffle=true ignores offset entirely and returns a full-length sample when limit >= length', () => {
  const result = sampleCompanies(LIST, 20, true, 5);
  assert.equal(result.length, 10);
  assert.deepEqual([...result].sort(), [...LIST].sort());
});

test('empty dataset never throws', () => {
  assert.deepEqual(sampleCompanies([], 5, false, 3), []);
});
