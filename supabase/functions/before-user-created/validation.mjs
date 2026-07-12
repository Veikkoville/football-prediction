// Bot-signup guard: pure e-mail validation logic (QUEUE #60).
//
// Portable ESM module — no Deno/Node-only APIs so the same code runs in the
// Supabase Edge Function (Deno) and under `node --test` on the dev machine.
// The DoH fetch is injectable for hermetic tests.
//
// Decision policy (fail-open on infra, fail-closed on hard negatives):
//   reject  -> syntactically broken e-mail, disposable domain, NXDOMAIN,
//              or domain with neither MX nor A/AAAA records
//   allow   -> valid-looking address whose domain resolves (MX, or A/AAAA
//              per RFC 5321 implicit-MX fallback)
//   allow   -> DoH unreachable / timeout / unexpected status (never block
//              real users because our DNS check had a bad day)

// Functioning throwaway providers the MX check cannot catch.
const DISPOSABLE_DOMAINS = new Set([
  '10minutemail.com',
  'dispostable.com',
  'discard.email',
  'fakeinbox.com',
  'getnada.com',
  'guerrillamail.com',
  'guerrillamail.info',
  'inboxkitten.com',
  'mailcatch.com',
  'maildrop.cc',
  'mailinator.com',
  'mailnesia.com',
  'mintemail.com',
  'mohmal.com',
  'mytemp.email',
  'sharklasers.com',
  'spamgourmet.com',
  'temp-mail.org',
  'tempail.com',
  'tempmail.com',
  'tempmailo.com',
  'throwawaymail.com',
  'trashmail.com',
  'yopmail.com',
]);

// Minimal syntactic gate. Deliberately loose (full RFC 5322 is a tarpit);
// the MX lookup does the heavy lifting. Rejects whitespace, missing @,
// empty local part, domain without a dot, and non-LDH domain labels.
const DOMAIN_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/i;

export function extractDomain(email) {
  if (typeof email !== 'string') return null;
  const trimmed = email.trim();
  const at = trimmed.lastIndexOf('@');
  if (at <= 0 || at === trimmed.length - 1) return null;
  if (/\s/.test(trimmed)) return null;
  return trimmed.slice(at + 1).toLowerCase();
}

export function syntaxCheck(email) {
  const domain = extractDomain(email);
  if (!domain) return { ok: false, reason: 'malformed_email' };
  if (!DOMAIN_RE.test(domain)) return { ok: false, reason: 'malformed_domain' };
  return { ok: true, domain };
}

export function isDisposable(domain) {
  return DISPOSABLE_DOMAINS.has(domain);
}

// --- DNS-over-HTTPS (Cloudflare primary, Google fallback) ----------------

const DOH_ENDPOINTS = [
  (name, type) =>
    new Request(
      `https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(name)}&type=${type}`,
      { headers: { accept: 'application/dns-json' } },
    ),
  (name, type) =>
    new Request(
      `https://dns.google/resolve?name=${encodeURIComponent(name)}&type=${type}`,
      { headers: { accept: 'application/dns-json' } },
    ),
];

const DNS_NOERROR = 0;
const DNS_NXDOMAIN = 3;

async function dohQuery(domain, type, fetchImpl, timeoutMs) {
  for (const makeRequest of DOH_ENDPOINTS) {
    try {
      const res = await fetchImpl(makeRequest(domain, type), {
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) continue; // try next resolver
      const data = await res.json();
      if (data.Status === DNS_NXDOMAIN) return { outcome: 'nxdomain' };
      if (data.Status === DNS_NOERROR) {
        const answers = (data.Answer ?? []).filter((a) => a.type !== undefined);
        return { outcome: answers.length > 0 ? 'found' : 'empty' };
      }
      // SERVFAIL etc: inconclusive, try next resolver
    } catch {
      // network error / timeout: try next resolver
    }
  }
  return { outcome: 'unknown' };
}

// Tiny TTL cache so warm instances don't re-resolve gmail.com per signup.
const cache = new Map();
const CACHE_TTL_MS = 60 * 60 * 1000;
const CACHE_MAX = 1000;

function cacheGet(key, now) {
  const hit = cache.get(key);
  if (hit && hit.expires > now) return hit.value;
  cache.delete(key);
  return undefined;
}

function cacheSet(key, value, now) {
  if (cache.size >= CACHE_MAX) cache.clear();
  cache.set(key, { value, expires: now + CACHE_TTL_MS });
}

/**
 * Does the domain accept mail? MX first; on an MX-less NOERROR fall back to
 * A/AAAA (implicit MX, RFC 5321 §5.1).
 * Returns 'deliverable' | 'undeliverable' | 'unknown'.
 */
export async function checkMailDomain(domain, opts = {}) {
  const fetchImpl = opts.fetchImpl ?? fetch;
  const timeoutMs = opts.timeoutMs ?? 1500;
  const now = opts.now ?? Date.now();

  const cached = cacheGet(domain, now);
  if (cached !== undefined) return cached;

  const mx = await dohQuery(domain, 'MX', fetchImpl, timeoutMs);
  let verdict;
  if (mx.outcome === 'nxdomain') {
    verdict = 'undeliverable';
  } else if (mx.outcome === 'found') {
    verdict = 'deliverable';
  } else if (mx.outcome === 'empty') {
    const a = await dohQuery(domain, 'A', fetchImpl, timeoutMs);
    if (a.outcome === 'found') verdict = 'deliverable';
    else if (a.outcome === 'nxdomain' || a.outcome === 'empty') verdict = 'undeliverable';
    else verdict = 'unknown';
  } else {
    verdict = 'unknown';
  }

  if (verdict !== 'unknown') cacheSet(domain, verdict, now);
  return verdict;
}

/**
 * Full decision for one signup attempt.
 * Returns { allow: boolean, reason: string }.
 */
export async function evaluateSignup(email, opts = {}) {
  const syntax = syntaxCheck(email);
  if (!syntax.ok) return { allow: false, reason: syntax.reason };
  if (isDisposable(syntax.domain)) return { allow: false, reason: 'disposable_domain' };

  const verdict = await checkMailDomain(syntax.domain, opts);
  if (verdict === 'undeliverable') return { allow: false, reason: 'domain_undeliverable' };
  if (verdict === 'unknown') return { allow: true, reason: 'dns_inconclusive_fail_open' };
  return { allow: true, reason: 'ok' };
}

// Test hook: clear the module-level cache between test cases.
export function _clearCache() {
  cache.clear();
}
