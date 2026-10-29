R.ready.then(async () => {
  const { $, api, setMsg } = R;
  async function load() {
    const plans = await api("/speed-plans");
    R.table($("rows"), plans, $("empty"), (tr, p) => {
      tr.insertCell().textContent = p.name;
      tr.insertCell().textContent = `${p.down_kbps / 1000} Mbps`;
      tr.insertCell().textContent = `${p.up_kbps / 1000} Mbps`;
      tr.insertCell().textContent = p.description;
    });
  }
  $("plan-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      await api("/speed-plans", { method: "POST", body: R.json({ name: f.name, description: f.description, down_kbps: Math.round(Number(f.down) * 1000), up_kbps: Math.round(Number(f.up) * 1000) }) });
      e.target.reset(); setMsg($("plan-msg"), "Plan creado", true); load();
    } catch (err) { setMsg($("plan-msg"), err.message, false); }
  });
  load();
});
