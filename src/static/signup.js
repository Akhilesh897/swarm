const signupBtn = document.getElementById("signupBtn");
const authStatus = document.getElementById("authStatus");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");

const STORAGE_KEYS = {
  email: "agent.email",
  token: "agent.token",
  userId: "agent.userId",
  role: "agent.role",
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

function saveAuth(data, email) {
  localStorage.setItem(STORAGE_KEYS.token, data.access_token);
  localStorage.setItem(STORAGE_KEYS.email, email);
  localStorage.setItem(STORAGE_KEYS.userId, data.user_id || "");
  localStorage.setItem(STORAGE_KEYS.role, data.role || "");
}

async function signup() {
  const email = emailInput.value.trim().toLowerCase();
  const password = passwordInput.value;
  if (!email || !password) {
    authStatus.textContent = "Enter email and password.";
    return;
  }

  authStatus.textContent = "Creating account...";
  try {
    const response = await fetch("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }

    saveAuth(data, email);
    authStatus.textContent = "Account created. Opening workspace...";
    window.location.href = rolePath(data.role);
  } catch (error) {
    authStatus.textContent = error.message || "Signup failed.";
  }
}

signupBtn.addEventListener("click", signup);
passwordInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    signup();
  }
});
