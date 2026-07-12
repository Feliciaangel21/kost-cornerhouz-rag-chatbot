const API_URL = `${window.location.origin}/chat`;
const SYNC_URL = `${window.location.origin}/sync-on-refresh`;
const CHAT_HISTORY_KEY = "kostmate_chat_history";
const CHAT_HISTORY_LIMIT = 4;

function getChatSessionId() {
  const storageKey = "kostmate_chat_session_id";
  let sessionId = sessionStorage.getItem(storageKey);

  if (!sessionId) {
    sessionId = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `web_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(storageKey, sessionId);
  }

  return sessionId;
}

const CHAT_SESSION_ID = getChatSessionId();

function getRecentChatHistory() {
  try {
    const history = JSON.parse(sessionStorage.getItem(CHAT_HISTORY_KEY) || "[]");
    if (!Array.isArray(history)) return [];

    return history
      .filter(function (item) {
        return (
          item &&
          (item.role === "user" || item.role === "assistant") &&
          typeof item.content === "string" &&
          item.content.trim()
        );
      })
      .slice(-CHAT_HISTORY_LIMIT);
  } catch (error) {
    return [];
  }
}

function rememberChatMessage(role, content) {
  const history = getRecentChatHistory();
  history.push({ role, content });
  sessionStorage.setItem(
    CHAT_HISTORY_KEY,
    JSON.stringify(history.slice(-CHAT_HISTORY_LIMIT))
  );
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function linkify(text) {
  let escapedText = escapeHtml(text || "");

  const links = [];

  // Markdown links: [Instagram Kost.cornerhouz](https://...)
  escapedText = escapedText.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    function (_, label, url) {
      const placeholder = `__LINK_${links.length}__`;
      links.push(
        `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
      );
      return placeholder;
    }
  );

  // Raw URLs: https://...
  escapedText = escapedText.replace(/(https?:\/\/[^\s<]+)/g, function (url) {
    const placeholder = `__LINK_${links.length}__`;
    links.push(
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
    );
    return placeholder;
  });

  links.forEach(function (html, index) {
    escapedText = escapedText.replace(`__LINK_${index}__`, html);
  });

  // Important: make backend \n show as real line breaks
  escapedText = escapedText.replace(/\n/g, "<br>");

  return escapedText;
}

async function sendMessage() {
  const input = document.getElementById("message-input");
  const message = input.value.trim();

  if (!message) return;

  const conversationHistory = getRecentChatHistory();

  addMessage(message, "user");
  rememberChatMessage("user", message);
  input.value = "";

  addMessage("Sebentar ya kak...", "bot");

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        session_id: CHAT_SESSION_ID,
        message: message,
        conversation_history: conversationHistory
      })
    });

    const data = await response.json();

    removeLoadingMessage();
    addMessage(data.reply, "bot");
    rememberChatMessage("assistant", data.reply);

    console.log("Chat result:", data);
  } catch (error) {
    removeLoadingMessage();
    addMessage(
      "Maaf kak, sistemnya sedang bermasalah. Coba lagi sebentar ya.",
      "bot"
    );
    console.error(error);
  }
}

async function syncAll() {
  addMessage("Sedang sync data dari Google Sheets...", "bot");

  try {
    const response = await fetch(SYNC_URL, {
      method: "POST"
    });

    const data = await response.json();

    addMessage(
      `Data berhasil disync kak. Rooms loaded: ${data.rooms_loaded}, available rooms: ${data.available_rooms}.`,
      "bot"
    );

    console.log("Sync result:", data);
  } catch (error) {
    addMessage("Sync gagal. Coba cek backend atau koneksi Google Sheets ya.", "bot");
    console.error(error);
  }
}

async function syncOnPageLoad() {
  try {
    const response = await fetch(SYNC_URL, {
      method: "POST"
    });
    const data = await response.json();
    console.log("Page refresh sync result:", data);
  } catch (error) {
    console.warn("Page refresh sync failed:", error);
  }
}

function addMessage(text, sender) {
  const chatBox = document.getElementById("chat-box");
  const div = document.createElement("div");

  div.className = `message ${sender}`;

  if (sender === "bot") {
    div.innerHTML = linkify(text);
  } else {
    div.textContent = text;
  }

  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function removeLoadingMessage() {
  const chatBox = document.getElementById("chat-box");
  const messages = chatBox.querySelectorAll(".message.bot");
  const last = messages[messages.length - 1];

  if (last && last.textContent === "Sebentar ya kak...") {
    last.remove();
  }
}

document
  .getElementById("message-input")
  .addEventListener("keydown", function(event) {
    if (event.key === "Enter") {
      sendMessage();
    }
  });

window.addEventListener("load", syncOnPageLoad);
