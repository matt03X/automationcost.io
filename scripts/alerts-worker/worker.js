// WizardCost Alerts — Cloudflare Worker (soukromý backend pro Apple Shortcut)
// ---------------------------------------------------------------------------
// Drží MailerLite token jako Worker SECRET (NIKDY v kódu/repu) a umožní z iPhonu:
//   GET  /status?site=automation  → { draft:{id,subject}|null, subscribers:N }
//   POST /send?site=automation    → { sent:true, subject } | { sent:false, reason }
//   POST /digest?site=automation  → uloží digest (cloud routine ho sem pošle)
//   GET  /digest?site=automation  → { date, summary, actions[], full } | { digest:null }
// Vše vyžaduje hlavičku:  Authorization: Bearer <SHORTCUT_SECRET>
//
// /send posílá EXISTUJÍCÍ draft, který založí scripts/send_price_alerts.py při revizi
// (draft = naše kampaň "Price alert (<site>) — …"). Telefon je jen finální
// potvrzovací tlačítko → bezpečné (cenu ověřuješ u PC, odešleš až z mobilu).
//
// /digest = „ping na iPhone" pro týdenní SEO digest: cloud routine (machine-off) udělá
// POST /digest se shrnutím; iPhone Shortcut (Po ráno) udělá GET /digest a ukáže notifikaci.
// Data drží Cloudflare KV (binding DIGEST) za authem → privátní, nic veřejného.
//
// SECRETS (Cloudflare → Worker → Settings → Variables and Secrets, typ Secret):
//   MAILERLITE_API_TOKEN  — MailerLite → Integrations → API → generate token
//   SHORTCUT_SECRET       — náhodný řetězec, stejný vložíš do Shortcutu
//   LLM_GROUP_ID          — (volitelné) id MailerLite skupiny pro LLM site
// KV BINDING (Settings → Variables → KV Namespace Bindings, nebo wrangler.toml):
//   DIGEST                — KV namespace pro uložený digest (per site)

const ML = "https://connect.mailerlite.com/api";

const SITES = {
  automation: { group: "190009381054580705" }, // price-drop-alerts (automation)
  llm: { groupEnv: "LLM_GROUP_ID" },            // doplní owner přes secret
};

async function ml(env, path, method = "GET", body) {
  const r = await fetch(ML + path, {
    method,
    headers: {
      Authorization: `Bearer ${env.MAILERLITE_API_TOKEN}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const txt = await r.text();
  if (!r.ok) throw new Error(`MailerLite ${path} → ${r.status}: ${txt.slice(0, 160)}`);
  return txt ? JSON.parse(txt) : {};
}

// nejnovější DRAFT kampaň, jejíž jméno patří dané site ("Price alert (<site>)")
async function latestDraft(env, site) {
  const res = await ml(env, "/campaigns?filter[status]=draft&limit=25");
  const prefix = `Price alert (${site})`;
  return (res.data || [])
    .filter((c) => (c.name || "").startsWith(prefix))
    .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())[0] || null;
}

function subjectOf(c) {
  return (c && c.emails && c.emails[0] && c.emails[0].subject) || (c && c.name) || "(bez předmětu)";
}

function groupId(env, site) {
  const s = SITES[site];
  if (!s) return null;
  return s.group || (s.groupEnv && env[s.groupEnv]) || null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // auth — bez správného SHORTCUT_SECRET nic nedělej
    const auth = request.headers.get("Authorization") || "";
    if (!env.SHORTCUT_SECRET || auth !== `Bearer ${env.SHORTCUT_SECRET}`) {
      return json({ error: "unauthorized" }, 401);
    }

    const site = SITES[url.searchParams.get("site")] ? url.searchParams.get("site") : "automation";

    try {
      if (request.method === "GET" && url.pathname === "/status") {
        const gid = groupId(env, site);
        const [draft, group] = await Promise.all([
          latestDraft(env, site),
          gid ? ml(env, `/groups/${gid}`).catch(() => null) : null,
        ]);
        return json({
          site,
          draft: draft ? { id: draft.id, subject: subjectOf(draft) } : null,
          subscribers: group?.data?.active_count ?? null,
        });
      }

      if (request.method === "POST" && url.pathname === "/send") {
        const draft = await latestDraft(env, site);
        if (!draft) return json({ sent: false, reason: "Žádný čekající draft k odeslání." });
        await ml(env, `/campaigns/${draft.id}/schedule`, "POST", { delivery: "instant" });
        return json({ sent: true, subject: subjectOf(draft) });
      }

      // --- Digest (ping na iPhone): cloud routine zapisuje, telefon čte ---
      if (url.pathname === "/digest") {
        if (!env.DIGEST) return json({ error: "KV binding 'DIGEST' není nakonfigurováno" }, 500);
        const key = `latest:${site}`;

        if (request.method === "POST") {
          let body = {};
          try {
            body = await request.json();
          } catch {
            return json({ ok: false, reason: "tělo není JSON" }, 400);
          }
          const rec = {
            site,
            savedAt: new Date().toISOString(),
            date: typeof body.date === "string" ? body.date : new Date().toISOString().slice(0, 10),
            summary: typeof body.summary === "string" ? body.summary.slice(0, 500) : "",
            actions: Array.isArray(body.actions) ? body.actions.slice(0, 5).map((a) => String(a).slice(0, 200)) : [],
            full: typeof body.full === "string" ? body.full.slice(0, 20000) : "",
          };
          await env.DIGEST.put(key, JSON.stringify(rec));
          return json({ ok: true, site, date: rec.date });
        }

        if (request.method === "GET") {
          const raw = await env.DIGEST.get(key);
          return json(raw ? JSON.parse(raw) : { site, digest: null });
        }
      }

      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: String((e && e.message) || e) }, 500);
    }
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
