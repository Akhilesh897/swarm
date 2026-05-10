const chatLog = document.getElementById("chatLog");
const messageInput = document.getElementById("message");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearChat");
const logoutBtn = document.getElementById("logoutBtn");
const identityPill = document.getElementById("identityPill");
const userIdInput = document.getElementById("userId");
const sessionIdInput = document.getElementById("sessionId");
const roleInput = document.getElementById("role");
const modelSelect = document.getElementById("modelSelect");
const apiStatus = document.getElementById("apiStatus");
const promptStrip = document.getElementById("promptStrip");
const draftSignal = document.getElementById("draftSignal");
const workspaceTitle = document.getElementById("workspaceTitle");
const roleEyebrow = document.getElementById("roleEyebrow");
const leavesContainer = document.getElementById("leavesContainer");
const ticketsContainer = document.getElementById("ticketsContainer");
const assetsContainer = document.getElementById("assetsContainer");
const roleMenu = document.getElementById("roleMenu");
const roleView = document.getElementById("roleView");
const refreshContextBtn = document.getElementById("refreshContextBtn");
const autoRefreshToggle = document.getElementById("autoRefreshToggle");
const lastSync = document.getElementById("lastSync");
const kpiStrip = document.getElementById("kpiStrip");
const appToast = document.getElementById("appToast");

let autoRefreshTimer = null;

const PROMPTS = [
  { label: "Paternity policy", text: "what is paternity leave policy", tone: "hr" },
  { label: "Leave balance", text: "what is my leave balance", tone: "hr" },
  { label: "Laptop ticket", text: "raise an IT ticket for laptop issue", tone: "it" },
  { label: "Expense rules", text: "what is expense reimbursement policy", tone: "finance" },
  
];

const STORAGE_KEYS = {
  token: "agent.token",
  userId: "agent.userId",
  sessionId: "agent.sessionId",
  role: "agent.role",
  model: "agent.model",
};

function rolePath(role) {
  if (role === "it_lead") {
    return "/it-lead";
  }
  if (role === "manager") {
    return "/manager";
  }
  return "/employee";
}

function roleLabel(role) {
  if (role === "it_lead") {
    return "IT Lead";
  }
  if (role === "manager") {
    return "Manager";
  }
  return "Employee";
}

function redirectToLogin() {
  window.location.href = "/";
}

async function bootstrapIdentity() {
  const token = localStorage.getItem(STORAGE_KEYS.token);
  const role = localStorage.getItem(STORAGE_KEYS.role);
  const userId = localStorage.getItem(STORAGE_KEYS.userId);
  if (!token || !role || !userId) {
    redirectToLogin();
    return false;
  }

  const expectedPath = rolePath(role);
  if (window.location.pathname !== expectedPath && window.location.pathname !== "/chat-ui") {
    window.location.replace(expectedPath);
    return false;
  }

  userIdInput.value = userId;
  roleInput.value = role;
  identityPill.textContent = `${roleLabel(role)} | ${userId}`;
  workspaceTitle.textContent = `${roleLabel(role)} Workspace`;
  roleEyebrow.textContent = "Authenticated Workspace";
  return true;
}

function setDefaults() {
  const storedSession = localStorage.getItem(STORAGE_KEYS.sessionId);
  const storedModel = localStorage.getItem(STORAGE_KEYS.model);
  sessionIdInput.value = storedSession || `session-${crypto.randomUUID().slice(0, 8)}`;
  modelSelect.value = storedModel || "auto";
}

function persistInputs() {
  localStorage.setItem(STORAGE_KEYS.sessionId, sessionIdInput.value.trim());
  localStorage.setItem(STORAGE_KEYS.model, modelSelect.value);
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    apiStatus.textContent = response.ok ? "Online" : "Degraded";
  } catch (error) {
    apiStatus.textContent = "Offline";
  }
}

function showToast(message, kind = "info") {
  if (!appToast) return;
  appToast.textContent = message;
  appToast.className = `app-toast show ${kind}`;
  setTimeout(() => {
    appToast.className = "app-toast";
  }, 1800);
}

function updateLastSync() {
  if (!lastSync) return;
  const now = new Date();
  lastSync.textContent = `${now.getHours().toString().padStart(2, "0")}:${now
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
}

function setLoadingKpis() {
  if (!kpiStrip) return;
  kpiStrip.innerHTML = `
    <div class="kpi-pill skeleton"></div>
    <div class="kpi-pill skeleton"></div>
    <div class="kpi-pill skeleton"></div>
  `;
}

function renderKpis({ role = "", leaves = [], tickets = [], assets = [], pendingLeave = 0, pendingAsset = 0 }) {
  if (!kpiStrip) return;
  const roleText = role ? role.replace("_", " ") : "unknown";
  const values = [
    { label: "Role", value: roleText.toUpperCase() },
    { label: "Open Tickets", value: String((tickets || []).filter((t) => !["resolved"].includes(String(t.status || "").toLowerCase())).length) },
    { label: "Pending Approvals", value: String(pendingLeave + pendingAsset) },
    { label: "Assets", value: String((assets || []).length) },
    { label: "Leaves", value: String((leaves || []).length) },
  ];
  kpiStrip.innerHTML = values
    .map((k) => `<div class="kpi-pill"><span>${k.label}</span><strong>${escapeHtml(k.value)}</strong></div>`)
    .join("");
}

function logout() {
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.userId);
  localStorage.removeItem(STORAGE_KEYS.role);
  redirectToLogin();
}

function createBubble(text, type, meta, actions = []) {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-bubble ${type}`;

  const content = document.createElement("div");
  content.className = "bubble-content";
  if (type === "agent" && typeof marked !== "undefined") {
    content.innerHTML = marked.parse(text);
  } else {
    content.textContent = text;
  }
  wrapper.appendChild(content);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "chat-meta";
    metaEl.textContent = meta;
    wrapper.appendChild(metaEl);
  }

  if (actions.length) {
    const actionsEl = document.createElement("div");
    actionsEl.className = "bubble-actions";
    actions.forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `bubble-action ${action.kind || "secondary"}`;
      button.textContent = action.label;
      button.addEventListener("click", action.onClick);
      actionsEl.appendChild(button);
    });
    wrapper.appendChild(actionsEl);
  }

  return wrapper;
}

function addMessage(text, type, meta, actions) {
  const bubble = createBubble(text, type, meta, actions);
  chatLog.appendChild(bubble);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderPromptStrip() {
  promptStrip.innerHTML = "";
  PROMPTS.forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `prompt-chip ${prompt.tone}`;
    button.textContent = prompt.label;
    button.addEventListener("click", () => {
      messageInput.value = prompt.text;
      updateDraftSignal();
      messageInput.focus();
    });
    promptStrip.appendChild(button);
  });
}

function updateDraftSignal() {
  const text = messageInput.value.trim();
  if (!text) {
    draftSignal.textContent = "Ready";
    return;
  }
  const words = text.split(/\s+/).length;
  draftSignal.textContent = `${words} word${words === 1 ? "" : "s"}`;
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => {
      button.textContent = original;
    }, 1200);
  } catch (error) {
    button.textContent = "Copy failed";
  }
}

async function sendMessage() {
  const text = messageInput.value.trim();
  const token = localStorage.getItem(STORAGE_KEYS.token);
  if (!text || !token) {
    return;
  }

  persistInputs();
  addMessage(text, "user", `Role: ${roleInput.value || "unknown"}`);
  messageInput.value = "";
  updateDraftSignal();

  addMessage("Thinking...", "agent");
  const thinkingBubble = chatLog.lastElementChild;
  const startedAt = performance.now();

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        query: text,
        session_id: sessionIdInput.value.trim(),
        model_preference: modelSelect.value,
        stream: true,
      }),
    });

    if (response.status === 401) {
      logout();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    thinkingBubble.remove();
    const resultBubble = createBubble("", "agent", "Typing...");
    chatLog.appendChild(resultBubble);
    chatLog.scrollTop = chatLog.scrollHeight;
    
    const contentDiv = resultBubble.querySelector(".bubble-content");
    const metaDiv = resultBubble.querySelector(".chat-meta");
    let accumulatedText = "";

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();
      
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const jsonStr = line.substring(6);
          if (jsonStr === "[DONE]") continue;
          try {
            const data = JSON.parse(jsonStr);
            if (data.chunk) {
              accumulatedText += data.chunk;
              contentDiv.innerHTML = typeof marked !== "undefined" ? marked.parse(accumulatedText) : accumulatedText;
              chatLog.scrollTop = chatLog.scrollHeight;
            }
            if (data.done) {
              const latencyMs = Math.round(performance.now() - startedAt);
              metaDiv.textContent = `Trace: ${data.trace_id} | Approval: ${data.approval_required ? "required" : "none"} | ${latencyMs} ms`;
              
              const actionsEl = document.createElement("div");
              actionsEl.className = "bubble-actions";
              
              const btn1 = document.createElement("button");
              btn1.className = "bubble-action primary";
              btn1.textContent = "Copy answer";
              btn1.onclick = (e) => copyText(accumulatedText, e.currentTarget);
              actionsEl.appendChild(btn1);
              
              const btn2 = document.createElement("button");
              btn2.className = "bubble-action secondary";
              btn2.textContent = "Reuse prompt";
              btn2.onclick = () => {
                 messageInput.value = text;
                 updateDraftSignal();
                 messageInput.focus();
              };
              actionsEl.appendChild(btn2);
              
              resultBubble.appendChild(actionsEl);
              chatLog.scrollTop = chatLog.scrollHeight;
            }
          } catch (e) {
             console.error("Parse error", e);
          }
        }
      }
    }
  } catch (error) {
    thinkingBubble.remove();
    addMessage("Something went wrong. Please try again.", "agent", "Error");
  }
}

sendBtn.addEventListener("click", sendMessage);
logoutBtn.addEventListener("click", logout);
clearBtn.addEventListener("click", () => {
  chatLog.innerHTML = "";
});
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});
messageInput.addEventListener("input", updateDraftSignal);
[sessionIdInput, modelSelect].forEach((input) => input.addEventListener("change", persistInputs));

async function fetchContext() {
  const token = localStorage.getItem(STORAGE_KEYS.token);
  if (!token) return;
  const headers = { Authorization: `Bearer ${token}` };
  const role = (roleInput?.value || "").trim();
  setLoadingKpis();

  try {
    const [leavesRes, ticketsRes, assetsRes] = await Promise.all([
      fetch("/api/context/leaves", { headers }),
      fetch("/api/context/tickets", { headers }),
      fetch("/api/context/assets", { headers }),
    ]);

    if (leavesRes.ok) {
      const leaves = await leavesRes.json();
      renderLeaves(leaves);
      window.__ctxLeaves = leaves;
    }
    if (ticketsRes.ok) {
      const tickets = await ticketsRes.json();
      renderTickets(tickets);
      window.__ctxTickets = tickets;
    }
    if (assetsRes.ok) {
      const assets = await assetsRes.json();
      renderAssets(assets, role);
      window.__ctxAssets = assets;
    }

    // Fallback quick-action panel in the existing context area:
    // manager/it_lead can approve directly from side cards.
    if (role === "manager" || role === "it_lead") {
      const approvalsRes = await fetch("/approvals/pending", { headers });
      if (approvalsRes.ok) {
        const pending = await approvalsRes.json();
        renderQuickApprovals(pending, role);
        renderKpis({
          role,
          leaves: window.__ctxLeaves || [],
          tickets: window.__ctxTickets || [],
          assets: window.__ctxAssets || [],
          pendingLeave: (pending.leave || []).length,
          pendingAsset: (pending.asset || []).length,
        });
      } else {
        renderKpis({
          role,
          leaves: window.__ctxLeaves || [],
          tickets: window.__ctxTickets || [],
          assets: window.__ctxAssets || [],
          pendingLeave: 0,
          pendingAsset: 0,
        });
      }
    } else {
      renderKpis({
        role,
        leaves: window.__ctxLeaves || [],
        tickets: window.__ctxTickets || [],
        assets: window.__ctxAssets || [],
        pendingLeave: 0,
        pendingAsset: 0,
      });
    }
    updateLastSync();
  } catch (error) {
    console.error("Failed to fetch context", error);
    showToast("Failed to refresh context", "error");
  }
}

function renderLeaves(leaves) {
  if (!leaves.length) {
    leavesContainer.innerHTML = "No leave requests found.";
    return;
  }
  leavesContainer.innerHTML = leaves.map(l => `
    <div class="context-card">
      <div class="context-card-title">
        <span>${l.leave_type}</span>
        <span class="status-badge ${l.status.toLowerCase()}">${l.status}</span>
      </div>
      <div class="context-card-meta">${l.start_date} to ${l.end_date}</div>
    </div>
  `).join("");
}

function renderTickets(tickets) {
  if (!tickets.length) {
    ticketsContainer.innerHTML = "No tickets found.";
    return;
  }
  ticketsContainer.innerHTML = tickets.map(t => `
    <div class="context-card">
      <div class="context-card-title">
        <span>#${t.id} ${t.issue_type}</span>
        <span class="status-badge ${t.status.toLowerCase()}">${t.status}</span>
      </div>
      <div class="context-card-meta">Priority: ${t.priority}</div>
    </div>
  `).join("");
}

function renderAssets(assets, role = "") {
  if (!assets.length) {
    assetsContainer.innerHTML = "No asset requests found.";
    return;
  }
  // Managers and IT leads should primarily action approvals, not browse raw asset list.
  if (role === "manager" || role === "it_lead") {
    assetsContainer.innerHTML = "Loading approval queue...";
    return;
  }
  assetsContainer.innerHTML = assets.map(a => `
    <div class="context-card">
      <div class="context-card-title">
        <span>${a.asset_type}</span>
        <span class="status-badge ${a.status.toLowerCase()}">${a.status.replace(/_/g, ' ')}</span>
      </div>
      <div class="context-card-meta">Stage: ${a.approval_stage.replace(/_/g, ' ')}</div>
    </div>
  `).join("");
}

function renderQuickApprovals(pending, role) {
  const h2 = assetsContainer.previousElementSibling;
  if (h2 && h2.tagName === "H2") {
    h2.textContent = "Pending Approvals";
  }

  const leave = pending.leave || [];
  const asset = pending.asset || [];
  const cards = [];
  if (role === "manager") {
    leave.forEach((l) => {
      cards.push(`
        <div class="context-card">
          <div class="context-card-title">
            <span>Leave #${l.request_id}</span>
            <span class="status-badge pending">manager approval</span>
          </div>
          <div class="context-card-meta">${l.employee_id} | ${l.start_date} to ${l.end_date}</div>
          <div class="bubble-actions">
            <button class="bubble-action" data-approval-action="approve" data-approval-id="${l.approval_id}">Approve</button>
            <button class="bubble-action" data-approval-action="reject" data-approval-id="${l.approval_id}">Reject</button>
          </div>
        </div>
      `);
    });
  }
  asset.forEach((a) => {
    cards.push(`
      <div class="context-card">
        <div class="context-card-title">
          <span>${a.asset_type} (asset #${a.asset_id})</span>
          <span class="status-badge pending">${(a.approval_stage || "").replace(/_/g, " ")}</span>
        </div>
        <div class="context-card-meta">Requested by ${a.requested_by}</div>
        <div class="bubble-actions">
          <button class="bubble-action" data-approval-action="approve" data-approval-id="${a.approval_id}">Approve</button>
          <button class="bubble-action" data-approval-action="reject" data-approval-id="${a.approval_id}">Reject</button>
        </div>
      </div>
    `);
  });
  if (!cards.length) {
    assetsContainer.innerHTML = "No pending approvals.";
    return;
  }
  assetsContainer.innerHTML = cards.join("");
  wireContextApprovalActions();
}

function wireContextApprovalActions() {
  assetsContainer.querySelectorAll("button[data-approval-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.getAttribute("data-approval-action");
      const approval_id = Number(button.getAttribute("data-approval-id"));
      if (!approval_id || !action) return;
      await apiFetch("/approvals/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id, action }),
      });
      await fetchContext();
      const role = localStorage.getItem(STORAGE_KEYS.role) || "";
      const activeLabel = roleMenu?.querySelector(".role-menu-item.active")?.textContent || "";
      const active = menuConfigForRole(role).find((x) => x.label === activeLabel);
      if (active) setRoleView(active.id, role);
    });
  });
}

function authHeaders() {
  const token = localStorage.getItem(STORAGE_KEYS.token);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), ...authHeaders() },
  });
  if (response.status === 401) {
    logout();
    throw new Error("Unauthorized");
  }
  return response;
}

function menuConfigForRole(role) {
  if (role === "admin") {
    return [
      { id: "users", label: "User Management" },
      { id: "audit", label: "Audit Logs" },
      { id: "system", label: "System Dashboard" },
    ];
  }
  if (role === "it_lead") {
    return [
      { id: "tickets_all", label: "All Tickets" },
      { id: "assign_tickets", label: "Assign Tickets" },
      { id: "inventory", label: "Inventory" },
      { id: "it_approvals", label: "IT Approvals" },
    ];
  }
  if (role === "manager") {
    return [
      { id: "leave_approvals", label: "Leave Approvals" },
      { id: "asset_approvals", label: "Asset Approvals" },
      { id: "approval_history", label: "Approval History" },
    ];
  }
  return [
    { id: "my_tickets", label: "My Tickets" },
    { id: "leave_mgmt", label: "Leave Management" },
    { id: "my_assets", label: "Asset Requests" },
    { id: "approval_status", label: "Approval Status" },
  ];
}

function renderRoleMenu(role) {
  if (!roleMenu || !roleView) return;
  const items = menuConfigForRole(role);
  roleMenu.innerHTML = "";
  items.forEach((item, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `role-menu-item ${i === 0 ? "active" : ""}`;
    button.textContent = item.label;
    button.addEventListener("click", () => {
      [...roleMenu.querySelectorAll(".role-menu-item")].forEach((x) => x.classList.remove("active"));
      button.classList.add("active");
      setRoleView(item.id, role);
    });
    roleMenu.appendChild(button);
  });
  if (items[0]) setRoleView(items[0].id, role);
}

function escapeHtml(text) {
  return String(text || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function renderSimpleTable(headers, rows) {
  return `
    <div class="role-table-wrap">
      <table class="role-table">
        <thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${rows.join("") || `<tr><td colspan="${headers.length}" class="role-view-muted">No data.</td></tr>`}</tbody>
      </table>
    </div>
  `;
}

async function setRoleView(viewId, role) {
  if (!roleView) return;
  roleView.innerHTML = `<div class="role-view-muted shimmer">Loading...</div>`;
  try {
    if (viewId === "my_tickets") {
      const res = await apiFetch("/tickets/my");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["ID", "Issue", "Priority", "Status"],
        data.map((t) => `<tr><td>${t.id}</td><td>${escapeHtml(t.issue_type)}</td><td>${escapeHtml(t.priority)}</td><td>${escapeHtml(t.status)}</td></tr>`),
      );
      return;
    }
    if (viewId === "tickets_all" || viewId === "assign_tickets") {
      const res = await apiFetch("/tickets/all");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["ID", "User", "Issue", "Status", "Assign", "Resolve"],
        data.map((t) => `<tr><td>${t.id}</td><td>${escapeHtml(t.user_id)}</td><td>${escapeHtml(t.issue_type)}</td><td>${escapeHtml(t.status)}</td><td><button class="mini-btn" data-action="assign" data-ticket-id="${t.id}">Assign</button></td><td><button class="mini-btn" data-action="resolve" data-ticket-id="${t.id}">Resolve</button></td></tr>`),
      );
      wireTicketActions();
      showToast("Tickets loaded");
      return;
    }
    if (viewId === "inventory") {
      const res = await apiFetch("/inventory");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["Asset", "Qty", "Updated"],
        data.map((i) => `<tr><td>${escapeHtml(i.asset_type)}</td><td>${i.quantity}</td><td>${escapeHtml(i.updated_at)}</td></tr>`),
      );
      return;
    }
    if (viewId === "leave_approvals") {
      const res = await apiFetch("/leave/pending");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["Approval", "Request", "Employee", "Dates", "Action"],
        data.map((l) => `<tr><td>${l.approval_id}</td><td>${l.request_id}</td><td>${escapeHtml(l.employee_id)}</td><td>${escapeHtml(l.start_date)} to ${escapeHtml(l.end_date)}</td><td><button class="mini-btn success" data-approval-action="approve" data-approval-id="${l.approval_id}">Approve</button> <button class="mini-btn danger" data-approval-action="reject" data-approval-id="${l.approval_id}">Reject</button></td></tr>`),
      );
      wireApprovalActions();
      showToast("Leave approvals ready");
      return;
    }
    if (viewId === "asset_approvals" || viewId === "it_approvals") {
      const res = await apiFetch("/approvals/pending");
      const data = res.ok ? await res.json() : {};
      const assets = data.asset || [];
      roleView.innerHTML = renderSimpleTable(
        ["Approval", "Asset", "Requester", "Type", "Stage", "Action"],
        assets.map((a) => `<tr><td>${a.approval_id}</td><td>${a.asset_id}</td><td>${escapeHtml(a.requested_by)}</td><td>${escapeHtml(a.asset_type)}</td><td>${escapeHtml(a.approval_stage)}</td><td><button class="mini-btn success" data-approval-action="approve" data-approval-id="${a.approval_id}">Approve</button> <button class="mini-btn danger" data-approval-action="reject" data-approval-id="${a.approval_id}">Reject</button></td></tr>`),
      );
      wireApprovalActions();
      showToast("Approval queue loaded");
      return;
    }
    if (viewId === "leave_mgmt") {
      const res = await apiFetch("/leave/my");
      const data = res.ok ? await res.json() : { balance: 0, history: [] };
      roleView.innerHTML = `
        <div class="role-view-muted">Balance: ${data.balance} days</div>
        <div class="role-form-grid">
          <input id="leaveStart" placeholder="Start YYYY-MM-DD" />
          <input id="leaveEnd" placeholder="End YYYY-MM-DD" />
        </div>
        <button class="mini-btn success" id="leaveApplyBtn" type="button">Apply Leave</button>
        ${renderSimpleTable(["ID", "Type", "Dates", "Status"], (data.history || []).map((l) => `<tr><td>${l.id}</td><td>${escapeHtml(l.leave_type)}</td><td>${escapeHtml(l.start_date)} to ${escapeHtml(l.end_date)}</td><td>${escapeHtml(l.status)}</td></tr>`))}
      `;
      document.getElementById("leaveApplyBtn")?.addEventListener("click", async () => {
        const start_date = document.getElementById("leaveStart")?.value?.trim();
        const end_date = document.getElementById("leaveEnd")?.value?.trim();
        if (!start_date || !end_date) return;
        await apiFetch("/leave/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start_date, end_date, leave_type: "general" }),
        });
        setRoleView("leave_mgmt", role);
        fetchContext();
        showToast("Leave request submitted", "success");
      });
      return;
    }
    if (viewId === "my_assets") {
      const res = await apiFetch("/assets/my");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["ID", "Type", "Status", "Stage", "Action"],
        data.map((a) => `<tr><td>${a.id}</td><td>${escapeHtml(a.asset_type)}</td><td>${escapeHtml(a.status)}</td><td>${escapeHtml(a.approval_stage)}</td><td></td></tr>`),
      );
      roleView.innerHTML += `
        <div class="role-form-grid" style="margin-top:8px;">
          <input id="assetTypeInput" placeholder="Asset type (e.g. laptop)" />
          <button class="mini-btn success" id="assetReqBtn" type="button">Request Asset</button>
        </div>
      `;
      document.getElementById("assetReqBtn")?.addEventListener("click", async () => {
        const asset_type = document.getElementById("assetTypeInput")?.value?.trim() || "";
        if (!asset_type) return;
        await apiFetch("/assets/request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ asset_type }),
        });
        setRoleView("my_assets", role);
        fetchContext();
        showToast("Asset request submitted", "success");
      });
      return;
    }
    if (viewId === "approval_status" || viewId === "approval_history") {
      const res = await apiFetch("/approvals/history");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["Approval", "Type", "Request", "Stage", "Status", "Approver"],
        data.map((a) => `<tr><td>${a.approval_id}</td><td>${escapeHtml(a.request_type)}</td><td>${a.request_id}</td><td>${escapeHtml(a.approval_stage)}</td><td>${escapeHtml(a.status)}</td><td>${escapeHtml(a.approver_id)}</td></tr>`),
      );
      return;
    }
    if (viewId === "users") {
      const res = await apiFetch("/admin/users");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["User", "Email", "Role", "Department"],
        data.map((u) => `<tr><td>${escapeHtml(u.user_id)}</td><td>${escapeHtml(u.email)}</td><td>${escapeHtml(u.role)}</td><td>${escapeHtml(u.department)}</td></tr>`),
      );
      return;
    }
    if (viewId === "audit") {
      const res = await apiFetch("/admin/audit-logs");
      const data = res.ok ? await res.json() : [];
      roleView.innerHTML = renderSimpleTable(
        ["ID", "User", "Event", "Detail"],
        data.map((l) => `<tr><td>${l.id}</td><td>${escapeHtml(l.user_id)}</td><td>${escapeHtml(l.event_type)}</td><td>${escapeHtml(l.detail)}</td></tr>`),
      );
      return;
    }
    roleView.innerHTML = `<div class="role-view-muted">System Dashboard</div>`;
  } catch (err) {
    roleView.innerHTML = `<div class="role-view-muted">Failed to load section.</div>`;
    showToast("Section load failed", "error");
  }
}

function wireApprovalActions() {
  roleView.querySelectorAll("button[data-approval-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const approval_id = Number(button.getAttribute("data-approval-id"));
      const action = button.getAttribute("data-approval-action");
      await apiFetch("/approvals/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id, action }),
      });
      const role = localStorage.getItem(STORAGE_KEYS.role) || "employee";
      const activeLabel = roleMenu?.querySelector(".role-menu-item.active")?.textContent || "";
      const id = menuConfigForRole(role).find((x) => x.label === activeLabel)?.id || "";
      if (id) setRoleView(id, role);
      fetchContext();
      showToast(`Approval ${action}d`, "success");
    });
  });
}

function wireTicketActions() {
  roleView.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.getAttribute("data-action");
      const ticket_id = Number(button.getAttribute("data-ticket-id"));
      if (!ticket_id) return;
      if (action === "assign") {
        const engineer_id = prompt("Assign to engineer id/email:");
        if (!engineer_id) return;
        await apiFetch("/tickets/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticket_id, engineer_id }),
        });
        showToast("Ticket assigned", "success");
      } else {
        await apiFetch("/tickets/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticket_id }),
        });
        showToast("Ticket resolved", "success");
      }
      const role = localStorage.getItem(STORAGE_KEYS.role) || "employee";
      setRoleView(action === "assign" ? "assign_tickets" : "tickets_all", role);
      fetchContext();
    });
  });
}

async function init() {
  const ok = await bootstrapIdentity();
  if (!ok) {
    return;
  }
  setDefaults();
  renderPromptStrip();
  updateDraftSignal();
  checkHealth();
  fetchContext();
  renderRoleMenu(roleInput.value || "employee");
  if (refreshContextBtn) {
    refreshContextBtn.addEventListener("click", () => {
      fetchContext();
      const role = localStorage.getItem(STORAGE_KEYS.role) || "";
      const active = roleMenu?.querySelector(".role-menu-item.active")?.textContent || "";
      const next = menuConfigForRole(role).find((x) => x.label === active)?.id;
      if (next) setRoleView(next, role);
    });
  }
  if (autoRefreshToggle) {
    const setAuto = () => {
      if (autoRefreshTimer) clearInterval(autoRefreshTimer);
      if (autoRefreshToggle.checked) {
        autoRefreshTimer = setInterval(() => {
          fetchContext();
        }, 15000);
      }
    };
    autoRefreshToggle.addEventListener("change", setAuto);
    setAuto();
  }
}

init();
