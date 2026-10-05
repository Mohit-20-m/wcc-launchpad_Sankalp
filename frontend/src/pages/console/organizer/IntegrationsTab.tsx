import { useEffect, useState } from "react";
import { Copy, KeyRound, RefreshCw, Trash2, Webhook } from "lucide-react";
import { api, type EventOut, type WebhookOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtAgo, fmtDateTime } from "../../../lib/format";

interface Props {
  event: EventOut;
  flash: (kind: "ok" | "error", text: string) => void;
}

const copy = (text: string, flash: Props["flash"]) =>
  navigator.clipboard?.writeText(text).then(() => flash("ok", "Copied."), () => flash("error", "Couldn't copy. Select it and copy manually."));

function ApiKeys({ event, flash }: Props) {
  const q = useLoad(() => api.apiKeys(event.id), [event.id]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write">("read");
  const [days, setDays] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const k = await api.createApiKey(event.id, { name: name.trim(), scope, ...(days ? { expires_in_days: Number(days) } : {}) });
      setFresh(k.key);
      setName("");
      q.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const keys = q.data ?? [];
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>API keys</h2>
          <p>
            Let scripts and dashboards use the REST API for <strong>this event only</strong>. Read keys can only fetch data; write keys can also change
            it. Docs: <a className="link-cyan" href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a>.
          </p>
        </div>
        <KeyRound size={18} />
      </div>
      <div className="form-grid">
        <div className="field"><label htmlFor="key-name">Key name</label><input id="key-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Grafana dashboard" /></div>
        <div className="field">
          <label htmlFor="key-scope">Access</label>
          <select id="key-scope" value={scope} onChange={(e) => setScope(e.target.value as "read" | "write")}>
            <option value="read">Read only</option>
            <option value="write">Read and write</option>
          </select>
        </div>
        <div className="field"><label htmlFor="key-days">Expires in (days, optional)</label><input id="key-days" type="number" min={1} max={365} value={days} onChange={(e) => setDays(e.target.value)} /></div>
      </div>
      <div className="row-actions" style={{ marginTop: 12 }}>
        <button className="btn btn--acid btn--sm" type="button" disabled={busy || !name.trim()} onClick={create}>Create API key</button>
      </div>
      {fresh ? (
        <div style={{ marginTop: 14 }}>
          <Notice kind="ok" title="Copy this key now. It won't be shown again.">
            Only a fingerprint is stored, so we can't recover it.
          </Notice>
          <div className="copy-box" style={{ marginTop: 8 }}>
            <span data-testid="new-api-key">{fresh}</span>
            <button className="btn btn--ghost btn--sm" type="button" onClick={() => copy(fresh, flash)}><Copy size={13} /> Copy</button>
          </div>
          <p className="panel-note">Try it: <code>curl -H "Authorization: Bearer {fresh.slice(0, 10)}…" {window.location.origin}/api/events/{event.id}/stats</code></p>
        </div>
      ) : null}
      {keys.length > 0 ? (
        <div className="tablewrap" style={{ marginTop: 14 }}>
          <table className="data">
            <thead><tr><th>Name</th><th>Access</th><th>Key</th><th>Last used</th><th>Expires</th><th /></tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td><strong>{k.name}</strong></td>
                  <td>{k.scope}</td>
                  <td><code>{k.prefix}…</code></td>
                  <td>{k.last_used_at ? fmtAgo(k.last_used_at) : "never"}</td>
                  <td>{k.revoked ? <span className="chip chip--ghost">REVOKED</span> : k.expires_at ? fmtDateTime(k.expires_at) : "never"}</td>
                  <td>
                    {!k.revoked ? (
                      <button className="btn btn--ghost btn--sm" type="button" onClick={() => window.confirm(`Revoke "${k.name}"? Anything using it stops working.`) && api.revokeApiKey(event.id, k.id).then(() => q.reload()).catch((e) => flash("error", errorText(e)))}>
                        Revoke
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Deliveries({ event, hook, flash }: { event: EventOut; hook: WebhookOut; flash: Props["flash"] }) {
  const q = useLoad(() => api.webhookDeliveries(event.id, hook.id), [event.id, hook.id], { pollMs: 4000 });
  const rows = q.data ?? [];
  if (rows.length === 0) return <p className="panel-note">No deliveries yet. Send a test.</p>;
  return (
    <div className="tablewrap">
      <table className="data">
        <thead><tr><th>When</th><th>Event</th><th>Status</th><th>Tries</th><th>HTTP</th><th>Detail</th><th /></tr></thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id}>
              <td title={fmtDateTime(d.created_at)}>{fmtAgo(d.created_at)}</td>
              <td><code>{d.event_type}</code></td>
              <td><span className={`chip ${d.status === "success" ? "chip--acid" : d.status === "failed" ? "chip--coral" : "chip--ghost"}`}>{d.status.toUpperCase()}</span></td>
              <td>{d.attempts}</td>
              <td>{d.response_code ?? "—"}</td>
              <td>{d.error ?? (d.duration_ms != null ? `${d.duration_ms} ms` : "—")}</td>
              <td>{d.status === "failed" ? <button className="btn btn--ghost btn--sm" type="button" onClick={() => api.retryDelivery(event.id, hook.id, d.id).then(() => q.reload()).catch((e) => flash("error", errorText(e)))}><RefreshCw size={12} /> Retry</button> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Webhooks({ event, flash }: Props) {
  const q = useLoad(() => api.webhooks(event.id), [event.id]);
  const typesQ = useLoad(api.webhookEventTypes, []);
  const [url, setUrl] = useState("");
  const [chosen, setChosen] = useState<string[]>([]); // empty = all events
  const [secretShown, setSecretShown] = useState<{ id: string; secret: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setSecretShown(null), [event.id]);

  const create = async () => {
    setBusy(true);
    try {
      const h = await api.createWebhook(event.id, { url: url.trim(), events: chosen.length ? chosen : ["*"] });
      setSecretShown({ id: h.id, secret: h.secret! });
      setUrl("");
      setChosen([]);
      q.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const act = async (fn: () => Promise<unknown>, okText: string) => {
    try {
      await fn();
      flash("ok", okText);
      q.reload();
    } catch (err) {
      flash("error", errorText(err));
    }
  };
  const hooks = q.data ?? [];
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Webhooks</h2>
          <p>
            We POST a signed JSON message to your URL when things happen (a submission, a round closing, results published…). Failed deliveries retry
            automatically; an endpoint that keeps failing is paused.
          </p>
        </div>
        <Webhook size={18} />
      </div>
      <div className="form-grid">
        <div className="field span-2"><label htmlFor="wh-url">Endpoint URL</label><input id="wh-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.org/hooks/launchpad" /></div>
        <div className="field span-2">
          <label>Send me</label>
          <div className="check-grid">
            <label><input type="checkbox" checked={chosen.length === 0} onChange={() => setChosen([])} /> Everything</label>
            {(typesQ.data ?? []).filter((t) => t !== "webhook.test").map((t) => (
              <label key={t}>
                <input type="checkbox" checked={chosen.includes(t)} onChange={(e) => setChosen(e.target.checked ? [...chosen, t] : chosen.filter((x) => x !== t))} /> {t}
              </label>
            ))}
          </div>
        </div>
      </div>
      <div className="row-actions" style={{ marginTop: 12 }}>
        <button className="btn btn--acid btn--sm" type="button" disabled={busy || !url.trim()} onClick={create}>Add webhook</button>
      </div>
      {secretShown ? (
        <div style={{ marginTop: 14 }}>
          <Notice kind="ok" title="Signing secret. Copy it now; it won't be shown again.">
            Verify each request: <code>HMAC-SHA256(secret, timestamp + "." + body)</code> must equal the <code>v1</code> value in the{" "}
            <code>X-Launchpad-Signature</code> header, and reject old timestamps.
          </Notice>
          <div className="copy-box" style={{ marginTop: 8 }}>
            <span data-testid="new-webhook-secret">{secretShown.secret}</span>
            <button className="btn btn--ghost btn--sm" type="button" onClick={() => copy(secretShown.secret, flash)}><Copy size={13} /> Copy</button>
          </div>
        </div>
      ) : null}

      <div className="stack" style={{ marginTop: 16 }}>
        {hooks.length === 0 && !q.loading ? <div className="emptystate">No webhooks yet.</div> : null}
        {hooks.map((h) => (
          <div className="panel" key={h.id} style={{ margin: 0 }} aria-label={`Webhook ${h.url}`}>
            <div className="panel-head">
              <div>
                <h2 style={{ fontSize: 15, overflowWrap: "anywhere" }}>{h.url}</h2>
                <p>{h.events[0] === "*" ? "All events" : h.events.join(", ")} · secret {h.secret_hint}</p>
                {h.disabled_reason ? <p style={{ color: "var(--coral)" }}>{h.disabled_reason}</p> : null}
              </div>
              <span className={`chip ${h.active ? "chip--acid" : "chip--coral"}`}>{h.active ? "ACTIVE" : "PAUSED"}</span>
            </div>
            <div className="row-actions">
              <button className="btn btn--cyan btn--sm" type="button" disabled={!h.active} onClick={() => void act(() => api.testWebhook(event.id, h.id), "Test sent. See the delivery log.")}>Send test</button>
              <button className="btn btn--ghost btn--sm" type="button" onClick={() => void act(() => api.patchWebhook(event.id, h.id, { active: !h.active }), h.active ? "Paused." : "Resumed.")}>{h.active ? "Pause" : "Resume"}</button>
              <button className="btn btn--ghost btn--sm" type="button" onClick={() => window.confirm("Rotate the secret? The old one stops working immediately.") && void api.rotateWebhookSecret(event.id, h.id).then((r) => { setSecretShown({ id: h.id, secret: r.secret! }); q.reload(); }).catch((e) => flash("error", errorText(e)))}>Rotate secret</button>
              <button className="btn btn--ghost btn--sm" type="button" onClick={() => setOpen(open === h.id ? null : h.id)} aria-expanded={open === h.id}>Deliveries</button>
              <button className="btn btn--ghost btn--sm" type="button" aria-label={`Delete webhook ${h.url}`} onClick={() => window.confirm("Delete this webhook?") && void act(() => api.deleteWebhook(event.id, h.id), "Webhook deleted.")}><Trash2 size={13} /></button>
            </div>
            {open === h.id ? <div style={{ marginTop: 12 }}><Deliveries event={event} hook={h} flash={flash} /></div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export function IntegrationsTab({ event, flash }: Props) {
  return (
    <>
      <ApiKeys event={event} flash={flash} />
      <Webhooks event={event} flash={flash} />
    </>
  );
}
