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

const PROMPTS = [
  { label: "Paternity policy", text: "what is paternity leave policy", tone: "hr" },
  { label: "Leave balance", text: "what is my leave balance", tone: "hr" },
  { label: "Laptop ticket", text: "raise an IT ticket for laptop issue", tone: "it" },
  { label: "Expense rules", text: "what is expense reimbursement policy", tone: "finance" },
  { label: "Onsite procedure", text: "what is the onsite procedures", tone: "policy" },
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
      }),
    });

    if (response.status === 401) {
      logout();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    thinkingBubble.remove();
    const meta = `Trace: ${data.trace_id} | Approval: ${data.approval_required ? "required" : "none"}`;
    const latencyMs = Math.round(performance.now() - startedAt);
    addMessage(data.response, "agent", `${meta} | ${latencyMs} ms`, [
      {
        label: "Copy answer",
        kind: "primary",
        onClick: (event) => copyText(data.response, event.currentTarget),
      },
      {
        label: "Reuse prompt",
        kind: "secondary",
        onClick: () => {
          messageInput.value = text;
          updateDraftSignal();
          messageInput.focus();
        },
      },
    ]);
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

  try {
    const [leavesRes, ticketsRes, assetsRes] = await Promise.all([
      fetch("/api/context/leaves", { headers }),
      fetch("/api/context/tickets", { headers }),
      fetch("/api/context/assets", { headers }),
    ]);

    if (leavesRes.ok) {
      const leaves = await leavesRes.json();
      renderLeaves(leaves);
    }
    if (ticketsRes.ok) {
      const tickets = await ticketsRes.json();
      renderTickets(tickets);
    }
    if (assetsRes.ok) {
      const assets = await assetsRes.json();
      renderAssets(assets);
    }
  } catch (error) {
    console.error("Failed to fetch context", error);
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

function renderAssets(assets) {
  if (!assets.length) {
    assetsContainer.innerHTML = "No asset requests found.";
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
}

init();
