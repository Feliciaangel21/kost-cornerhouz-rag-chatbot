const API_URL = `${window.location.origin}/chat`;
const SYNC_URL = `${window.location.origin}/admin/sync-all`;

async function sendMessage() {
  const input = document.getElementById("message-input");
  const message = input.value.trim();

  if (!message) return;

  addMessage(message, "user");
  input.value = "";

  addMessage("Sebentar ya kak...", "bot");

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        session_id: "web_user",
        message: message
      })
    });

    const data = await response.json();

    removeLoadingMessage();
    addMessage(data.reply, "bot");

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

function addMessage(text, sender) {
  const chatBox = document.getElementById("chat-box");
  const div = document.createElement("div");

  div.className = `message ${sender}`;
  div.textContent = text;

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
