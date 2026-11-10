const TOKEN = document.body.dataset.token;
const state = { rows: [], config: {}, query: "", openMenu: null, first: true };

async function api(path, body) {
  const opts = {
    method: body ? "POST" : "GET",
    headers: { "X-PortWatch-Token": TOKEN, "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2600);
}

function saveConfig(patch) {
  Object.assign(state.config, patch);
  api("/api/config", { config: patch }).catch(() => {});
}

// ---------------------------------------------------------------- 그리기
function matches(row) {
  if (!state.query) return true;
  const hay = [row.port, row.title, row.name, row.cmdline, row.cwd, row.addrs]
    .join(" ").toLowerCase();
  return hay.includes(state.query);
}

function badges(row) {
  const out = [];
  if (row.health) {
    const [code, ms] = row.health;
    out.push(`<span class="badge ${code < 400 ? "ok" : "warn"}">${code} · ${ms}ms</span>`);
  } else if (row.kind !== "tcp") {
    out.push(`<span class="badge info">${row.kind.toUpperCase()}</span>`);
  }
  if (row.docker) out.push(`<span class="badge info">Docker</span>`);
  if (row.public) out.push(`<span class="badge warn" title="${row.addrs} 에 바인딩되어 같은 네트워크의 다른 장비에서 접근됩니다">외부 공개</span>`);
  return out.join("");
}

function subtitle(row) {
  const bits = [];
  if (row.restricted) bits.push("다른 사용자 소유 · 프로세스 정보 없음");
  else {
    if (row.cmdline) bits.push(row.cmdline.slice(0, 150));
    if (row.uptime) bits.push("가동 " + row.uptime);
  }
  bits.push(row.addrs);
  return bits.join("   ·   ");
}

function rowHTML(row) {
  const pinned = (state.config.pinned || []).includes(row.port);
  return `<div class="row ${row.url ? "clickable" : ""}" data-port="${row.port}">
    <div class="pill ${row.kind}">${row.port}</div>
    <div class="meta">
      <div class="title">${escapeHTML(row.title)}</div>
      <div class="sub">${escapeHTML(subtitle(row))}</div>
    </div>
    <div class="badges">${badges(row)}</div>
    <div class="actions">
      <button class="icon star" title="즐겨찾기">${pinned ? "★" : "☆"}</button>
      ${row.url ? `<button class="icon open" title="브라우저로 열기">↗</button>` : ""}
      <button class="icon more" title="더 보기">⋯</button>
    </div>
  </div>`;
}

function offlineRowHTML(port, saved) {
  return `<div class="row" data-port="${port}" data-offline="1">
    <div class="pill tcp">${port}</div>
    <div class="meta">
      <div class="title">${escapeHTML(saved.title)}</div>
      <div class="sub">${escapeHTML(saved.cmdline.slice(0, 120) + "   ·   " + saved.cwd)}</div>
    </div>
    <div class="badges"><span class="badge mute">꺼짐</span></div>
    <div class="actions">
      <button class="icon restart" title="기억해 둔 명령으로 다시 실행">▶</button>
      <button class="icon forget" title="기억 지우기">🗑</button>
    </div>
  </div>`;
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function render() {
  const pinned = state.config.pinned || [];
  const visible = state.rows.filter(r =>
    (state.config.show_system || r.section !== "system") && matches(r));

  const buckets = { pinned: [], mine: [], docker: [], system: [] };
  visible.forEach(r => buckets[pinned.includes(r.port) ? "pinned" : r.section].push(r));

  const live = new Set(state.rows.map(r => r.port));
  const offline = state.query ? [] : pinned
    .filter(p => !live.has(p) && (state.config.commands || {})[String(p)])
    .map(p => [p, state.config.commands[String(p)]]);

  const sections = [
    ["pinned", "즐겨찾기", "자주 여는 포트입니다."],
    ["mine", "내 서버", "직접 띄운 프로세스입니다."],
    ["docker", "Docker 컨테이너", "컨테이너 안에서 도는 서비스입니다."],
    ["system", "시스템·관리 도구", "OS와 관리 도구가 쓰는 포트입니다."],
  ];

  let html = "";
  for (const [key, title, desc] of sections) {
    const items = buckets[key];
    if (!items.length) continue;
    html += `<section><h2>${title} (${items.length})</h2><p class="desc">${desc}</p>
      <div class="list">${items.map(rowHTML).join("")}</div></section>`;
  }
  if (offline.length) {
    html += `<section><h2>꺼진 즐겨찾기 (${offline.length})</h2>
      <p class="desc">즐겨찾기에 넣어 둔 포트인데 지금은 떠 있지 않습니다.</p>
      <div class="list">${offline.map(([p, s]) => offlineRowHTML(p, s)).join("")}</div></section>`;
  }
  if (!html) {
    html = `<div class="empty">${state.query ? "검색어와 일치하는 포트가 없습니다."
      : "표시할 포트가 없습니다. '시스템'을 켜 보세요."}</div>`;
  }
  document.getElementById("main").innerHTML = html;

  const mine = state.rows.filter(r => r.section === "mine").length;
  const docker = state.rows.filter(r => r.section === "docker").length;
  document.getElementById("summary").textContent =
    `내 서버 ${mine} · Docker ${docker} · 전체 ${state.rows.length}`;
}

// ---------------------------------------------------------------- 대화상자
function dialog({ title, body, extra = "", buttons }) {
  const dlg = document.getElementById("dialog");
  document.getElementById("dlgTitle").textContent = title;
  document.getElementById("dlgBody").textContent = body || "";
  document.getElementById("dlgExtra").innerHTML = extra;
  const foot = document.getElementById("dlgFoot");
  foot.innerHTML = "";
  buttons.forEach(b => {
    const el = document.createElement("button");
    el.textContent = b.label;
    if (b.style) el.className = b.style;
    el.onclick = () => { dlg.close(); b.onClick && b.onClick(dlg); };
    foot.appendChild(el);
  });
  dlg.showModal();
  return dlg;
}

async function confirmKill(row) {
  const lines = [`PID ${row.pid} · 포트 ${row.port}`];
  if (row.cmdline) lines.push(row.cmdline.slice(0, 180));
  if (row.uptime) lines.push("가동 " + row.uptime);
  lines.push("", "저장하지 않은 작업이 있다면 사라질 수 있습니다.");
  dialog({
    title: `${row.title} 을(를) 종료할까요?`,
    body: lines.join("\n"),
    buttons: [
      { label: "취소" },
      { label: "종료", style: "danger", onClick: () => doKill(row) },
    ],
  });
}

async function doKill(row) {
  const res = await api("/api/kill", { port: row.port });
  toast(res.message);
  if (!res.ok) return;
  setTimeout(async () => {
    const alive = await api("/api/alive", { pid: res.pid });
    if (!alive.alive) { toast(`${row.title} 이(가) 종료되었습니다`); refresh(); return; }
    dialog({
      title: "아직 종료되지 않았습니다",
      body: `${row.title} (PID ${res.pid}) 이(가) 3초가 지나도록 응답하지 않습니다.\n\n`
           + "강제로 종료하면 프로세스는 정리할 기회를 갖지 못합니다.",
      buttons: [
        { label: "더 기다리기" },
        { label: "강제 종료", style: "danger", onClick: async () => {
            const r = await api("/api/force-kill", { pid: res.pid });
            toast(r.message); setTimeout(refresh, 800);
          } },
      ],
    });
  }, 3000);
}

function freePortDialog() {
  dialog({
    title: "포트 비우기",
    body: "쓰려는 포트 번호를 입력하면 그 포트를 쥐고 있는 프로세스를 찾습니다.",
    extra: `<input type="search" id="freeInput" placeholder="예: 8080" style="margin-top:12px;width:100%">`,
    buttons: [
      { label: "취소" },
      { label: "찾기", style: "primary", onClick: () => {
          const port = parseInt(document.getElementById("freeInput").value, 10);
          if (!port) { toast("포트 번호를 숫자로 입력해 주세요"); return; }
          const row = state.rows.find(r => r.port === port);
          if (!row) { toast(`${port} 번은 비어 있습니다 — 바로 쓰실 수 있습니다`); return; }
          if (row.can_kill) { confirmKill(row); return; }
          const advice = row.docker
            ? `Docker 컨테이너가 쓰고 있습니다. docker stop 으로 내릴 수 있습니다.`
            : "다른 사용자가 쓰고 있어 이 앱에서는 종료할 수 없습니다.";
          dialog({ title: `${port} 번은 ${row.title} 이(가) 쓰고 있습니다`,
                   body: advice, buttons: [{ label: "알겠습니다" }] });
        } },
    ],
  });
  setTimeout(() => document.getElementById("freeInput")?.focus(), 50);
}

async function exposureDialog() {
  const { rows } = await api("/api/exposure");
  if (!rows.length) {
    dialog({ title: "외부에 열린 포트가 없습니다",
             body: "모든 포트가 127.0.0.1 에만 묶여 있습니다.",
             buttons: [{ label: "닫기" }] });
    return;
  }
  const risky = rows.filter(r => r.risky);
  const rest = rows.filter(r => !r.risky);
  let body = "";
  if (risky.length) body += "아래 포트는 인증 없이 열려 있으면 특히 위험합니다.\n\n"
    + risky.map(r => `${r.port}  ${r.title}  (${r.addrs})  ← ${r.risky}`).join("\n") + "\n\n";
  if (rest.length) body += "그 밖에 외부에서 접근 가능한 포트입니다.\n\n"
    + rest.map(r => `${r.port}  ${r.title}  (${r.addrs})`).join("\n");
  body += "\n\n같은 네트워크의 다른 장비에서 접근할 수 있습니다. "
       + "개발용이라면 127.0.0.1 에만 묶는 편이 안전합니다.";
  dialog({
    title: `외부에 열린 포트 ${rows.length}개`, body,
    buttons: [
      { label: "목록 복사", onClick: () => {
          navigator.clipboard.writeText(body).then(() => toast("목록을 복사했습니다")); } },
      { label: "닫기" },
    ],
  });
}

// ---------------------------------------------------------------- 이벤트
document.addEventListener("click", async (ev) => {
  if (state.openMenu && !ev.target.closest(".menu") && !ev.target.closest(".more")) {
    state.openMenu.remove(); state.openMenu = null;
  }
  const rowEl = ev.target.closest(".row");
  if (!rowEl) return;
  const port = parseInt(rowEl.dataset.port, 10);

  if (rowEl.dataset.offline) {
    if (ev.target.closest(".restart")) {
      const saved = state.config.commands[String(port)];
      dialog({
        title: `${saved.title} 을(를) 다시 띄울까요?`,
        body: `${saved.cmdline}\n\n작업 디렉터리: ${saved.cwd}\n\n`
             + "터미널에서 직접 실행할 때와 환경 변수가 다를 수 있습니다.",
        buttons: [{ label: "취소" }, { label: "실행", style: "primary", onClick: async () => {
          const r = await api("/api/restart", { port });
          toast(r.message); setTimeout(refresh, 1600);
        } }],
      });
    } else if (ev.target.closest(".forget")) {
      const commands = { ...state.config.commands };
      delete commands[String(port)];
      saveConfig({ commands });
      toast("기억해 둔 실행 명령을 지웠습니다");
      render();
    }
    return;
  }

  const row = state.rows.find(r => r.port === port);
  if (!row) return;

  if (ev.target.closest(".star")) {
    const pinned = new Set(state.config.pinned || []);
    const commands = { ...(state.config.commands || {}) };
    if (pinned.has(port)) pinned.delete(port);
    else {
      pinned.add(port);
      if (row.cmdline && row.cwd && !row.docker)
        commands[String(port)] = { title: row.title, cmdline: row.cmdline, cwd: row.cwd };
    }
    saveConfig({ pinned: [...pinned].sort((a, b) => a - b), commands });
    render();
    return;
  }
  if (ev.target.closest(".open")) { window.open(row.url, "_blank"); return; }
  if (ev.target.closest(".more")) { openMenu(ev.target.closest(".actions"), row); return; }
  if (row.url && !ev.target.closest("button")) window.open(row.url, "_blank");
});

function openMenu(anchor, row) {
  if (state.openMenu) { state.openMenu.remove(); state.openMenu = null; }
  const items = [];
  if (row.url) {
    items.push(["브라우저로 열기", () => window.open(row.url, "_blank")]);
    items.push(["URL 복사", () => navigator.clipboard.writeText(row.url)
      .then(() => toast("URL을 복사했습니다"))]);
  }
  items.push(["명령줄 복사", () => navigator.clipboard.writeText(row.cmdline || "-")
    .then(() => toast("명령줄을 복사했습니다"))]);
  if (row.cwd) {
    items.push(["작업 디렉터리 열기", async () => toast((await api("/api/open-dir", { port: row.port })).message)]);
    items.push(["터미널에서 열기", async () => toast((await api("/api/open-terminal", { port: row.port })).message)]);
  }
  if (row.docker && row.container) {
    items.push(["separator"]);
    items.push([`docker stop ${row.container} 복사`, () =>
      navigator.clipboard.writeText(`docker stop ${row.container}`)
        .then(() => toast("명령을 복사했습니다"))]);
  } else if (row.can_kill) {
    items.push(["separator"]);
    items.push(["프로세스 종료", () => confirmKill(row)]);
  }

  const menu = document.createElement("div");
  menu.className = "menu";
  items.forEach(([label, fn]) => {
    if (label === "separator") { menu.appendChild(document.createElement("hr")); return; }
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => { menu.remove(); state.openMenu = null; fn(); };
    menu.appendChild(b);
  });
  anchor.appendChild(menu);
  state.openMenu = menu;
}

document.getElementById("search").addEventListener("input", (e) => {
  state.query = e.target.value.trim().toLowerCase();
  render();
});
document.getElementById("refresh").onclick = () => refresh();
document.getElementById("freePort").onclick = freePortDialog;
document.getElementById("exposure").onclick = exposureDialog;
document.getElementById("showSystem").onchange = (e) => {
  saveConfig({ show_system: e.target.checked }); render();
};
document.getElementById("checkHealth").onchange = (e) => {
  saveConfig({ check_health: e.target.checked }); refresh();
};
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "/" || (e.key === "f" && (e.ctrlKey || e.metaKey))) {
    e.preventDefault(); document.getElementById("search").focus();
  } else if (e.key.toLowerCase() === "r") refresh();
});

// ---------------------------------------------------------------- 갱신 주기
async function refresh() {
  try {
    const data = await api("/api/state?health=" + (state.config.check_health ? 1 : 0));
    state.rows = data.rows;
    state.config = data.config;
    document.getElementById("showSystem").checked = !!data.config.show_system;
    document.getElementById("checkHealth").checked = !!data.config.check_health;
    const { opened, closed } = data.changes;
    if (!state.first && data.config.notify_changes && (opened.length || closed.length)) {
      const parts = [];
      if (opened.length) parts.push(`${opened.slice(0, 3).join(", ")}${opened.length > 3 ? ` 외 ${opened.length - 3}개` : ""} 열림`);
      if (closed.length) parts.push(`${closed.slice(0, 3).join(", ")}${closed.length > 3 ? ` 외 ${closed.length - 3}개` : ""} 닫힘`);
      toast("포트 " + parts.join(" · "));
    }
    state.first = false;
    render();
  } catch (err) {
    document.getElementById("summary").textContent = "서버에 연결하지 못했습니다";
  }
}

refresh();
setInterval(() => { if (state.config.auto_refresh !== false) refresh(); }, 5000);
