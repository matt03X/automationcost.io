// Cloudflare Pages Function — anonymous willingness-to-pay signal for the Wizard 01 fake-door.
//
// GDPR-safe: stores NO personal data. It only records an interest event
// (recommended tool + founding price + day). No email, no IP, no cookies.
//
// Zero setup: every event is console.log'd → readable in the Cloudflare Pages
// dashboard logs (search "FOUNDING_INTEREST") or via `wrangler pages deployment tail`.
//
// Optional persistent counter: bind a KV namespace as `WTP` in the Pages project
// (Settings → Functions → KV namespace bindings). Then GET /api/founding-interest
// returns the running total.

export async function onRequestPost({ request, env }) {
  let body = {};
  try { body = await request.json(); } catch (_) {}

  const tool = String(body.tool || 'unknown').slice(0, 40).replace(/[^a-z0-9-]/gi, '');
  const price = Number(body.price) || 0;
  const day = new Date().toISOString().slice(0, 10);

  // Always log — works with no KV setup at all.
  console.log('FOUNDING_INTEREST', JSON.stringify({ tool, price, day }));

  // Optional persistent counters when a KV namespace `WTP` is bound.
  if (env && env.WTP) {
    const keys = ['total', `day:${day}`, `tool:${tool}`];
    await Promise.all(keys.map(async (k) => {
      const cur = parseInt((await env.WTP.get('count:' + k)) || '0', 10);
      await env.WTP.put('count:' + k, String(cur + 1));
    }));
  }

  return Response.json({ ok: true });
}

// Quick read of the signal (only meaningful if KV `WTP` is bound).
export async function onRequestGet({ env }) {
  if (!env || !env.WTP) {
    return Response.json({
      ok: true,
      note: 'No KV bound — read the signal from Cloudflare Pages function logs (FOUNDING_INTEREST) or `wrangler pages deployment tail`.',
    });
  }
  const total = Number((await env.WTP.get('count:total')) || '0');
  return Response.json({ ok: true, total });
}
