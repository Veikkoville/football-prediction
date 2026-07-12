// Supabase Auth Hook: Before User Created (QUEUE #60 bot-signup guard).
//
// Deployed as an Edge Function and wired in Dashboard -> Auth -> Hooks ->
// "Before User Created" (HTTPS hook). Rejects bot signups server-side:
// no client change, no breakage of installed app versions.
//
// Deploy notes: see README.md in this directory. Requires secrets:
//   BEFORE_USER_CREATED_HOOK_SECRET  (Standard Webhooks secret from the
//                                     dashboard hook config, "v1,whsec_..." )
// Deploy with --no-verify-jwt (Auth calls this with a webhook signature,
// not a user JWT).

import { Webhook } from 'npm:standardwebhooks@1.0.0';
import { evaluateSignup } from './validation.mjs';

const HOOK_SECRET = Deno.env.get('BEFORE_USER_CREATED_HOOK_SECRET') ?? '';

const REJECT_MESSAGE =
  'This email address looks invalid or undeliverable. Please sign up with a real email address.';

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

Deno.serve(async (req) => {
  const rawBody = await req.text();

  // --- Verify Standard Webhooks signature -------------------------------
  if (!HOOK_SECRET) {
    // Misconfiguration: without a secret we cannot trust the caller.
    // Fail open (allow) rather than lock out all signups, but log loudly.
    console.error('before-user-created: BEFORE_USER_CREATED_HOOK_SECRET not set; allowing signup');
    return json(200, {});
  }
  try {
    const wh = new Webhook(HOOK_SECRET.replace('v1,whsec_', ''));
    wh.verify(rawBody, {
      'webhook-id': req.headers.get('webhook-id') ?? '',
      'webhook-timestamp': req.headers.get('webhook-timestamp') ?? '',
      'webhook-signature': req.headers.get('webhook-signature') ?? '',
    });
  } catch (err) {
    console.error('before-user-created: signature verification failed', err);
    return json(401, {
      error: { http_code: 401, message: 'Invalid webhook signature' },
    });
  }

  // --- Evaluate the signup ----------------------------------------------
  let email = '';
  try {
    const payload = JSON.parse(rawBody);
    email = payload?.user?.email ?? '';
  } catch {
    console.error('before-user-created: unparseable payload; allowing signup');
    return json(200, {});
  }

  // Phone-only or otherwise email-less signups: not our concern here.
  if (!email) return json(200, {});

  const { allow, reason } = await evaluateSignup(email);
  const domain = email.split('@').pop() ?? '';

  if (allow) {
    if (reason !== 'ok') {
      console.warn(`before-user-created: allowed (${reason}) domain=${domain}`);
    }
    return json(200, {});
  }

  console.warn(`before-user-created: REJECTED (${reason}) domain=${domain}`);
  // HUOM: hylkäys palautetaan HTTP 200 + error-body. Dokumentaation
  // 4xx-esimerkki EI toimi deployattua GoTruea vasten: hookshttp.go palauttaa
  // hookin 400:lle sokeasti 500 "Invalid payload sent to hook" ja parsii
  // error-objektin ({"error":{"http_code","message"}}, hookserrors.Check)
  // VAIN 200/202-vastauksen bodysta. Verifioitu supabase/auth-lähteestä +
  // livenä 12.7.2026 (upstream-bugi: supabase/auth#2235).
  return json(200, {
    error: { http_code: 400, message: REJECT_MESSAGE },
  });
});
