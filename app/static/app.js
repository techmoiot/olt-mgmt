let currentOlt = null, currentGw = null;
const $ = id => document.getElementById(id);

function el(tag, props = {}, ...kids) {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids);
  return e;
}
function setMsg(node, text, ok) { node.textContent = text; node.className = "msg " + (ok ? "ok" : "bad"); }

let session = null;   // {username, role, csrf_token, must_change_password}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (session && opts.method && opts.method !== "GET") headers["X-CSRF-Token"] = session.csrf_token;
  const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/auth/login") { session = null; showView("login"); throw new Error("Sesión vencida: vuelve a entrar"); }
  if (res.status === 403 && data.code === "password_change_required") { showView("password", true); throw new Error(data.detail); }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d
      : Array.isArray(d) ? d.map(e => e.loc.slice(1).join(".") + ": " + e.msg).join("; ") : "Error " + res.status);
  }
  return data;
}

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

/* ---------- Gateways / VPN ---------- */
async function loadGateways() {
  if (!isAdmin()) return [];
  const gws = await api("/gateways");
  const tbody = $("gws"); tbody.replaceChildren();
  $("gw-empty").classList.toggle("hidden", gws.length > 0);
  const sel = $("gw-select"); const keep = sel.value;
  sel.replaceChildren(new Option("Directo (misma red)", ""));
  for (const g of gws) sel.add(new Option(`Por VPN vía ${g.name}`, g.id));
  sel.value = keep;

  for (const g of gws) {
    const tr = tbody.insertRow();
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
        try {
          await api(`/gateways/${g.id}/router-key`, { method: "PUT", body: JSON.stringify({ public_key: input.value.trim() }) });
          loadGateways();
        } catch (e) { setMsg(msg, e.message, false); }
      };
      st.append(el("div", { className: "msg bad", textContent: "Falta la clave pública del MikroTik" }), input, " ", save, msg);
    }
    const act = tr.insertCell(); act.className = "row-actions";
    const bScript = el("button", { textContent: "Script VPN" });
    bScript.onclick = () => { currentGw = g; $("vpn-name").textContent = g.name; $("vpn-card").classList.remove("hidden"); $("vpn-card").scrollIntoView({ behavior: "smooth" }); };
    const bDel = el("button", { textContent: "Eliminar", className: "danger" });
    bDel.onclick = async () => {
      if (!confirm(`¿Quitar "${g.name}" del sistema?`)) return;
      try { await api(`/gateways/${g.id}`, { method: "DELETE" }); loadGateways(); }
      catch (e) { alert(e.message); }
    };
    act.append(bScript, bDel);
  }
}

$("gw-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  body.listen_port = Number(body.listen_port) || 13231;
  if (!body.tunnel_net) delete body.tunnel_net;
  try {
    await api("/gateways", { method: "POST", body: JSON.stringify(body) });
    e.target.reset(); $("gw-form").elements.listen_port.value = 13231;
    setMsg($("gw-msg"), "MikroTik agregado", true); loadGateways();
  } catch (err) { setMsg($("gw-msg"), err.message, false); }
});

$("vpn-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  if (!body.server_public_ip) delete body.server_public_ip;
  try {
    const r = await api(`/gateways/${currentGw.id}/vpn-script`, { method: "POST", body: JSON.stringify(body) });
    showOutput(`Script VPN: ${currentGw.name}`, r); setMsg($("vpn-msg"), "Script generado", true);
  } catch (err) { setMsg($("vpn-msg"), err.message, false); }
});

/* ---------- OLTs ---------- */
async function loadVendors() {
  $("vendor").replaceChildren();
  for (const v of await api("/vendors")) $("vendor").add(new Option(v, v));
}

async function loadOlts() {
  const tbody = $("olts"); tbody.replaceChildren();
  const [olts, gws] = [await api("/olts"), isAdmin() ? await api("/gateways") : []];
  const gwName = Object.fromEntries(gws.map(g => [g.id, g.name]));
  $("empty").classList.toggle("hidden", olts.length > 0);
  for (const o of olts) {
    const tr = tbody.insertRow();
    tr.insertCell().textContent = o.name;
    tr.insertCell().textContent = o.vendor + (o.model ? " " + o.model : "");
    const acc = tr.insertCell();
    acc.append(el("div", { textContent: `${o.host} · ${o.cli_protocol.toUpperCase()} :${o.cli_protocol === "ssh" ? o.ssh_port : o.telnet_port}` }),
      el("div", { className: "hint", textContent: `SNMP :${o.snmp_port} ${o.has_snmp_read ? "· lectura" : ""} ${o.has_snmp_write ? "· escritura" : ""}` }),
      el("div", { className: "hint", textContent: o.gateway_id ? `VPN vía ${gwName[o.gateway_id] || "?"}` : "Acceso directo" }));
    const st = tr.insertCell(); st.className = "msg"; st.textContent = "—";
    const act = tr.insertCell(); act.className = "row-actions";

    const bTest = el("button", { textContent: "Probar conexión" });
    bTest.onclick = async () => {
      st.className = "msg"; st.textContent = "probando…";
      try {
        const r = await api(`/olts/${o.id}/test`, { method: "POST" });
        st.replaceChildren(...r.checks.map(c => el("div", {
          className: "msg " + (c.reachable ? "ok" : c.reachable === false ? "bad" : ""),
          textContent: `${c.service.toUpperCase()} :${c.port} ${c.reachable ? "responde" + (c.latency_ms != null ? ` (${c.latency_ms} ms)` : "") : c.reachable === false ? "sin respuesta" : "no comprobado"}`,
        })));
      } catch (e) { setMsg(st, e.message, false); }
    };
    act.append(bTest);
    if (isAdmin()) {
      const bMk = el("button", { textContent: "Script MikroTik" });
      bMk.onclick = () => openOltScript(o);
      const bDel = el("button", { textContent: "Eliminar", className: "danger" });
      bDel.onclick = async () => {
        if (!confirm(`¿Quitar "${o.name}" del sistema? No toca la OLT física.`)) return;
        try { await api(`/olts/${o.id}`, { method: "DELETE" }); loadOlts(); loadGateways(); }
        catch (e) { setMsg(st, e.message, false); }
      };
      act.append(bMk, bDel);
    }
  }
}

$("add-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  for (const k of ["ssh_port", "telnet_port", "snmp_port"]) body[k] = Number(body[k]);
  body.gateway_id = body.gateway_id ? Number(body.gateway_id) : null;
  try {
    await api("/olts", { method: "POST", body: JSON.stringify(body) });
    e.target.reset(); setMsg($("add-msg"), "OLT agregada", true); loadOlts(); loadGateways();
  } catch (err) { setMsg($("add-msg"), err.message, false); }
});

function openOltScript(olt) {
  currentOlt = olt;
  $("olt-script-name").textContent = olt.name;
  // Con VPN el origen es la IP del servidor dentro del túnel, no hace falta pedirla.
  $("system-ip-label").classList.toggle("hidden", !!olt.gateway_id);
  $("olt-script-card").classList.remove("hidden");
  $("olt-script-card").scrollIntoView({ behavior: "smooth" });
}

$("olt-script-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  body.vlan_id = Number(body.vlan_id); body.prefix = Number(body.prefix);
  body.masquerade = e.target.elements.masquerade.checked;
  if (!body.system_ip || currentOlt.gateway_id) delete body.system_ip;
  try {
    const r = await api(`/olts/${currentOlt.id}/mikrotik-script`, { method: "POST", body: JSON.stringify(body) });
    showOutput(`Script de VLAN y firewall: ${currentOlt.name}`, r); setMsg($("olt-script-msg"), "Script generado", true);
  } catch (err) { setMsg($("olt-script-msg"), err.message, false); }
});


/* ---------- Sesión: login, cambio de contraseña, usuarios ---------- */
const isAdmin = () => !!session && session.role === "admin";

function showView(name, forced = false) {
  for (const v of ["login", "password", "app"]) $("view-" + v).classList.toggle("hidden", v !== name);
  if (name === "password") {
    $("pw-title").textContent = forced ? "Debes cambiar tu contraseña" : "Cambiar contraseña";
    $("pw-sub").textContent = forced ? "Tu contraseña es temporal. Elige una nueva para continuar." : "Al cambiarla se cierran tus otras sesiones.";
    $("pw-cancel").classList.toggle("hidden", forced);
    $("pw-form").reset(); $("pw-msg").textContent = "";
  }
  if (name === "login") { $("login-form").reset(); document.body.classList.remove("is-admin"); }
}

async function enterApp() {
  if (session.must_change_password) { showView("password", true); return; }
  document.body.classList.toggle("is-admin", isAdmin());
  $("who-name").textContent = session.username;
  $("who-role").textContent = isAdmin() ? "administrador" : "operador";
  showView("app");
  await loadVendors();
  await loadGateways();
  await loadOlts();
  if (isAdmin()) await loadUsers();
}

$("login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    session = await api("/auth/login", { method: "POST", body: JSON.stringify(body) });
    $("login-msg").textContent = "";
    await enterApp();
  } catch (err) { setMsg($("login-msg"), err.message, false); }
});

$("btn-logout").addEventListener("click", async () => {
  try { await api("/auth/logout", { method: "POST" }); } catch { /* ya estaba cerrada */ }
  session = null; showView("login");
});

$("btn-pw").addEventListener("click", () => showView("password", false));
$("pw-cancel").addEventListener("click", () => showView("app"));

$("pw-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  if (f.new_password !== f.repeat) { setMsg($("pw-msg"), "Las contraseñas nuevas no coinciden", false); return; }
  try {
    await api("/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: f.current_password, new_password: f.new_password }) });
    session.must_change_password = false;
    await enterApp();
  } catch (err) { setMsg($("pw-msg"), err.message, false); }
});

async function loadUsers() {
  const users = await api("/users");
  const tbody = $("users"); tbody.replaceChildren();
  for (const u of users) {
    const tr = tbody.insertRow();
    tr.insertCell().textContent = u.username + (u.username === session.username ? " (tú)" : "");
    tr.insertCell().textContent = u.role === "admin" ? "administrador" : "operador";
    tr.insertCell().textContent = (u.active ? "activo" : "desactivado") + (u.must_change_password ? " · contraseña temporal" : "");
    tr.insertCell().textContent = u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "nunca";
    const act = tr.insertCell(); act.className = "row-actions";
    const patch = async body => {
      try { await api(`/users/${u.id}`, { method: "PATCH", body: JSON.stringify(body) }); loadUsers(); }
      catch (err) { setMsg($("user-msg"), err.message, false); }
    };
    const bAct = el("button", { textContent: u.active ? "Desactivar" : "Activar" });
    bAct.onclick = () => patch({ active: !u.active });
    const bRole = el("button", { textContent: u.role === "admin" ? "Pasar a operador" : "Pasar a admin" });
    bRole.onclick = () => patch({ role: u.role === "admin" ? "operator" : "admin" });
    const bReset = el("button", { textContent: "Restablecer contraseña" });
    bReset.onclick = async () => {
      const pw = prompt(`Nueva contraseña temporal para ${u.username} (mínimo 10 caracteres):`);
      if (!pw) return;
      try { await api(`/users/${u.id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: pw }) }); setMsg($("user-msg"), "Contraseña restablecida", true); loadUsers(); }
      catch (err) { setMsg($("user-msg"), err.message, false); }
    };
    act.append(bAct, bRole, bReset);
  }
}

$("user-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    await api("/users", { method: "POST", body: JSON.stringify(body) });
    e.target.reset(); setMsg($("user-msg"), "Usuario creado", true); loadUsers();
  } catch (err) { setMsg($("user-msg"), err.message, false); }
});

(async function boot() {
  try { session = await api("/auth/me"); await enterApp(); }
  catch { if (!session) showView("login"); }
})();
