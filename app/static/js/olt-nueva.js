R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  // Marca -> modelos. «Otro» permite escribir un modelo que no esté en la lista.
  const catalog = await api("/catalog");
  $("vendor").add(new Option("Selecciona una marca", ""));
  for (const c of catalog) $("vendor").add(new Option(c.label, c.vendor));
  const OTHER = "__otro__";
  function syncModels() {
    const c = catalog.find(x => x.vendor === $("vendor").value);
    const sel = $("model-select"); sel.replaceChildren();
    sel.disabled = !c;
    if (c) {
      for (const m of c.models) sel.add(new Option(m, m));
      sel.add(new Option(c.models.length ? "Otro modelo…" : "Escribir modelo…", OTHER));
    }
    const note = $("vendor-note");
    note.classList.toggle("hidden", !c || c.implemented);
    note.textContent = c && !c.implemented ? `${c.label}: puedes registrar la OLT y generar sus scripts de MikroTik, pero autorizar ONUs en esta marca funcionará cuando esté lista su integración.` : "";
    syncOther();
  }
  function syncOther() {
    const other = $("model-select").value === OTHER;
    $("model-other-label").classList.toggle("hidden", !other);
    $("model-text").required = other;
    if (!other) $("model-text").value = $("model-select").value;
  }
  $("vendor").addEventListener("change", syncModels);
  $("model-select").addEventListener("change", syncOther);
  syncModels();
  const gws = await api("/gateways");
  for (const g of gws) $("gw-select").add(new Option(`Por VPN vía ${g.name}`, g.id));

  let wantTest = false;
  $("btn-save-test").addEventListener("click", () => { wantTest = true; });
  $("btn-save").addEventListener("click", () => { wantTest = false; });

  $("add-form").addEventListener("submit", async e => {
    e.preventDefault();
    const test = wantTest; wantTest = false;
    const body = Object.fromEntries(new FormData(e.target));
    body.model = $("model-select").value === OTHER ? $("model-text").value.trim() : $("model-select").value;
    for (const k of ["ssh_port", "telnet_port", "snmp_port"]) body[k] = Number(body[k]);
    body.gateway_id = body.gateway_id ? Number(body.gateway_id) : null;
    try {
      const olt = await api("/olts", { method: "POST", body: R.json(body) });
      if (!test) { location.href = "/static/olts.html"; return; }
      setMsg($("add-msg"), "OLT guardada. Probando conexión…", true);
      const r = await api(`/olts/${olt.id}/test`, { method: "POST" });
      $("test-result").replaceChildren(el("h3", { className: "sec", textContent: "Resultado de la conexión" }),
        ...r.checks.map(c => el("div", { className: "msg " + (c.reachable ? "ok" : c.reachable === false ? "bad" : ""), textContent: `${c.service.toUpperCase()} :${c.port} — ${c.detail}` })),
        el("p", {}, el("a", { className: "btn", href: "/static/olts.html", textContent: "Ir a la lista de OLTs" })));
    } catch (err) { setMsg($("add-msg"), err.message, false); }
  });
});
