// Tests for the bot-signup guard core logic (QUEUE #60).
// Run: node --test supabase/functions/before-user-created/validation.test.mjs
//
// Hermetic tests use a mock DoH fetch; the two live tests at the bottom hit
// real DNS-over-HTTPS to prove the prompt's acceptance criteria
// (reject gmail.comaa, accept gmail.com).

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  extractDomain,
  syntaxCheck,
  isDisposable,
  checkMailDomain,
  evaluateSignup,
  _clearCache,
} from './validation.mjs';

function mockDoh(handler) {
  return async (request) => {
    const url = new URL(request.url);
    const name = url.searchParams.get('name');
    const type = url.searchParams.get('type');
    const body = handler(name, type);
    if (body === 'network-error') throw new TypeError('fetch failed');
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/dns-json' },
    });
  };
}

const MX_FOUND = { Status: 0, Answer: [{ type: 15, data: '10 mx.example.com.' }] };
const A_FOUND = { Status: 0, Answer: [{ type: 1, data: '93.184.216.34' }] };
const NXDOMAIN = { Status: 3 };
const EMPTY = { Status: 0 };
const SERVFAIL = { Status: 2 };

test.beforeEach(() => _clearCache());

// --- syntax ---------------------------------------------------------------

test('extractDomain lowercases and handles trim', () => {
  assert.equal(extractDomain('  User@GMail.COM '), 'gmail.com');
});

test('syntaxCheck rejects malformed emails', () => {
  for (const bad of ['', 'nope', '@gmail.com', 'a@', 'a b@gmail.com', 'a@gmail', 'a@-bad-.com']) {
    assert.equal(syntaxCheck(bad).ok, false, `should reject: "${bad}"`);
  }
});

test('syntaxCheck accepts normal addresses', () => {
  assert.deepEqual(syntaxCheck('ville@gmail.com'), { ok: true, domain: 'gmail.com' });
});

// --- disposable list --------------------------------------------------------

test('disposable domains are rejected', async () => {
  assert.equal(isDisposable('mailinator.com'), true);
  const res = await evaluateSignup('bot@mailinator.com', { fetchImpl: mockDoh(() => MX_FOUND) });
  assert.deepEqual(res, { allow: false, reason: 'disposable_domain' });
});

// --- MX / DoH decision matrix ----------------------------------------------

test('NXDOMAIN rejects (the gmail.comaa bot pattern)', async () => {
  const res = await evaluateSignup('aramadjibril18@gmail.comaa', {
    fetchImpl: mockDoh(() => NXDOMAIN),
  });
  assert.deepEqual(res, { allow: false, reason: 'domain_undeliverable' });
});

test('MX present allows', async () => {
  const res = await evaluateSignup('real@gmail.com', { fetchImpl: mockDoh(() => MX_FOUND) });
  assert.deepEqual(res, { allow: true, reason: 'ok' });
});

test('no MX but A record allows (implicit MX fallback)', async () => {
  const res = await evaluateSignup('a@a-only.example', {
    fetchImpl: mockDoh((name, type) => (type === 'MX' ? EMPTY : A_FOUND)),
  });
  assert.deepEqual(res, { allow: true, reason: 'ok' });
});

test('no MX and no A rejects', async () => {
  const res = await evaluateSignup('a@parked.example', { fetchImpl: mockDoh(() => EMPTY) });
  assert.deepEqual(res, { allow: false, reason: 'domain_undeliverable' });
});

test('DoH totally unreachable fails OPEN', async () => {
  const res = await evaluateSignup('a@gmail.com', {
    fetchImpl: mockDoh(() => 'network-error'),
  });
  assert.deepEqual(res, { allow: true, reason: 'dns_inconclusive_fail_open' });
});

test('SERVFAIL on both resolvers fails OPEN', async () => {
  const res = await evaluateSignup('a@gmail.com', { fetchImpl: mockDoh(() => SERVFAIL) });
  assert.deepEqual(res, { allow: true, reason: 'dns_inconclusive_fail_open' });
});

test('first resolver down, second answers -> normal verdict', async () => {
  let calls = 0;
  const fetchImpl = async (request) => {
    calls += 1;
    if (calls === 1) throw new TypeError('fetch failed');
    return new Response(JSON.stringify(MX_FOUND), { status: 200 });
  };
  const res = await evaluateSignup('a@gmail.com', { fetchImpl });
  assert.deepEqual(res, { allow: true, reason: 'ok' });
  assert.equal(calls, 2);
});

test('verdicts are cached per domain', async () => {
  let calls = 0;
  const fetchImpl = mockDoh(() => {
    calls += 1;
    return MX_FOUND;
  });
  await checkMailDomain('gmail.com', { fetchImpl });
  await checkMailDomain('gmail.com', { fetchImpl });
  assert.equal(calls, 1);
});

// --- live acceptance criteria (real DoH) -------------------------------------

test('LIVE: gmail.comaa is rejected', async () => {
  const res = await evaluateSignup('aramadjibril18@gmail.comaa', { timeoutMs: 5000 });
  assert.deepEqual(res, { allow: false, reason: 'domain_undeliverable' });
});

test('LIVE: gmail.com is accepted', async () => {
  const res = await evaluateSignup('real.person@gmail.com', { timeoutMs: 5000 });
  assert.deepEqual(res, { allow: true, reason: 'ok' });
});
