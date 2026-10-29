R.ready.then(async () => {
  const { $, el, api } = R;
  const card = (n, label, cls = "") => el("div", { className: "stat " + cls }, el("div", { className: "n", textContent: n }), el("div", { className: "l", textContent: label }));
  async function load() {
    const d = await api("/dashboard");
    $("stats-onus").replaceChildren(card(d.onus_total, "En el sistema"), card(d.pending, "Sin autorizar", d.pending ? "warn" : ""), card(d.olts, "OLTs"));
    $("stats-state").replaceChildren(card(d.online, "Activas", "ok"), card(d.offline, "Fuera de línea", d.offline ? "bad" : ""), card(d.low_signal, "Baja señal", d.low_signal ? "warn" : ""), card(d.suspended, "Suspendidas"));
    $("stats-auth").replaceChildren(card(d.authorized, "Autorizadas en total"), card(d.authorized_today, "Hoy"), card(d.authorized_month, "Este mes"));
    $("updated").textContent = "Última actualización: " + new Date().toLocaleTimeString();
  }
  $("refresh").addEventListener("click", load);
  load();
});
