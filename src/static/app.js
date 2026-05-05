const chatLog = document.getElementById("chatLog");
const messageInput = document.getElementById("message");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearChat");
const userIdInput = document.getElementById("userId");
const sessionIdInput = document.getElementById("sessionId");
const roleSelect = document.getElementById("role");
const modelSelect = document.getElementById("modelSelect");
const apiStatus = document.getElementById("apiStatus");
const promptStrip = document.getElementById("promptStrip");
const draftSignal = document.getElementById("draftSignal");

const PROMPTS = [
  { label: "Paternity policy", text: "what is paternity leave policy", tone: "hr" },
  { label: "Leave balance", text: "what is my leave balance", tone: "hr" },
  { label: "Laptop ticket", text: "raise an IT ticket for laptop issue", tone: "it" },
  { label: "Expense rules", text: "what is expense reimbursement policy", tone: "finance" },
  { label: "Onsite procedure", text: "what is the onsite procedures", tone: "policy" },
];

const STORAGE_KEYS = {
  userId: "agent.userId",
  sessionId: "agent.sessionId",
  role: "agent.role",
  model: "agent.model",
};

function setDefaultIds() {
  const storedUser = localStorage.getItem(STORAGE_KEYS.userId);
  const storedSession = localStorage.getItem(STORAGE_KEYS.sessionId);
  const storedRole = localStorage.getItem(STORAGE_KEYS.role);
  const storedModel = localStorage.getItem(STORAGE_KEYS.model);

  userIdInput.value = storedUser || `user-${crypto.randomUUID().slice(0, 8)}`;
  sessionIdInput.value = storedSession || `session-${crypto.randomUUID().slice(0, 8)}`;
  roleSelect.value = storedRole || "employee";
  modelSelect.value = storedModel || "auto";
}

function persistInputs() {
  localStorage.setItem(STORAGE_KEYS.userId, userIdInput.value.trim());
  localStorage.setItem(STORAGE_KEYS.sessionId, sessionIdInput.value.trim());
  localStorage.setItem(STORAGE_KEYS.role, roleSelect.value);
  localStorage.setItem(STORAGE_KEYS.model, modelSelect.value);
}

function createBubble(text, type, meta, actions = []) {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-bubble ${type}`;

  const content = document.createElement("div");
  content.className = "bubble-content";
  content.textContent = text;

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

async function checkHealth() {
  try {
    const response = await fetch("/health");
    apiStatus.textContent = response.ok ? "Online" : "Degraded";
  } catch (error) {
    apiStatus.textContent = "Offline";
  }
}

async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text) {
    return;
  }

  persistInputs();
  addMessage(text, "user", `Role: ${roleSelect.value}`);
  messageInput.value = "";

  const payload = {
    user_id: userIdInput.value.trim(),
    role: roleSelect.value,
    query: text,
    session_id: sessionIdInput.value.trim(),
    model_preference: modelSelect.value,
  };

  addMessage("Thinking...", "agent");
  const thinkingBubble = chatLog.lastElementChild;
  const startedAt = performance.now();

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

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

[userIdInput, sessionIdInput, roleSelect].forEach((input) => {
  input.addEventListener("change", persistInputs);
});

modelSelect.addEventListener("change", () => {
  persistInputs();
  sessionIdInput.value = `session-${crypto.randomUUID().slice(0, 8)}`;
  chatLog.innerHTML = "";
});

setDefaultIds();
renderPromptStrip();
checkHealth();
