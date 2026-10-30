R.ready.then(async () => {
  const { $, el, api } = R;
  async function load() {
    const d = await api("/dashboard");
    const unknown = Math.max(d.authorized - d.online - d.offline, 0);
    const segs = [
      ["seg-ok", d.online, "Activas"],
      ["seg-bad", d.offline, "Fuera de línea"],
      ["seg-idle", unknown, "Autorizadas sin lectura"],
      ["seg-warn", d.pending, "Sin autorizar"],
    ];
    $("hero-total").textContent = d.onus_total;
    const bar = $("fiberbar"); bar.replaceChildren();
    const total = segs.reduce((a, s) => a + s[1], 0);
    const addSeg = (cls, n) => { const d = el("div", { className: cls, title: String(n) }); d.style.flexGrow = n; bar.append(d); };
    for (const [cls, n] of segs) if (n > 0) addSeg(cls, n);
    if (!total) addSeg("seg-idle", 1);
    $("legend").replaceChildren(...segs.map(([cls, n, label]) =>
      el("div", {}, el("i", { className: "dot " + cls }), el("b", { textContent: n }), el("span", { textContent: label }))));
    const fact = (n, label, cls = "") => el("div", { className: "fact " + cls }, el("b", { textContent: n }), el("span", { textContent: label }));
    $("facts").replaceChildren(
      fact(d.low_signal, "Con baja señal", d.low_signal ? "warn" : ""),
      fact(d.suspended, "Suspendidas"),
      fact(d.authorized_today, "Autorizadas hoy"),
      fact(d.authorized_month, "Autorizadas este mes"),
      fact(d.olts, "OLTs registradas"));
    $("updated").textContent = "Actualizado " + new Date().toLocaleTimeString();
  }
  $("refresh").addEventListener("click", load);
  load();
});
