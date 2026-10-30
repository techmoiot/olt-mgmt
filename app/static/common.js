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


  const NS = "http://www.w3.org/2000/svg";
  const ICONS = {
    dashboard: "M3 13h7V3H3zM14 21h7V11h-7zM3 21h7v-6H3zM14 3v5h7V3z",
    olts: "M3 6h18v5H3zM3 13h18v5H3zM7 8.5h.01M7 15.5h.01",
    "olt-nueva": "M12 5v14M5 12h14",
    "onus-sin-autorizar": "M12 8v5M12 16.5h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
    "onus-autorizadas": "M4 12.5l5 5L20 6.5",
    mikrotik: "M5 12.5a10 10 0 0114 0M8.5 16a5 5 0 017 0M12 19.5h.01M2 9a15 15 0 0120 0",
    planes: "M3 17l5-6 4 4 8-10M15 5h5v5",
    zonas: "M12 21s-7-6-7-11a7 7 0 0114 0c0 5-7 11-7 11zM12 12a2 2 0 100-4 2 2 0 000 4z",
    usuarios: "M16 19v-1.5a3.5 3.5 0 00-3.5-3.5h-5A3.5 3.5 0 004 17.5V19M10 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM20 19v-1.5a3.5 3.5 0 00-2.5-3.3M15.5 4.2a3.5 3.5 0 010 6.6",
    auditoria: "M7 3h8l4 4v14H7zM14 3v5h5M10 13h6M10 17h6",
  };
  R.icon = function (name, size = 18) {
    const svg = document.createElementNS(NS, "svg");
    for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
    const p = document.createElementNS(NS, "path"); p.setAttribute("d", ICONS[name] || ""); svg.append(p);
    return svg;
  };
  R.logo = function (size = 26) {  // tres arcos de señal sobre un punto: la luz que sale por la fibra
    const svg = document.createElementNS(NS, "svg");
    for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 32 32", fill: "none", stroke: "currentColor", "stroke-width": 2.4, "stroke-linecap": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
    for (const d of ["M6 14a14 14 0 0120 0", "M10 18a8.5 8.5 0 0112 0", "M13.5 22a3.5 3.5 0 015 0"]) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); svg.append(p); }
    const c = document.createElementNS(NS, "circle"); c.setAttribute("cx", 16); c.setAttribute("cy", 26.5); c.setAttribute("r", 1.8); c.setAttribute("fill", "currentColor"); c.setAttribute("stroke", "none"); svg.append(c);
    return svg;
  };

  // Medidor de señal óptica: potencia recibida de la ONU en dBm (más cerca de 0 = más fuerte).
  R.signal = function (dbm) {
    const v = parseFloat(dbm);
    const wrap = el("span", { className: "signal" });
    if (!isFinite(v)) { wrap.classList.add("none"); wrap.textContent = "—"; return wrap; }
    const [cls, bars, label] = v >= -24 ? ["good", 4, "buena"] : v >= -27 ? ["fair", 3, "aceptable"] : v >= -29 ? ["low", 2, "baja"] : ["critical", 1, "crítica"];
    wrap.classList.add(cls); wrap.title = `Señal ${label}`;
    const b = el("span", { className: "bars" });
    for (let i = 1; i <= 4; i++) b.append(el("i", { className: i <= bars ? "on" : "" }));
    wrap.append(b, document.createTextNode(`${v.toFixed(1)} dBm`));
    return wrap;
  };

  R.pill = (text, kind) => el("span", { className: "pill " + (kind || ""), textContent: text });

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
        nav.append(el("a", { href: `/static/${id}.html`, className: id === page ? "active" : "" }, R.icon(id), label));
      }
    }
    const aside = el("aside", { className: "sidebar", id: "sidebar" }, el("div", { className: "brand" }, R.logo(26), "Ritsuko"), nav);
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
