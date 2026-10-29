R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  for (const v of await api("/vendors")) $("vendor").add(new Option(v, v));
  const gws = await api("/gateways");
  for (const g of gws) $("gw-select").add(new Option(`Por VPN vía ${g.name}`, g.id));

  let wantTest = false;
  $("btn-save-test").addEventListener("click", () => { wantTest = true; });
  $("btn-save").addEventListener("click", () => { wantTest = false; });

  $("add-form").addEventListener("submit", async e => {
    e.preventDefault();
    const test = wantTest; wantTest = false;
    const body = Object.fromEntries(new FormData(e.target));
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
