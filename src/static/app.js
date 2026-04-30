const chatLog = document.getElementById("chatLog");
const messageInput = document.getElementById("message");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearChat");
const userIdInput = document.getElementById("userId");
const sessionIdInput = document.getElementById("sessionId");
const roleSelect = document.getElementById("role");
const apiStatus = document.getElementById("apiStatus");

const STORAGE_KEYS = {
  userId: "agent.userId",
  sessionId: "agent.sessionId",
  role: "agent.role",
};

function setDefaultIds() {
  const storedUser = localStorage.getItem(STORAGE_KEYS.userId);
  const storedSession = localStorage.getItem(STORAGE_KEYS.sessionId);
  const storedRole = localStorage.getItem(STORAGE_KEYS.role);

  userIdInput.value = storedUser || `user-${crypto.randomUUID().slice(0, 8)}`;
  sessionIdInput.value = storedSession || `session-${crypto.randomUUID().slice(0, 8)}`;
  roleSelect.value = storedRole || "employee";
}

function persistInputs() {
  localStorage.setItem(STORAGE_KEYS.userId, userIdInput.value.trim());
  localStorage.setItem(STORAGE_KEYS.sessionId, sessionIdInput.value.trim());
  localStorage.setItem(STORAGE_KEYS.role, roleSelect.value);
}

function createBubble(text, type, meta) {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-bubble ${type}`;

  const content = document.createElement("div");
  content.textContent = text;

  wrapper.appendChild(content);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "chat-meta";
    metaEl.textContent = meta;
    wrapper.appendChild(metaEl);
  }

  return wrapper;
}

function addMessage(text, type, meta) {
  const bubble = createBubble(text, type, meta);
  chatLog.appendChild(bubble);
  chatLog.scrollTop = chatLog.scrollHeight;
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
  };

  addMessage("Thinking...", "agent");
  const thinkingBubble = chatLog.lastElementChild;

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
    addMessage(data.response, "agent", meta);
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

[userIdInput, sessionIdInput, roleSelect].forEach((input) => {
  input.addEventListener("change", persistInputs);
});

setDefaultIds();
checkHealth();
