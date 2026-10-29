R.ready.then(async () => {
  const { $, api } = R;
  R.bindSearch($("search"), $("rows"));
  async function load() {
    const rows = await api(`/audit?limit=${$("limit").value}`);
    R.table($("rows"), rows, null, (tr, r) => {
      tr.insertCell().textContent = R.fmtDate(r.at);
      tr.insertCell().textContent = r.actor;
      tr.insertCell().textContent = r.action;
      tr.insertCell().textContent = r.olt_id ?? "";
      tr.insertCell().textContent = r.serial;
      tr.insertCell().textContent = r.detail;
    });
  }
  $("btn-go").addEventListener("click", load);
  load();
});
