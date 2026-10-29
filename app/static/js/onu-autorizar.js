R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  const id = Number(new URLSearchParams(location.search).get("id"));
  if (!id) { location.href = "/static/onus-sin-autorizar.html"; return; }
  let onu;
  try { onu = await api(`/onus/${id}`); } catch (e) { setMsg($("auth-msg"), e.message, false); return; }
  if (onu.status !== "pending") { setMsg($("auth-msg"), "Esta ONU ya no está pendiente.", false); return; }
  $("f-olt").value = onu.olt_name; $("f-sn").value = onu.serial; $("f-port").value = onu.pon_port;
  if (onu.onu_model) document.querySelector("[name=onu_model]").value = onu.onu_model;

  // Pestañas
  for (const b of $("tabs").querySelectorAll("button")) b.addEventListener("click", () => {
    for (const x of $("tabs").querySelectorAll("button")) x.classList.toggle("active", x === b);
    for (const p of document.querySelectorAll(".tab-panel")) p.classList.toggle("active", p.id === b.dataset.tab);
  });

  // VLANs: las que existen en la OLT; si el adaptador de la marca aún no las lista, se escribe a mano.
  let vlanInput = $("f-vlan");
  try {
    const vlans = await api(`/olts/${onu.olt_id}/vlans`);
    R.fillSelect(vlanInput, vlans, v => String(v), v => v);
  } catch (e) {
    const manual = el("input", { name: "vlan", type: "number", min: 1, max: 4094, required: true, placeholder: "ID de VLAN" });
    vlanInput.replaceWith(manual); vlanInput = manual;
    manual.parentElement.append(el("span", { className: "hint", textContent: e.status === 501 ? "Esta marca aún no lista VLANs: escríbela." : e.message }));
  }

  // Planes y perfiles
  const plans = await api("/speed-plans");
  R.fillSelect($("f-plan"), plans, p => `${p.name} (↓${p.down_kbps / 1000} / ↑${p.up_kbps / 1000} Mbps)`, p => p.id, "Sin plan propio");
  let prof = { supported: false };
  try { prof = await api(`/olts/${onu.olt_id}/profiles`); } catch { /* sin perfiles */ }
  R.fillSelect($("f-line"), prof.line_profiles, x => x, x => x, "—");
  R.fillSelect($("f-down"), prof.down_profiles, x => x, x => x, "—");
  R.fillSelect($("f-up"), prof.up_profiles, x => x, x => x, "—");
  $("adv-note").textContent = prof.supported ? "Perfiles leídos de la OLT." : "Esta marca aún no expone sus perfiles: usa un plan propio.";
  $("f-adv").disabled = !prof.supported;
  $("f-adv").addEventListener("change", () => $("adv-box").classList.toggle("hidden", !$("f-adv").checked));
  $("f-limit").addEventListener("change", () => $("limit-box").classList.toggle("hidden", !$("f-limit").checked));

  // Zona y NAP (el NAP se filtra por zona)
  const [zones, naps] = [await api("/zones"), await api("/naps")];
  R.fillSelect($("f-zone"), zones, z => z.name, z => z.id, "Selecciona una zona");
  const fillNaps = () => R.fillSelect($("f-nap"), naps.filter(n => !$("f-zone").value || n.zone_id === Number($("f-zone").value) || n.zone_id === null), n => n.name, n => n.id, "Selecciona un NAP");
  $("f-zone").addEventListener("change", fillNaps); fillNaps();

  $("auth-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const num = k => (f[k] ? Number(f[k]) : null);
    const limit = $("f-limit").checked, adv = limit && $("f-adv").checked;
    const body = {
      customer_name: f.customer_name, customer_ref: f.customer_ref || "", customer_phone: f.customer_phone || "",
      customer_address: f.customer_address || "", onu_model: f.onu_model || "", config_type: f.config_type,
      vlan: Number(f.vlan), svlan: num("svlan"),
      speed_plan_id: limit && !adv ? num("speed_plan_id") : null,
      line_profile: adv ? (f.line_profile || "") : "", up_profile: adv ? (f.up_profile || "") : "", down_profile: adv ? (f.down_profile || "") : "",
      zone_id: num("zone_id"), nap_id: num("nap_id"), comments: f.comments || "",
    };
    if (limit && !adv && !body.speed_plan_id) { setMsg($("auth-msg"), "Elige un plan de velocidad o desactiva «Limitar velocidad».", false); return; }
    setMsg($("auth-msg"), "Autorizando…", true);
    try {
      await api(`/onus/${id}/authorize`, { method: "POST", body: R.json(body) });
      location.href = "/static/onus-autorizadas.html";
    } catch (err) { setMsg($("auth-msg"), err.message, false); }
  });
});
