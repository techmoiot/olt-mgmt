R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  async function load() {
    const [olts, gws] = [await api("/olts"), R.isAdmin() ? await api("/gateways") : []];
    const gwName = Object.fromEntries(gws.map(g => [g.id, g.name]));
    R.table($("olts"), olts, $("empty"), (tr, o) => {
      tr.insertCell().textContent = o.name;
      tr.insertCell().textContent = [o.vendor, o.model, o.software_version && "v" + o.software_version, o.pon_type.toUpperCase()].filter(Boolean).join(" · ");
      const acc = tr.insertCell();
      acc.append(el("div", { textContent: `${o.host} · ${o.cli_protocol.toUpperCase()} :${o.cli_port ?? (o.cli_protocol === "ssh" ? o.ssh_port : o.telnet_port)}` }),
        el("div", { className: "hint", textContent: `SNMP :${o.snmp_port}${o.has_snmp_read ? " · lectura" : ""}${o.has_snmp_write ? " · escritura" : ""}` }),
        el("div", { className: "hint", textContent: o.gateway_id ? `VPN vía ${gwName[o.gateway_id] || "MikroTik"}` : "Acceso directo" }));
      const st = tr.insertCell(); st.className = "msg"; st.textContent = "—";
      const act = tr.insertCell(); act.className = "row-actions";

      const bTest = el("button", { textContent: "Probar conexión" });
      bTest.onclick = async () => {
        st.className = "msg"; st.textContent = "probando…";
        try {
          if (!R.isAdmin()) throw new Error("La prueba de conexión es solo para administradores");
          const r = await api(`/olts/${o.id}/test`, { method: "POST" });
          st.replaceChildren(...r.checks.map(c => el("div", {
            className: "msg " + (c.reachable ? "ok" : c.reachable === false ? "bad" : ""),
            textContent: `${c.service.toUpperCase()} :${c.port} ${c.reachable ? "responde" + (c.latency_ms != null ? ` (${c.latency_ms} ms)` : "") : c.reachable === false ? "sin respuesta" : "no comprobado"}`,
          })));
        } catch (e) { setMsg(st, e.message, false); }
      };
      const bScan = el("button", { textContent: "Buscar ONUs" });
      bScan.onclick = async () => {
        st.className = "msg"; st.textContent = "buscando…";
        try { const r = await api(`/olts/${o.id}/scan`, { method: "POST" }); setMsg(st, `${r.length} ONU(s) sin autorizar`, true); }
        catch (e) { setMsg(st, e.message, false); }
      };
      act.append(bTest, bScan);
      if (R.isAdmin()) {
        const bDel = el("button", { textContent: "Eliminar", className: "danger" });
        bDel.onclick = async () => {
          if (!confirm(`¿Quitar "${o.name}" del sistema? No toca la OLT física.`)) return;
          try { await api(`/olts/${o.id}`, { method: "DELETE" }); load(); } catch (e) { setMsg(st, e.message, false); }
        };
        act.append(bDel);
      }
    });
  }
  load();
});
