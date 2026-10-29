(async function () {
  const { $, api, setMsg } = R;
  let me;
  try { me = await (await fetch("/auth/me", { credentials: "same-origin" })).json(); } catch { me = null; }
  if (!me || !me.username) { location.href = "/"; return; }
  R.session = me;
  const forced = new URLSearchParams(location.search).has("forzado") || me.must_change_password;
  $("pw-title").textContent = forced ? "Debes cambiar tu contraseña" : "Cambiar contraseña";
  $("pw-sub").textContent = forced ? "Tu contraseña es temporal. Elige una nueva para continuar." : "Al cambiarla se cierran tus otras sesiones.";
  $("pw-cancel").classList.toggle("hidden", forced);
  $("pw-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    if (f.new_password !== f.repeat) { setMsg($("pw-msg"), "Las contraseñas nuevas no coinciden", false); return; }
    try {
      await api("/auth/change-password", { method: "POST", body: R.json({ current_password: f.current_password, new_password: f.new_password }) });
      location.href = "/static/dashboard.html";
    } catch (err) { setMsg($("pw-msg"), err.message, false); }
  });
})();
