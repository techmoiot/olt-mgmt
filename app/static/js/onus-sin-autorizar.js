R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  const olts = await api("/olts");
  R.fillSelect($("olt-filter"), olts, o => o.name, o => o.id, "Todas las OLTs");
  R.bindSearch($("search"), $("rows"));

  async function load() {
    const q = $("olt-filter").value ? `&olt_id=${$("olt-filter").value}` : "";
    const onus = await api("/onus?status=pending" + q);
    R.table($("rows"), onus, $("empty"), (tr, o) => {
      tr.insertCell().textContent = o.olt_name;
      tr.insertCell().textContent = o.pon_port;
      tr.insertCell().textContent = o.serial;
      tr.insertCell().textContent = o.onu_model || "—";
      tr.insertCell().textContent = o.rx_power_dbm || "—";
      tr.insertCell().append(el("a", { className: "btn primary", href: `/static/onu-autorizar.html?id=${o.id}`, textContent: "Autorizar" }));
    });
  }

  $("btn-scan").addEventListener("click", async () => {
    const targets = $("olt-filter").value ? olts.filter(o => String(o.id) === $("olt-filter").value) : olts;
    const problems = []; let found = 0;
    $("scan-msg").className = "msg"; $("scan-msg").textContent = "buscando…";
    for (const o of targets) {
      try { found += (await api(`/olts/${o.id}/scan`, { method: "POST" })).length; }
      catch (e) { problems.push(`${o.name}: ${e.message}`); }
    }
    setMsg($("scan-msg"), problems.length ? problems.join(" | ") : `${found} ONU(s) pendientes`, !problems.length);
    load();
  });
  $("olt-filter").addEventListener("change", load);
  load();
});
