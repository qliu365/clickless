const $ = (id) => document.getElementById(id);
const AUTH_KEY = "officelego_token";

let pollTimer = null;
let selectedFlow = "";
let selectedStepIndices = new Set();
let lastClickedIndex = -1;
let focusStepIndex = -1;
let modalOkHandler = null;
let appMeta = null;

function authHeaders(extra = {}) {
  const h = { "Content-Type": "application/json", ...extra };
  const t = localStorage.getItem(AUTH_KEY);
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    localStorage.removeItem(AUTH_KEY);
    location.href = "/login.html";
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showToast(msg, ms = 4500) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function showModal(title, bodyHtml, onOk) {
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = bodyHtml;
  modalOkHandler = onOk;
  $("modal-overlay").classList.remove("hidden");
}

function hideModal() {
  $("modal-overlay").classList.add("hidden");
  modalOkHandler = null;
}

$("modal-cancel").addEventListener("click", hideModal);
$("modal-ok").addEventListener("click", async () => {
  if (modalOkHandler) await modalOkHandler();
});

function sortedSelection() {
  return [...selectedStepIndices].sort((a, b) => a - b);
}

function renderFlows(flows) {
  const list = $("flow-list");
  list.innerHTML = "";
  flows.forEach((f) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    if (f.name === selectedFlow) btn.classList.add("active");
    btn.innerHTML = `${esc(f.name)}<span class="item-meta">${f.step_count} steps</span>`;
    btn.onclick = () => loadFlow(f.name);
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function renderModules(modules) {
  const list = $("module-list");
  list.innerHTML = "";
  modules.forEach((m) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.innerHTML = `${esc(m.name)}<span class="item-meta">${m.step_count} steps</span>`;
    btn.onclick = () => viewModule(m.name);
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadStepSimulation(index) {
  focusStepIndex = index;
  if (index < 0) {
    clearSimulation();
    return;
  }
  try {
    const detail = await api(`/api/steps/${index}`);
    const capBefore = $("sim-before");
    const capAfter = $("sim-after");
    const emptyB = $("sim-before-empty");
    const emptyA = $("sim-after-empty");
    $("sim-caption").textContent = `Step ${index + 1}: ${detail.step.type || "?"}`;

    if (detail.capture_before_url) {
      capBefore.src = detail.capture_before_url;
      capBefore.classList.remove("hidden");
      emptyB.classList.add("hidden");
    } else {
      capBefore.classList.add("hidden");
      emptyB.classList.remove("hidden");
    }
    if (detail.capture_after_url) {
      capAfter.src = detail.capture_after_url;
      capAfter.classList.remove("hidden");
      emptyA.classList.add("hidden");
    } else {
      capAfter.classList.add("hidden");
      emptyA.classList.remove("hidden");
    }

    const jsonEl = $("sim-step-json");
    jsonEl.textContent = JSON.stringify(detail.step, null, 2);
    jsonEl.classList.remove("hidden");
  } catch (e) {
    showToast(e.message);
  }
}

function clearSimulation() {
  $("sim-caption").textContent = "Select a click step to preview before/after";
  $("sim-before").classList.add("hidden");
  $("sim-after").classList.add("hidden");
  $("sim-before-empty").classList.remove("hidden");
  $("sim-after-empty").classList.remove("hidden");
  $("sim-step-json").classList.add("hidden");
}

function renderSteps(snap) {
  const list = $("step-list");
  const empty = $("empty-steps");
  const steps = snap.steps || [];
  $("step-count").textContent = String(snap.step_count || 0);
  list.innerHTML = "";

  if (!steps.length) {
    empty.classList.remove("hidden");
    clearSimulation();
    return;
  }
  empty.classList.add("hidden");

  const activePlay =
    snap.playing && snap.playback_step > 0 ? snap.playback_step - 1 : -1;

  steps.forEach((s) => {
    const li = document.createElement("li");
    if (s.index === activePlay) li.classList.add("playback-active");
    if (s.index === focusStepIndex) li.classList.add("selected");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selectedStepIndices.has(s.index);
    cb.onclick = (e) => {
      e.stopPropagation();
      toggleSelect(s.index, e.shiftKey);
    };

    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = s.label;

    li.appendChild(cb);
    li.appendChild(label);
    if (s.has_capture) {
      const dot = document.createElement("span");
      dot.className = "capture-dot";
      dot.title = "Has simulation capture";
      li.appendChild(dot);
    }

    li.onclick = () => {
      focusStepIndex = s.index;
      renderSteps(snap);
      loadStepSimulation(s.index);
    };

    list.appendChild(li);
  });
}

function toggleSelect(index, shift) {
  if (shift && lastClickedIndex >= 0) {
    const a = Math.min(lastClickedIndex, index);
    const b = Math.max(lastClickedIndex, index);
    for (let i = a; i <= b; i++) selectedStepIndices.add(i);
  } else if (selectedStepIndices.has(index)) {
    selectedStepIndices.delete(index);
  } else {
    selectedStepIndices.add(index);
  }
  lastClickedIndex = index;
}

function updateUI(snap) {
  $("status-bar").textContent = snap.status || "Ready";
  $("status-bar").className = "status-bar";
  if (snap.recording) $("status-bar").classList.add("recording");
  if (snap.playing) $("status-bar").classList.add("playing");

  $("btn-record").disabled = snap.recording || snap.playing;
  $("btn-stop-record").disabled = !snap.recording;
  $("btn-pause").disabled = !snap.recording || snap.recording_paused;
  $("btn-resume").disabled = !snap.recording || !snap.recording_paused;
  $("btn-run").disabled = snap.recording || snap.playing || !snap.step_count;
  $("btn-stop-play").disabled = !snap.playing;

  const loopBar = $("record-loop-bar");
  if (snap.recording) loopBar.classList.remove("hidden");
  else loopBar.classList.add("hidden");

  if (snap.loop_body_mode) {
    $("btn-loop-done").classList.add("accent");
  } else {
    $("btn-loop-done").classList.remove("accent");
  }

  const rp = snap.range_pick || {};
  const hint = $("range-pick-hint");
  if (rp.state && rp.state !== "idle") {
    hint.textContent = rp.message || rp.state;
    hint.classList.remove("hidden");
    if (rp.state === "confirm") showRangePickConfirm(rp);
    else if (rp.state === "done") confirmRangePickAuto(rp);
  } else {
    hint.classList.add("hidden");
    rangeConfirmShown = false;
    rangeAutoConfirmed = false;
  }

  if (snap.flow_name) {
    $("flow-name").value = snap.flow_name;
    selectedFlow = snap.flow_name;
  }

  $("opt-auto-correct").checked = !!snap.auto_correct;
  $("opt-wait-load").checked = snap.wait_load !== false;
  $("opt-speed").value = snap.playback_speed ?? 1;

  renderSteps(snap);

  if (snap.fix_messages?.length) {
    showToast("Auto-corrected:\n• " + snap.fix_messages.join("\n• "), 9000);
  }
  if (snap.loop_warnings?.length) {
    showToast(snap.loop_warnings.join("\n"), 7000);
  }
}

let rangeConfirmShown = false;
let rangeAutoConfirmed = false;

function showRangePickConfirm(rp) {
  if (rangeConfirmShown) return;
  rangeConfirmShown = true;
  showModal(
    "Confirm row count",
    `<p>Detected about <strong>${rp.rows}</strong> rows (${esc(rp.address || "")}).</p>
     <label>How many rows should the loop run?</label>
     <input type="number" id="modal-rows" min="1" max="10000" value="${rp.rows || 10}" />`,
    async () => {
      const rows = parseInt($("modal-rows")?.value || rp.rows, 10);
      await api("/api/record/loop/pick/confirm", {
        method: "POST",
        body: JSON.stringify({ rows }),
      });
      rangeConfirmShown = false;
      hideModal();
      await refreshStatus();
    }
  );
}

async function confirmRangePickAuto(rp) {
  if (rangeConfirmShown || rangeAutoConfirmed) return;
  rangeAutoConfirmed = true;
  try {
    await api("/api/record/loop/pick/confirm", {
      method: "POST",
      body: JSON.stringify({ rows: rp.rows }),
    });
    await refreshStatus();
  } catch (e) {
    showToast(e.message);
  }
}

async function refreshStatus() {
  const snap = await api("/api/status");
  updateUI(snap);
  if (!snap.recording && !snap.playing) stopPolling();
  return snap;
}

async function refreshFlows() {
  const { flows } = await api("/api/flows");
  renderFlows(flows);
}

async function refreshModules() {
  const { modules } = await api("/api/modules");
  renderModules(modules);
}

async function checkPermissions() {
  const perm = await api("/api/permissions");
  const banner = $("perm-banner");
  if (perm.granted) {
    banner.classList.add("hidden");
    return;
  }
  banner.classList.remove("hidden");
  $("perm-text").textContent = perm.hint;
}

async function loadFlow(name) {
  await api(`/api/flows/${encodeURIComponent(name)}`);
  selectedFlow = name;
  $("flow-name").value = name;
  selectedStepIndices.clear();
  await refreshFlows();
  await refreshStatus();
  showToast(`Loaded “${name}”`);
}

async function viewModule(name) {
  const data = await api(`/api/modules/${encodeURIComponent(name)}/steps`);
  showModal(
    `Module: ${esc(name)}`,
    `<p>${data.steps.length} steps (read-only preview)</p>
     <pre style="font-size:0.72rem;max-height:200px;overflow:auto">${esc(JSON.stringify(data.steps, null, 2))}</pre>`,
    () => hideModal()
  );
}

async function pushOptions() {
  await api("/api/options", {
    method: "POST",
    body: JSON.stringify({
      auto_correct: $("opt-auto-correct").checked,
      wait_load: $("opt-wait-load").checked,
      playback_speed: parseFloat($("opt-speed").value) || 1,
    }),
  });
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(() => refreshStatus().catch(() => {}), 350);
}

function stopPolling() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

$("btn-refresh-flows").onclick = refreshFlows;
$("btn-refresh-modules").onclick = refreshModules;
$("btn-perm-prompt").onclick = async () => {
  await api("/api/permissions/prompt", { method: "POST" });
  await checkPermissions();
};
$("opt-auto-correct").onchange = pushOptions;
$("opt-wait-load").onchange = pushOptions;
$("opt-speed").onchange = pushOptions;

$("btn-record").onclick = async () => {
  try {
    await pushOptions();
    const clear = confirm(
      "Start recording?\n\nOK = new flow (clears steps)\nCancel = append to current steps"
    );
    await api("/api/record/start", {
      method: "POST",
      body: JSON.stringify({ clear }),
    });
    selectedStepIndices.clear();
    startPolling();
    await refreshStatus();
  } catch (e) {
    showToast(e.message);
  }
};

$("btn-stop-record").onclick = async () => {
  await api("/api/record/stop", { method: "POST" });
  await refreshStatus();
};

$("btn-pause").onclick = async () => {
  await api("/api/record/pause", { method: "POST" });
  await refreshStatus();
};

$("btn-resume").onclick = async () => {
  await api("/api/record/resume", { method: "POST" });
  await refreshStatus();
};

$("btn-loop-pick").onclick = async () => {
  try {
    await api("/api/record/loop/pick/start", { method: "POST" });
    showToast("Switch to Excel and drag to select cells");
    startPolling();
    await refreshStatus();
  } catch (e) {
    showToast(e.message);
  }
};

$("btn-loop-wps").onclick = () => {
  showModal(
    "WPS loop row count",
    `<p>WPS has no selection highlight — enter how many rows to loop.</p>
     <label>Row count</label>
     <input type="number" id="modal-wps-rows" min="1" max="10000" value="10" />`,
    async () => {
      const rows = parseInt($("modal-wps-rows").value, 10) || 10;
      await api("/api/record/loop/wps", {
        method: "POST",
        body: JSON.stringify({ rows }),
      });
      hideModal();
      await refreshStatus();
      showToast(`Loop ×${rows} — record copy → paste once, then Loop body done`);
    }
  );
};

$("btn-loop-done").onclick = async () => {
  await api("/api/record/loop/done", { method: "POST" });
  await refreshStatus();
};

$("btn-run").onclick = async () => {
  try {
    await pushOptions();
    await api("/api/playback/start", { method: "POST", body: "{}" });
    startPolling();
    showToast("Switch to your target app");
    await refreshStatus();
  } catch (e) {
    showToast(e.message);
  }
};

$("btn-stop-play").onclick = async () => {
  await api("/api/playback/stop", { method: "POST" });
  await refreshStatus();
};

$("btn-save").onclick = async () => {
  const name = $("flow-name").value.trim();
  if (!name) return showToast("Enter a flow name");
  try {
    await api("/api/flows", { method: "POST", body: JSON.stringify({ name }) });
    selectedFlow = name;
    await refreshFlows();
    showToast(`Saved “${name}”`);
  } catch (e) {
    showToast(e.message);
  }
};

$("btn-insert-text").onclick = () => {
  showModal(
    "Insert text",
    `<label>Text to type</label><textarea id="modal-text"></textarea>`,
    async () => {
      const text = $("modal-text").value;
      await api("/api/steps/type", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      hideModal();
      await refreshStatus();
    }
  );
};

$("btn-save-module").onclick = async () => {
  const indices = sortedSelection();
  if (!indices.length) return showToast("Select steps first (checkboxes)");
  showModal(
    "Save as module",
    `<p>Selected: steps ${indices.map((i) => i + 1).join(", ")}</p>
     <label>Module name</label>
     <input type="text" id="modal-mod-name" placeholder="Copy to web" />
     <label class="check" style="margin-top:0.6rem">
       <input type="checkbox" id="modal-expand" checked /> Expand module references into concrete steps
     </label>`,
    async () => {
      const name = $("modal-mod-name").value.trim();
      if (!name) return showToast("Enter a module name");
      await api("/api/modules/save", {
        method: "POST",
        body: JSON.stringify({
          name,
          indices,
          expand_modules: $("modal-expand").checked,
        }),
      });
      selectedStepIndices.clear();
      hideModal();
      await refreshModules();
      await refreshStatus();
      showToast(`Saved module “${name}”`);
    }
  );
};

$("btn-insert-module").onclick = async () => {
  const { modules } = await api("/api/modules");
  if (!modules.length) return showToast("Save a module first");
  const { labels, positions } = await api("/api/gaps");
  const modOpts = modules.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join("");
  const gapOpts = labels
    .map((l, i) => `<option value="${positions[i]}">${esc(l)}</option>`)
    .join("");
  showModal(
    "Insert module",
    `<label>Module</label><select id="modal-mod">${modOpts}</select>
     <label>Position</label><select id="modal-gap">${gapOpts}</select>`,
    async () => {
      await api("/api/steps/insert-module", {
        method: "POST",
        body: JSON.stringify({
          name: $("modal-mod").value,
          at_index: parseInt($("modal-gap").value, 10),
        }),
      });
      hideModal();
      await refreshStatus();
    }
  );
};

$("btn-insert-loop").onclick = async () => {
  const { modules } = await api("/api/modules");
  const indices = sortedSelection();
  const modOpts = modules
    .map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`)
    .join("");
  const hasSel = indices.length > 0;
  showModal(
    "Insert loop",
    `<label>Repeat count</label><input type="number" id="modal-loop-count" min="1" max="10000" value="10" />
     <label>Source</label>
     <select id="modal-loop-source">
       ${modules.length ? '<option value="module">Saved module</option>' : ""}
       ${hasSel ? '<option value="selection">Selected steps</option>' : ""}
     </select>
     <div id="modal-loop-module-wrap" class="${modules.length ? "" : "hidden"}">
       <label>Module</label><select id="modal-loop-mod">${modOpts}</select>
     </div>
     <div id="modal-loop-sel-wrap" class="${hasSel ? "" : "hidden"}">
       <label class="check"><input type="checkbox" id="modal-loop-remove" checked />
       Remove original steps (avoid running twice)</label>
     </div>`,
    async () => {
      const source = $("modal-loop-source").value;
      const count = parseInt($("modal-loop-count").value, 10) || 10;
      const body = { count, source };
      if (source === "module") body.module_name = $("modal-loop-mod").value;
      else {
        body.indices = indices;
        body.remove_selected = $("modal-loop-remove").checked;
      }
      await api("/api/steps/insert-loop", {
        method: "POST",
        body: JSON.stringify(body),
      });
      hideModal();
      await refreshStatus();
    }
  );
};

$("btn-delete-steps").onclick = async () => {
  const indices = sortedSelection();
  if (!indices.length) return showToast("Select steps to delete");
  if (!confirm(`Delete ${indices.length} step(s)?`)) return;
  await api("/api/steps/delete", {
    method: "POST",
    body: JSON.stringify({ indices }),
  });
  selectedStepIndices.clear();
  focusStepIndex = -1;
  clearSimulation();
  await refreshStatus();
};

$("btn-edit-step").onclick = async () => {
  const indices = sortedSelection();
  if (indices.length !== 1) return showToast("Select exactly one step to edit");
  const index = indices[0];
  const detail = await api(`/api/steps/${index}`);
  const step = detail.step;
  const t = step.type;

  if (t === "type") {
    showModal(
      "Edit type step",
      `<label>Text</label><textarea id="modal-edit-text">${esc(step.text || "")}</textarea>`,
      async () => {
        await api(`/api/steps/${index}`, {
          method: "PUT",
          body: JSON.stringify({ text: $("modal-edit-text").value }),
        });
        hideModal();
        await refreshStatus();
        loadStepSimulation(index);
      }
    );
  } else if (t === "loop") {
    showModal(
      "Edit loop",
      `<label>Repeat count</label>
       <input type="number" id="modal-edit-count" min="1" max="10000" value="${step.count || 10}" />
       <p class="hint">Inline loop body: ${(step.steps || []).length} steps
       ${step.module ? `· module “${esc(step.module)}”` : ""}</p>`,
      async () => {
        await api(`/api/steps/${index}`, {
          method: "PUT",
          body: JSON.stringify({ count: parseInt($("modal-edit-count").value, 10) }),
        });
        hideModal();
        await refreshStatus();
      }
    );
  } else if (t === "module") {
    const mod = await api(`/api/modules/${encodeURIComponent(step.name)}/steps`);
    showModal(
      `Module: ${esc(step.name)}`,
      `<p>${mod.steps.length} steps in file. Edit the module JSON file or re-save from a selection.</p>
       <pre style="font-size:0.7rem;max-height:180px;overflow:auto">${esc(JSON.stringify(mod.steps.slice(0, 8), null, 2))}${mod.steps.length > 8 ? "\n…" : ""}</pre>`,
      hideModal
    );
  } else {
    showToast(`Step type “${t}” — edit in desktop app or delete & re-record`);
  }
};

function updatePublicBanner() {
  const el = $("public-banner");
  if (!el || !appMeta) return;
  const remote =
    location.hostname !== "localhost" && location.hostname !== "127.0.0.1";
  if (appMeta.public_mode || remote) {
    el.classList.remove("hidden");
    el.textContent =
      appMeta.hint_zh ||
      "Recording runs on the Mac where this server is running—not in the cloud.";
  } else {
    el.classList.add("hidden");
  }
}

async function init() {
  appMeta = await fetch("/api/meta").then((r) => r.json());
  if (appMeta.auth_required && !localStorage.getItem(AUTH_KEY)) {
    location.href = "/login.html";
    return;
  }
  updatePublicBanner();
  await checkPermissions();
  await refreshFlows();
  await refreshModules();
  const snap = await refreshStatus();
  updateUI(snap);
  if (snap.recording || snap.playing) startPolling();
}

const btnLogout = $("btn-logout");
if (btnLogout) {
  btnLogout.onclick = () => {
    localStorage.removeItem(AUTH_KEY);
    location.href = "/login.html";
  };
}

init().catch((e) => showToast(String(e)));
