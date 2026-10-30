R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  const [olts, plans] = [await api("/olts"), await api("/speed-plans")];
  const short = n => (n ? n.split(" - ")[0].replace(/^ADMINOLT_/, "").replace(/_[DU]$/, "") : "—");
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
      const sn = tr.insertCell(); sn.className = "sn"; sn.textContent = o.serial;
      tr.insertCell().textContent = `${o.pon_port} / ${o.onu_id ?? "—"}`;
      tr.insertCell().textContent = o.svlan ? `${o.vlan} / S${o.svlan}` : (o.vlan ?? "—");
      tr.insertCell().textContent = o.speed_plan_id ? (planName[o.speed_plan_id] || "plan") : (o.down_profile || o.up_profile ? `↓${short(o.down_profile)} ↑${short(o.up_profile)}` : "sin límite");
      tr.insertCell().append(R.signal(o.rx_power_dbm));
      const susp0 = o.status === "suspended"; tr.insertCell().append(susp0 ? R.pill("Suspendida", "warn") : o.oper_state === "offline" ? R.pill("Fuera de línea", "bad") : R.pill("Activa", "ok"));
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
