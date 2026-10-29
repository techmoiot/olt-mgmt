/* Código compartido de todas las pantallas: sesión, menú lateral y utilidades. Sin código en línea (CSP). */
(function () {
  const $ = id => document.getElementById(id);

  function el(tag, props = {}, ...kids) {
    const e = Object.assign(document.createElement(tag), props);
    e.append(...kids);
    return e;
  }
  function setMsg(node, text, ok) { node.textContent = text; node.className = "msg " + (ok ? "ok" : "bad"); }

  const R = { $, el, setMsg, session: null };

  R.api = async function (path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (R.session && opts.method && opts.method !== "GET") headers["X-CSRF-Token"] = R.session.csrf_token;
    const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/auth/login") { location.href = "/"; throw new Error("Sesión vencida"); }
    if (res.status === 403 && data.code === "password_change_required") { location.href = "/static/cambiar-clave.html?forzado=1"; throw new Error(data.detail); }
    if (!res.ok) {
      const d = data.detail;
      const err = new Error(typeof d === "string" ? d
        : Array.isArray(d) ? d.map(e => e.loc.slice(1).join(".") + ": " + e.msg).join("; ") : "Error " + res.status);
      err.status = res.status;
      throw err;
    }
    return data;
  };
  R.json = body => JSON.stringify(body);
  R.isAdmin = () => !!R.session && R.session.role === "admin";

  R.table = function (tbody, rows, emptyNode, build) {
    tbody.replaceChildren();
    if (emptyNode) emptyNode.classList.toggle("hidden", rows.length > 0);
    for (const r of rows) build(tbody.insertRow(), r);
  };

  R.fillSelect = function (sel, items, label, value, blank) {
    const keep = sel.value;
    sel.replaceChildren();
    if (blank !== undefined) sel.add(new Option(blank, ""));
    for (const it of items) sel.add(new Option(label(it), value(it)));
    if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
  };

  R.fmtDate = s => (s ? new Date(s).toLocaleString() : "—");

  // Filtro de texto simple sobre filas de una tabla (por el texto visible)
  R.bindSearch = function (input, tbody) {
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      for (const tr of tbody.rows) tr.classList.toggle("hidden", !!q && !tr.textContent.toLowerCase().includes(q));
    });
  };

  const MENU = [
    { title: "General", items: [["dashboard", "Dashboard"]] },
    { title: "OLT", items: [["olts", "OLTs"], ["olt-nueva", "Agregar OLT", true]] },
    { title: "ONU", items: [["onus-sin-autorizar", "Sin autorizar"], ["onus-autorizadas", "Autorizadas"]] },
    { title: "Red", admin: true, items: [["mikrotik", "MikroTik y VPN"], ["planes", "Planes de velocidad"], ["zonas", "Zonas y NAP"]] },
    { title: "Sistema", admin: true, items: [["usuarios", "Usuarios"], ["auditoria", "Auditoría"]] },
  ];

  function buildLayout(page, title) {
    const main = $("main");
    const nav = el("nav");
    for (const g of MENU) {
      if (g.admin && !R.isAdmin()) continue;
      const items = g.items.filter(i => !i[2] || R.isAdmin());
      nav.append(el("div", { className: "nav-title", textContent: g.title }));
      for (const [id, label] of items) {
        nav.append(el("a", { href: `/static/${id}.html`, textContent: label, className: id === page ? "active" : "" }));
      }
    }
    const aside = el("aside", { className: "sidebar", id: "sidebar" }, el("div", { className: "brand", textContent: "Ritsuko" }), nav);
    const burger = el("button", { type: "button", className: "burger", textContent: "☰", title: "Menú" });
    burger.onclick = () => aside.classList.toggle("open");
    const logout = el("button", { type: "button", textContent: "Salir" });
    logout.onclick = async () => {
      try { await R.api("/auth/logout", { method: "POST" }); } catch { /* ya estaba cerrada */ }
      location.href = "/";
    };
    const who = el("div", { className: "who" },
      el("span", { textContent: R.session.username }),
      el("span", { className: "badge", textContent: R.isAdmin() ? "administrador" : "operador" }),
      el("a", { href: "/static/cambiar-clave.html", className: "btn", textContent: "Cambiar contraseña" }),
      logout);
    const top = el("header", { className: "topbar" }, burger, el("h1", { textContent: title }), who);
    document.body.classList.toggle("is-admin", R.isAdmin());
    main.classList.remove("hidden");
    const content = el("div", { className: "content" }, top, main);
    document.body.prepend(el("div", { className: "layout" }, aside, content));
  }

  R.ready = (async function () {
    const page = document.body.dataset.page;
    if (!page) return R;
    try { R.session = await (await fetch("/auth/me", { credentials: "same-origin" })).json(); } catch { R.session = null; }
    if (!R.session || !R.session.username) { location.href = "/"; return new Promise(() => {}); }
    if (R.session.must_change_password) { location.href = "/static/cambiar-clave.html?forzado=1"; return new Promise(() => {}); }
    if (document.body.dataset.admin && !R.isAdmin()) { location.href = "/static/dashboard.html"; return new Promise(() => {}); }
    buildLayout(page, document.body.dataset.title || "Ritsuko");
    return R;
  })();

  window.R = R;
})();
