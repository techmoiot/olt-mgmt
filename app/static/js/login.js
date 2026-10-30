(async function () {
  const { $, api, setMsg } = R;
  $("wordmark").prepend(R.logo(30));
  // Si ya hay una sesión válida, directo al panel.
  try {
    const me = await (await fetch("/auth/me", { credentials: "same-origin" })).json();
    if (me && me.username) { location.href = me.must_change_password ? "/static/cambiar-clave.html?forzado=1" : "/static/dashboard.html"; return; }
  } catch { /* sin sesión */ }
  $("login-form").addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const s = await api("/auth/login", { method: "POST", body: R.json(Object.fromEntries(new FormData(e.target))) });
      location.href = s.must_change_password ? "/static/cambiar-clave.html?forzado=1" : "/static/dashboard.html";
    } catch (err) { setMsg($("login-msg"), err.message, false); }
  });
})();
