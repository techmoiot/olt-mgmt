R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  const delBtn = (path, msg, reload) => {
    const b = el("button", { textContent: "Eliminar", className: "danger" });
    b.onclick = async () => { try { await api(path, { method: "DELETE" }); reload(); } catch (e) { setMsg(msg, e.message, false); } };
    return b;
  };
  async function load() {
    const [zones, naps] = [await api("/zones"), await api("/naps")];
    const zname = Object.fromEntries(zones.map(z => [z.id, z.name]));
    R.fillSelect($("nap-zone"), zones, z => z.name, z => z.id, "Sin zona");
    R.table($("zones"), zones, $("zones-empty"), (tr, z) => { tr.insertCell().textContent = z.name; tr.insertCell().append(delBtn(`/zones/${z.id}`, $("zone-msg"), load)); });
    R.table($("naps"), naps, $("naps-empty"), (tr, n) => {
      tr.insertCell().textContent = n.name; tr.insertCell().textContent = zname[n.zone_id] || "—";
      tr.insertCell().append(delBtn(`/naps/${n.id}`, $("nap-msg"), load));
    });
  }
  $("zone-form").addEventListener("submit", async e => {
    e.preventDefault();
    try { await api("/zones", { method: "POST", body: R.json(Object.fromEntries(new FormData(e.target))) }); e.target.reset(); setMsg($("zone-msg"), "Zona agregada", true); load(); }
    catch (err) { setMsg($("zone-msg"), err.message, false); }
  });
  $("nap-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target)); f.zone_id = f.zone_id ? Number(f.zone_id) : null;
    try { await api("/naps", { method: "POST", body: R.json(f) }); e.target.reset(); setMsg($("nap-msg"), "NAP agregado", true); load(); }
    catch (err) { setMsg($("nap-msg"), err.message, false); }
  });
  load();
});
