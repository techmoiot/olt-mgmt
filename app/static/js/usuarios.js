R.ready.then(async () => {
  const { $, el, api, setMsg } = R;
  async function load() {
    const users = await api("/users");
    R.table($("users"), users, null, (tr, u) => {
      tr.insertCell().textContent = u.username + (u.username === R.session.username ? " (tú)" : "");
      tr.insertCell().textContent = u.role === "admin" ? "administrador" : "operador";
      tr.insertCell().textContent = (u.active ? "activo" : "desactivado") + (u.must_change_password ? " · contraseña temporal" : "");
      tr.insertCell().textContent = u.last_login_at ? R.fmtDate(u.last_login_at) : "nunca";
      const act = tr.insertCell(); act.className = "row-actions";
      const patch = async body => {
        try { await api(`/users/${u.id}`, { method: "PATCH", body: R.json(body) }); load(); } catch (err) { setMsg($("user-msg"), err.message, false); }
      };
      const bAct = el("button", { textContent: u.active ? "Desactivar" : "Activar" }); bAct.onclick = () => patch({ active: !u.active });
      const bRole = el("button", { textContent: u.role === "admin" ? "Pasar a operador" : "Pasar a admin" }); bRole.onclick = () => patch({ role: u.role === "admin" ? "operator" : "admin" });
      const bReset = el("button", { textContent: "Restablecer contraseña" });
      bReset.onclick = async () => {
        const pw = prompt(`Nueva contraseña temporal para ${u.username} (mínimo 10 caracteres):`);
        if (!pw) return;
        try { await api(`/users/${u.id}/reset-password`, { method: "POST", body: R.json({ new_password: pw }) }); setMsg($("user-msg"), "Contraseña restablecida", true); load(); }
        catch (err) { setMsg($("user-msg"), err.message, false); }
      };
      act.append(bAct, bRole, bReset);
    });
  }
  $("user-form").addEventListener("submit", async e => {
    e.preventDefault();
    try { await api("/users", { method: "POST", body: R.json(Object.fromEntries(new FormData(e.target))) }); e.target.reset(); setMsg($("user-msg"), "Usuario creado", true); load(); }
    catch (err) { setMsg($("user-msg"), err.message, false); }
  });
  load();
});
