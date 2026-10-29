R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  let currentGw = null, olts = [];

  function showOutput(title, r) {
    $("out-title").textContent = title;
    $("out-script").value = r.script;
    const ul = $("out-notes"); ul.replaceChildren();
    for (const n of r.notes) ul.append(el("li", { textContent: n }));
    $("out-card").classList.remove("hidden");
    $("out-card").scrollIntoView({ behavior: "smooth" });
  }
  $("out-copy").addEventListener("click", async () => {
    const ta = $("out-script");
    try { await navigator.clipboard.writeText(ta.value); setMsg($("copy-msg"), "Copiado", true); }
    catch { ta.select(); document.execCommand("copy"); }
  });

  /* ---------- MikroTik / VPN ---------- */
  async function loadGateways() {
    const gws = await api("/gateways");
    R.table($("gws"), gws, $("gw-empty"), (tr, g) => {
      tr.insertCell().textContent = g.name;
      tr.insertCell().textContent = `${g.endpoint}:${g.listen_port}/udp`;
      tr.insertCell().textContent = `${g.tunnel_net} (MikroTik ${g.router_ip} · servidor ${g.server_ip})`;
      const st = tr.insertCell();
      if (g.vpn_ready) {
        st.append(el("div", { className: "msg ok", textContent: "Clave del MikroTik registrada" }),
          el("div", { className: "hint" }, "En el servidor: ", el("code", { textContent: `python tools/wg_server_config.py ${g.id}` })));
      } else {
        const input = el("input", { placeholder: "Clave pública que imprime el script", size: 30 });
        const save = el("button", { textContent: "Guardar clave" });
        const msg = el("div", { className: "msg" });
        save.onclick = async () => {
          try { await api(`/gateways/${g.id}/router-key`, { method: "PUT", body: R.json({ public_key: input.value.trim() }) }); loadGateways(); }
          catch (e) { setMsg(msg, e.message, false); }
        };
        st.append(el("div", { className: "msg bad", textContent: "Falta la clave pública del MikroTik" }), input, " ", save, msg);
      }
      const act = tr.insertCell(); act.className = "row-actions";
      const bScript = el("button", { textContent: "Script VPN" });
      bScript.onclick = () => { currentGw = g; $("vpn-name").textContent = g.name; $("vpn-card").classList.remove("hidden"); $("vpn-card").scrollIntoView({ behavior: "smooth" }); };
      const bDel = el("button", { textContent: "Eliminar", className: "danger" });
      bDel.onclick = async () => {
        if (!confirm(`¿Quitar "${g.name}" del sistema?`)) return;
        try { await api(`/gateways/${g.id}`, { method: "DELETE" }); loadGateways(); } catch (e) { alert(e.message); }
      };
      act.append(bScript, bDel);
    });
  }

  $("gw-form").addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    body.listen_port = Number(body.listen_port) || 13231;
    if (!body.tunnel_net) delete body.tunnel_net;
    try {
      await api("/gateways", { method: "POST", body: R.json(body) });
      e.target.reset(); $("gw-form").elements.listen_port.value = 13231;
      setMsg($("gw-msg"), "MikroTik agregado", true); loadGateways();
    } catch (err) { setMsg($("gw-msg"), err.message, false); }
  });

  $("vpn-form").addEventListener("submit", async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    if (!body.server_public_ip) delete body.server_public_ip;
    try {
      const r = await api(`/gateways/${currentGw.id}/vpn-script`, { method: "POST", body: R.json(body) });
      showOutput(`Script VPN: ${currentGw.name}`, r); setMsg($("vpn-msg"), "Script generado", true);
    } catch (err) { setMsg($("vpn-msg"), err.message, false); }
  });

  /* ---------- Script de VLAN + firewall por OLT ---------- */
  function currentOlt() { return olts.find(o => String(o.id) === $("olt-select").value); }
  function syncSystemIp() {
    const o = currentOlt();
    // Con VPN el origen es la IP del servidor dentro del túnel, no hace falta pedirla.
    $("system-ip-label").classList.toggle("hidden", !!(o && o.gateway_id));
  }
  olts = await api("/olts");
  R.fillSelect($("olt-select"), olts, o => `${o.name} (${o.host})`, o => o.id);
  $("olt-select").addEventListener("change", syncSystemIp); syncSystemIp();

  $("olt-script-form").addEventListener("submit", async e => {
    e.preventDefault();
    const o = currentOlt();
    if (!o) { setMsg($("olt-script-msg"), "Primero agrega una OLT", false); return; }
    const body = Object.fromEntries(new FormData(e.target)); delete body.olt;
    body.vlan_id = Number(body.vlan_id); body.prefix = Number(body.prefix);
    body.masquerade = e.target.elements.masquerade.checked;
    if (!body.system_ip || o.gateway_id) delete body.system_ip;
    try {
      const r = await api(`/olts/${o.id}/mikrotik-script`, { method: "POST", body: R.json(body) });
      showOutput(`Script de VLAN y firewall: ${o.name}`, r); setMsg($("olt-script-msg"), "Script generado", true);
    } catch (err) { setMsg($("olt-script-msg"), err.message, false); }
  });

  loadGateways();
});
