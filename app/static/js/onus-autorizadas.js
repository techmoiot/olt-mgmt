R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  const [olts, plans] = [await api("/olts"), await api("/speed-plans")];
  const planName = Object.fromEntries(plans.map(p => [p.id, p.name]));
  R.fillSelect($("olt-filter"), olts, o => o.name, o => o.id, "Todas las OLTs");
  R.bindSearch($("search"), $("rows"));

  async function load() {
    const q = $("olt-filter").value ? `&olt_id=${$("olt-filter").value}` : "";
    const st = $("state-filter").value;
    let onus = [];
    for (const s of st ? [st] : ["authorized", "suspended"]) onus = onus.concat(await api(`/onus?status=${s}` + q));
    R.table($("rows"), onus, $("empty"), (tr, o) => {
      tr.insertCell().append(el("div", { textContent: o.customer_name || "—" }), el("div", { className: "hint", textContent: o.customer_ref }));
      tr.insertCell().textContent = o.olt_name;
      tr.insertCell().textContent = o.serial;
      tr.insertCell().textContent = `${o.pon_port} / ${o.onu_id ?? "—"}`;
      tr.insertCell().textContent = o.svlan ? `${o.vlan} / S${o.svlan}` : (o.vlan ?? "—");
      tr.insertCell().textContent = o.speed_plan_id ? (planName[o.speed_plan_id] || "plan") : (o.down_profile || o.up_profile ? `${o.down_profile || "—"} / ${o.up_profile || "—"}` : "sin límite");
      tr.insertCell().textContent = o.rx_power_dbm || "—";
      tr.insertCell().append(el("span", { className: "pill " + (o.status === "suspended" ? "bad" : "ok"), textContent: o.status === "suspended" ? "suspendida" : "activa" }));
      const act = tr.insertCell(); act.className = "row-actions";
      const run = async (path, method = "POST") => {
        try { await api(path, { method }); load(); } catch (e) { setMsg($("msg"), e.message, false); }
      };
      const susp = o.status === "suspended";
      const b = el("button", { textContent: susp ? "Reactivar" : "Suspender" });
      b.onclick = () => { if (susp || confirm(`¿Suspender el servicio de ${o.customer_name || o.serial}?`)) run(`/onus/${o.id}/${susp ? "resume" : "suspend"}`); };
      act.append(b);
      if (R.isAdmin()) {
        const d = el("button", { textContent: "Eliminar", className: "danger" });
        d.onclick = () => { if (confirm(`¿Eliminar la ONU ${o.serial} de la OLT? El cliente perderá el servicio.`)) run(`/onus/${o.id}`, "DELETE"); };
        act.append(d);
      }
    });
  }
  $("btn-go").addEventListener("click", load);
  load();
});
