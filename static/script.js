lucide.createIcons();

let activeSession = null;
let sessions = {};
const sessionList = document.getElementById("chat-sessions");
const chatWindow = document.getElementById("chat-window");
const sendBtn = document.getElementById("send-btn");
const msgInput = document.getElementById("message-input");
const newChatBtn = document.getElementById("new-chat");

const toolsPanel = document.getElementById("tools-panel");
const companySelect = document.getElementById("company-select");
const toolsContainer = document.getElementById("tools-container");

document.getElementById("run-tool-button").onclick = () =>
  toolsPanel.classList.toggle("hidden");
document.getElementById("close-tools-panel").onclick = () =>
  toolsPanel.classList.add("hidden");

const toolsByCompany = {
  TCC: ["Modem Signal levels", "Equipment Details"],
  VCC: ["ServiceNow", "AppHub"],
  RiskRadar: ["Churn"],
};


function buildCompactTable(headers, rows) {
  return `
    <table class="compact-table">
      <thead>
        <tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr>
      </thead>
      <tbody>
        ${
          rows && rows.length
            ? rows.map(r => `
                <tr>${r.map(c => `<td>${c ?? "N/A"}</td>`).join("")}</tr>
              `).join("")
            : `<tr><td colspan="${headers.length}">No data available</td></tr>`
        }
      </tbody>
    </table>
  `;
}

function fmt(val) {
  return val === null || val === undefined || val === "" ? "N/A" : val;
}


// =================== TIME FORMATTERS ===================


function to12HourFromDateTime(dateTimeStr) {
  if (!dateTimeStr || typeof dateTimeStr !== "string") return "N/A";

  // Expected format: YYYY-MM-DDTHH:mm:ss
  const parts = dateTimeStr.split("T");
  if (parts.length !== 2) return "N/A";

  const [hourStr, minuteStr] = parts[1].split(":");
  let hour = parseInt(hourStr, 10);
  const minute = minuteStr;

  const ampm = hour >= 12 ? "PM" : "AM";
  hour = hour % 12;
  hour = hour === 0 ? 12 : hour;

  return `${hour}:${minute} ${ampm}`;
}


// Convert ISO datetime ? "MM/DD/YYYY h:mm AM/PM"
function to12HourDateTime(dateStr) {
  if (!dateStr) return "N/A";

  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "N/A";

  const date = d.toLocaleDateString();
  const time = d.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  });

  return `${date} ${time}`;
}


function formatOfficeHoursRows(officeHours) {
  if (!Array.isArray(officeHours)) return [];

  return officeHours.map(d => [
    fmt(d.dayName),
    to12HourFromDateTime(d.timeOpen),
    to12HourFromDateTime(d.timeLunchStart),
    to12HourFromDateTime(d.timeLunchEnd),
    to12HourFromDateTime(d.timeClose),
  ]);
}



function generateSessionId() {
  return "sess-" + Date.now();
}

function renderSessions() {
  sessionList.innerHTML = "";
  Object.keys(sessions).forEach((id) => {
    const li = document.createElement("li");
    li.className =
      "flex justify-between items-center px-4 py-3 cursor-pointer hover:bg-gray-100 " +
      (id === activeSession ? "bg-gray-200 font-bold" : "");

    // Chat session name span (loads session on click)
    const span = document.createElement("span");
    span.textContent = sessions[id];
    span.className = "flex-1"; // allow span to take available space
    span.onclick = () => loadSession(id);

    // Close button
    const closeBtn = document.createElement("button");
    closeBtn.innerHTML = '<i data-lucide="x"></i>';
    closeBtn.className =
      "ml-2 text-gray-400 hover:text-red-500 flex items-center";
    closeBtn.title = "Close Chat";
    closeBtn.onclick = (e) => {
      e.stopPropagation(); // prevent loading session when clicking close
      delete sessions[id];

      if (activeSession === id) {
        activeSession = null;
        chatWindow.innerHTML = "";
      }

      renderSessions();
      lucide.createIcons();
    };

    li.appendChild(span);
    li.appendChild(closeBtn);
    sessionList.appendChild(li);
  });
  lucide.createIcons(); // render icons in close buttons
}

let assistantMessageCount = 0; // Track how many assistant messages have been shown

function addMessage(sender, text) {
  const chatWindow = document.getElementById("chat-window");
  const d = document.createElement("div");
  d.className = `flex ${sender === "User" ? "justify-end" : "justify-start"} items-start space-x-3 mb-2`;

  // ?? If assistant, convert Markdown to HTML before inserting
  const formattedText =
    sender === "Assistant" ? marked.parse(text) : text;

  if (sender === "User") {
    d.innerHTML = `
      <div class="max-w-xs md:max-w-md px-3 py-2 rounded-lg bg-purple-600 text-white break-words text-sm">
        ${formattedText}
      </div>`;
  } else {
    assistantMessageCount += 1; // increment for each assistant response
    const messageId = "msg-" + Date.now();

    // ?? First assistant message (no feedback icons)
    if (assistantMessageCount === 1) {
      d.innerHTML = `
        <img src="static/image.png" alt="agent" class="w-10 h-10 rounded-full flex-shrink-0" />
        <div class="max-w-4xl w-full px-3 py-2 rounded-lg bg-gray-200 text-black break-words text-sm relative markdown-body" id="${messageId}">
          ${formattedText}
        </div>`;
    } else {
      // ?? Subsequent assistant messages (with thumbs + copy)
      d.innerHTML = `
        <img src="static/image.png" alt="agent" class="w-10 h-10 rounded-full flex-shrink-0" />
        <div class="max-w-4xl w-full py-2 rounded-lg bg-gray-200 text-black break-words text-sm relative markdown-body" id="${messageId}">
          ${formattedText}
          <div class="flex items-center gap-3 mt-2 text-lg feedback-icons">
            <!-- Thumbs Up SVG -->
            <svg class="thumbs-up cursor-pointer" title="Thumbs Up" width="24" height="24" viewBox="0 0 24 24" fill="#EAEAEA" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L13.17 2 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h7c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1z"/>
            </svg>

            <!-- Thumbs Down SVG -->
            <svg class="thumbs-down cursor-pointer" title="Thumbs Down" width="24" height="24" viewBox="0 0 24 24" fill="#EAEAEA" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 3h4v12H2V3zm20 11c0 1.1-.9 2-2 2h-6.31l.95 4.57.03.32c0 .41-.17.79-.44 1.06L13.17 22l-5.58-5.59C7.22 16.05 7 15.55 7 15V5c0-1.1.9-2 2-2h7c.83 0 1.54.5 1.84 1.22l3.02 7.05c.09.23.14.47.14.73v1z"/>
            </svg>

            <span class="copy-btn cursor-pointer text-gray-600 hover:text-purple-600" title="Copy Message">ðŸ“‹</span>
            <select class="negative-dropdown hidden ml-1 border rounded text-sm">
              <option value="">Select reason</option>
              <option value="Irrelevant">Irrelevant</option>
              <option value="Incorrect">Incorrect</option>
              <option value="Vague">Vague</option>
              <option value="Confusing">Confusing</option>
              <option value="Incomplete">Incomplete</option>
            </select>
            <span class="thank-you hidden text-blue-600 text-sm ml-2">Thanks for your feedback!</span>
          </div>
        </div>`;
    }
  }
  
  chatWindow.appendChild(d);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  if (sender === "Assistant") {
  d.querySelectorAll("a").forEach(a => {
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener noreferrer");
  });
  }
  // Only initialize icons for non-first assistant messages
  if (sender === "Assistant" && assistantMessageCount > 1) {
    const msgContainer = d.querySelector(".markdown-body");
    const thumbsUp = msgContainer.querySelector(".thumbs-up");
    const thumbsDown = msgContainer.querySelector(".thumbs-down");
    const copyBtn = msgContainer.querySelector(".copy-btn");
    const dropdown = msgContainer.querySelector(".negative-dropdown");
    const thankYou = msgContainer.querySelector(".thank-you");

    /** âœ… Copy to clipboard
    copyBtn.addEventListener("click", () => {
    if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      copyBtn.textContent = "âœ…";
      setTimeout(() => (copyBtn.textContent = "ðŸ“‹"), 1000);
    });
     } else {
       const tempInput = document.createElement("input");
    tempInput.value = text;
    document.body.appendChild(tempInput);
    tempInput.select();
    document.execCommand("copy");
    document.body.removeChild(tempInput);
    copyBtn.textContent = "âœ…";
    setTimeout(() => (copyBtn.textContent = "ðŸ“‹"), 1000);
    }
   });
   
   // Copy to clipboard (RTF)
    copyBtn.addEventListener("click", async () => {
      const rtf = text; // text should now be an RTF string like "{\\rtf1\\ansi ...}"
    
      // Modern API path: write RTF as "text/rtf"
      async function copyRtfModern(rtfString) {
        const blob = new Blob([rtfString], { type: "text/rtf" });
        const item = new ClipboardItem({ "text/rtf": blob });
        await navigator.clipboard.write([item]);
      }
    
      // Fallback: copy via copy event + execCommand
      function copyRtfFallback(rtfString) {
        function onCopy(e) {
          e.clipboardData.setData("text/rtf", rtfString);
          // Optional: also provide plain text so pasting into plain editors still works
          e.clipboardData.setData("text/plain", rtfString);
          e.preventDefault();
        }
    
        document.addEventListener("copy", onCopy);
        document.execCommand("copy");
        document.removeEventListener("copy", onCopy);
      }
    
      try {
        if (navigator.clipboard && typeof ClipboardItem !== "undefined") {
          await copyRtfModern(rtf);
        } else {
          copyRtfFallback(rtf);
        }
    
        copyBtn.textContent =  "âœ…";
        setTimeout(() => (copyBtn.textContent =   "âœ…"), 1000);
      } catch (err) {
        console.error("Failed to copy RTF:", err);
        copyBtn.textContent = "âœ…";
        setTimeout(() => (copyBtn.textContent =   "âœ…"), 1500);
      }
    }); **/
    
    copyBtn.addEventListener("click", () => {
      // Clone ONLY the assistant message
      const contentClone = msgContainer.cloneNode(true);
    
      // Remove feedback / UI elements from clone
      contentClone.querySelectorAll(
        ".feedback-icons, .copy-btn, .thumbs-up, .thumbs-down, select, svg"
      ).forEach(el => el.remove());
    
      // Create hidden container for copy
      const tempDiv = document.createElement("div");
      tempDiv.style.position = "fixed";
      tempDiv.style.left = "-9999px";
      tempDiv.appendChild(contentClone);
      document.body.appendChild(tempDiv);
    
      // Select content
      const range = document.createRange();
      range.selectNodeContents(contentClone);
    
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    
      // Copy
      document.execCommand("copy");
    
      // Cleanup
      selection.removeAllRanges();
      document.body.removeChild(tempDiv);
    
      // UI feedback
      copyBtn.textContent = "âœ…";
      setTimeout(() => (copyBtn.textContent = "âœ…"), 1000);
    });



    // âœ… Feedback events
    thumbsUp.addEventListener("click", () => {
      sendFeedback(1, "Satisfied", thankYou);
    });

    thumbsDown.addEventListener("click", () => {
      dropdown.classList.remove("hidden");
      dropdown.focus();
    });

    dropdown.addEventListener("change", (e) => {
      const reason = e.target.value;
      if (reason) {
        sendFeedback(0, reason, thankYou);
        dropdown.classList.add("hidden");
        dropdown.value = "";
      }
    });
  }
}

// On page load, add the default message
window.onload = function () {
  addMessage("Assistant", "Hello! Ask me a question about our SOGs or use the wrench icon to run diagnostics.");
};

async function loadSession(id) {
  activeSession = id;
  chatWindow.innerHTML = "";
  renderSessions();

  try {
    const res = await fetch(`/api/history/${id}`);
    if (!res.ok) throw new Error("Failed to load history");
    const data = await res.json();

    // Only render if there is existing chat history
    if (data && data.length > 0) {
      data.forEach((item) => {
        if (item.type === "message") {
          addMessage(item.sender, item.message);
        } else if (item.type === "tool") {
          const tmpl = document.getElementById("tool-output-template").content.cloneNode(true);
          tmpl.querySelector(".tool-name").textContent = item.tool_name;
          tmpl.querySelector(".account-id").textContent = item.account_number;
          tmpl.querySelector(".tool-results").innerHTML =
          `<pre style="white-space: pre-wrap; word-wrap: break-word;">${item.message}</pre>`;
          chatWindow.appendChild(tmpl);
        }
      });
    } 
    // If no chat history, do nothing to show blank chat window (no assistant message)

    chatWindow.scrollTop = chatWindow.scrollHeight;
    lucide.createIcons();

  } catch (err) {
    addMessage("Assistant", "Sorry, could not load chat history for this session.");
    console.error(err);
  }
}

async function startNewChat() {
  const id = generateSessionId();
  const chatNum = Object.keys(sessions).length + 1;
  sessions[id] = `Chat ${chatNum}`;
  renderSessions();
  loadSession(id);
}

async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text || !activeSession) return;

  addMessage("User", text);
  msgInput.value = "";

  // Create "Typing..." message with animated dots
  const loadingDiv = document.createElement("div");
  loadingDiv.className = "flex justify-start items-start space-x-3 mb-2";
  loadingDiv.innerHTML = `
    <img src="static/image.png" alt="agent" class="w-10 h-10 rounded-full flex-shrink-0" />
    <div class="max-w-xs md:max-w-md px-3 py-2 rounded-lg bg-gray-200 text-black text-sm">
      <div class="typing-indicator">
        <span>Typing</span>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>`;
  chatWindow.appendChild(loadingDiv);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  try {
    const res = await fetch("/api/message", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session_id: activeSession,
        sender: "User",
        message: text,
      }),
    });

    if (!res.ok) throw new Error("Server error sending message");
    const data = await res.json();

    // Remove "Typing..." before showing actual response
    loadingDiv.remove();
    addMessage("Assistant", data.response);
  } catch (err) {
    loadingDiv.remove();
    addMessage("Assistant", "âš ï¸ Sorry, an error occurred sending your message.");
    console.error(err);
  }
}


function clearTools() {
  toolsContainer.innerHTML = "";
}

function renderTools(companyKey) {
  clearTools();
  if (!toolsByCompany[companyKey]) return;
  toolsByCompany[companyKey].forEach((tool) => {
    const btn = document.createElement("button");
    btn.className = "tool-button border p-2 rounded text-sm hover:bg-purple-50";
    btn.textContent = tool;
    btn.onclick = () => {
      const accountNumber = document.getElementById("account-number").value.trim();
      if (!accountNumber) {
        alert("Please enter an account number");
        return;
      }
      toolsPanel.classList.add("hidden");
      runTool(tool, accountNumber);
    };
    toolsContainer.appendChild(btn);
  });
}

companySelect.addEventListener("change", () => {
  renderTools(companySelect.value);
});

function runTool(toolName, accountNumber) {

  if (!activeSession) {
    alert("Please start or select a chat session before running a tool.");
    return;
  }

  const company = document.getElementById("company-select").value;
  
  const loadingDiv = document.createElement("div");
  loadingDiv.className = "flex justify-start items-start space-x-3 mb-2";
  loadingDiv.innerHTML = `
    <img src="static/image.png" alt="agent" class="w-10 h-10 rounded-full flex-shrink-0" />
    <div class="max-w-xs md:max-w-md px-3 py-2 rounded-lg bg-gray-200 text-black text-sm">
      Please wait<span class="typing-dots"></span> fetching data for <strong>${toolName}</strong> on account <strong>${accountNumber}</strong>.
    </div>
  `;
  chatWindow.appendChild(loadingDiv);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  fetch("/api/run_tool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: activeSession,
      tool_name: toolName,
      account_number: accountNumber,
      company: company,
      sender: "User"
    })
  })
  .then(res => {
    if (!res.ok) throw new Error("Failed to run tool");
    return res.json();
  })
  .then(data => {
  
    loadingDiv.remove();
    const tmpl = document.getElementById("tool-output-template").content.cloneNode(true);

    tmpl.querySelector(".tool-name").textContent = data.tool_name;
    tmpl.querySelector(".account-id").textContent = data.account_number;

    let outputHTML = "";

    // ---------------- SERVICE NOW ----------------
    if (data.tool_name === "ServiceNow" && Array.isArray(data.results)) {

      data.results.forEach(item => {

        let recentComment = "No comments";

        if (item.comments) {

          const commentBlocks = item.comments
          .split(/\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2} [AP]M - [^\n]+\n/)
          .filter(c => c.trim() !== "");

          if (commentBlocks.length > 0) {
            recentComment = commentBlocks[0].trim();
          }

        }

    outputHTML += `
        <div style="padding:8px 10px;margin-bottom:6px;border-radius:8px;background:#ffffff;">        
          <div style="
            display:grid;
            grid-template-columns:140px 1fr;  /* fixed width for labels */
            row-gap:3px;
            column-gap:12px;
            align-items:start;
          ">
        
            <strong style="text-align:left;">Ticket:</strong>
            <span>${item.ticket_number || "N/A"}</span>
        
            <strong style="text-align:left;">State:</strong>
            <span>${item.state || "N/A"}</span>
        
            <strong style="text-align:left;">Opened By:</strong>
            <span>${item.opened_by || "N/A"}</span>
        
            <strong style="text-align:left;">Requested For:</strong>
            <span>${item.requested_for || "N/A"}</span>
        
            <strong style="text-align:left;">Opened At:</strong>
            <span>${item.opened_at || "N/A"}</span>
        
            <strong style="text-align:left;">Assignment Group:</strong>
            <span>${item.assignment_group || "N/A"}</span>
        
            <strong style="text-align:left;">Record URL:</strong>
            <span>${item.record_url 
                  ? `<a href="${item.record_url}" target="_blank" style="color:#2563eb;text-decoration:underline;">View</a>` 
                  : "N/A"}</span>
        
            <strong style="text-align:left;">Comments:</strong>
            <span style="white-space:pre-wrap;">${recentComment}</span>
        
          </div>
        </div>  
        `;
      });

    }

    // ---------------- APPHUB TOOL (FINAL FIXED) ----------------
    else if (data.tool_name === "AppHub" && typeof data.results === "object") {
    
      const sys = data.results.system_information || {};
    
      // ? FULL outage objects (already working)
      const outages = Array.isArray(data.results.outage_information)
        ? data.results.outage_information
        : [];
    
      // ? FIX: derive outage IDs from outages
      const outageIds = outages.map(o => o.id).filter(Boolean);
    
      // ? FIX: define outageIdTable (this was missing)
      const outageIdTable = buildCompactTable(
        ["Outage ID"],
        outageIds.length ? outageIds.map(id => [id]) : []
      );
    
      /* ================= SYSTEM INFORMATION ================= */
      const systemTable = buildCompactTable(
        ["Field", "Value"],
        [
          ["System Id" , fmt(sys.system_id)],
          ["System Name", fmt(sys.system_name)],
          ["State", fmt(sys.state)],
          ["SPA", fmt(data.results.business_unit)],
          ["Service Areas", (sys.service_area_names || []).join(", ") || "N/A"]
        ]
      );
    
      /* ================= SUB-CITY INFORMATION ================= */
      const subCityTable = buildCompactTable(
        ["Sub-City"],
        Array.isArray(sys.subcity_information)
          ? sys.subcity_information.map(s => [fmt(s.serviceAreaName)])
          : []
      );
    
      /* ================= OFFICE HOURS ================= */
      const officeHoursTable = buildCompactTable(
        ["Day", "Open", "LunchStart", "LunchEnd", "Close"],
        formatOfficeHoursRows(sys.office_hours)
      );
    
     
       /* ================= DROP BURY / WALL FISH (? FIXED) ================= */
      
        
        let wallFishArray = [];
        
        if (Array.isArray(sys.wall_fish_information)) {
          wallFishArray = sys.wall_fish_information;
        }
        else if (
          sys.wall_fish_information &&
          typeof sys.wall_fish_information === "object"
        ) {
          // ? Convert object-with-index-keys into array
          wallFishArray = Object.values(sys.wall_fish_information);
        }

      
        const wallFishTable = buildCompactTable(
          ["Company Name", "Type", "Contact / Details"],
          wallFishArray.length
            ? wallFishArray.map(item => [
                fmt(item.companyName),
                fmt(item.companyType),
                fmt(item.companyContact)
              ])
            : [["N/A", "N/A", "N/A"]]
        );

    
      /* ================= RETURN BOX ================= */
      const returnBoxTable = buildCompactTable(
        ["Equipment Return Box Address"],
        (sys.equipment_return_box_addresses || []).map(addr => [addr])
      );
    
      /* ================= OFFICE ALERTS ================= */
      
        
        const alertsTable = buildCompactTable(
          ["Alert Message", "Start Date", "End Date"],
          Array.isArray(sys.office_alerts)
            ? sys.office_alerts.map(a => [
                fmt(a.alertMessage),
                to12HourDateTime(a.effectiveStart),
                to12HourDateTime(a.effectiveEnd),
              ])
            : []
        );

    
      /* ================= FINAL OUTPUT ================= */
      outputHTML = `
        <div>
          <div class="compact-section-title">System Information</div>
          ${systemTable}
    
          <div class="compact-section-title">Sub-City Information</div>
          ${subCityTable}
    
          <div class="compact-section-title">Office Hours</div>
          ${officeHoursTable}
    
          <div class="compact-section-title">Wall Fish / Drop Bury</div>
          ${wallFishTable}
    
          <div class="compact-section-title">Equipment Return Box Addresses</div>
          ${returnBoxTable}
    
          <div class="compact-section-title">Office Alerts</div>
          ${alertsTable}
    
          <div class="compact-section-title">Outage IDs</div>
          ${outageIdTable}
        </div>
      `;
    }
    // ---------------- TCC MODEM SIGNAL LEVELS ----------------
      else if (
        data.tool_name === "Modem Signal levels" &&
        typeof data.results === "object"
      ) {
        const billing = data.results.billingInfo || {};
        const modem = data.results.modemSignalLevels || {};
      
        const billingTable = buildCompactTable(
          ["Field", "Value"],
          [
            ["Business Unit", fmt(billing.business_unit)],
            ["Current Balance", fmt(billing.current_balance)],
            ["Last Payment Amount", fmt(billing.last_payment_amount)],
            ["Last Payment Date", to12HourDateTime(billing.last_payment_date)],
            ["Payment Due Amount", fmt(billing.payment_due_amount)],
            ["Payment Due Date", to12HourDateTime(billing.payment_due_date)],
            ["Past Due Amount", fmt(billing.past_due_amount)]
          ]
        );
      
        const modemTable = buildCompactTable(
          ["Metric", "Value"],
          [
            ["Account", fmt(modem.account)],
            ["Homes Passed ID", fmt(modem.homesPassedId)],
            ["Latitude", fmt(modem.latitude)],
            ["Longitude", fmt(modem.longitude)],
            ["Modem MAC", fmt(modem.modemMAC)],
            ["Modem State", fmt(modem.modemState)],
            ["US RX", fmt(modem.usRX)],
            ["US TX", fmt(modem.usTX)],
            ["US SNR", fmt(modem.usSNR)],
            ["DS RX", fmt(modem.dsRX)],
            ["DS SNR", fmt(modem.dsSNR)],
            ["Customer Status", fmt(modem.customerStatus)],
            ["Icon", fmt(modem.icon)]
          ]
        );
      
        outputHTML = `
          <div>
            <div class="compact-section-title">Modem Signal Levels</div>
            ${modemTable}
            
            <div class="compact-section-title">Billing Information</div>
            ${billingTable}  
          </div>
        `;
      }
      // ---------------- TCC EQUIPMENT DETAILS ----------------
      else if (
        data.tool_name === "Equipment Details" &&
        typeof data.results === "object"
      ) {
        const modem = data.results.modemDetails || {};
        const equipment = Array.isArray(data.results.equipmentDetails)
          ? data.results.equipmentDetails
          : [];
      
        // Modem summary table
        const modemTable = buildCompactTable(
          ["Field", "Value"],
          [
            ["Account", fmt(data.results.account)],
            ["Modem MAC", fmt(modem.modemMAC)],
            ["Modem State", fmt(modem.modemState)]
          ]
        );
      
        // Equipment table
        const equipmentTable = buildCompactTable(
          [
            "Description",
            "Model",
            "Serial Number",
            "Manufacturer",
            "Ownership",
            "Equipment Type"
          ],
          equipment.length
            ? equipment.map(e => [
                fmt(e.description),
                fmt(e.model),
                fmt(e.serial_number),
                fmt(e.manufacturer),
                fmt(e.customer_owned),
                fmt(e.equipment_type)
              ])
            : []
        );
      
        outputHTML = `
          <div>
            <div class="compact-section-title">Modem Details</div>
            ${modemTable}
      
            <div class="compact-section-title">Equipment Details</div>
            ${equipmentTable}
          </div>
        `;
      }   
    
    // ---------------- STRING RESPONSE ----------------
    else if (typeof data.results === "string") {

      outputHTML = `
      <div style="padding:6px;">
        ${data.results}
      </div>
      `;

    }

    // ---------------- FALLBACK ----------------
    else {

      outputHTML = `
      <pre style="font-size:12px;">
${JSON.stringify(data.results, null, 2)}
      </pre>
      `;

    }

    tmpl.querySelector(".tool-results").innerHTML = outputHTML;

    chatWindow.appendChild(tmpl);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    lucide.createIcons();

  })
  .catch(error => {
    loadingDiv.remove();
    addMessage("Assistant", `Error running tool: ${error.message}`);
    console.error(error);

  });

}
newChatBtn.onclick = startNewChat;
sendBtn.onclick = sendMessage;
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-grow textarea
msgInput.addEventListener("input", () => {
  msgInput.style.height = "auto";
  msgInput.style.height = msgInput.scrollHeight + "px";
});

// Start with one chat session open
startNewChat();

const select = document.getElementById("company-select");

select.addEventListener("change", function () {
  if (this.value) {
    this.style.backgroundColor = "#F5EDF5"; // apply your color
  } else {
    this.style.backgroundColor = "white"; // default
  }
});

function sendFeedback(score, reason = null, thankYouElem = null) {
  fetch('/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      responseId: activeSession,
      feedbackScore: score,
      reason: reason
    }),
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === "ok") {
        // show per-message thank-you if present
        if (thankYouElem) {
          thankYouElem.classList.remove("hidden");
          setTimeout(() => thankYouElem.classList.add("hidden"), 3000);
        }
        // show global thank-you banner (optional)
        const globalThankYou = document.getElementById("thank-you");
        if (globalThankYou) {
          globalThankYou.style.display = "block";
        }
      }
    });
}

// Close button for the global thank-you banner
document.getElementById("closeThankYou")?.addEventListener("click", () => {
  document.getElementById("thank-you").style.display = "none";
});

function ensureIconsVisible() {
  const icons = document.querySelectorAll('.thumbs-up, .thumbs-down, .copy-btn');
  icons.forEach(icon => {
    if (!icon.textContent.trim()) {
      if (icon.classList.contains('thumbs-up')) icon.textContent = 'ðŸ‘';
      else if (icon.classList.contains('thumbs-down')) icon.textContent = 'ðŸ‘Ž';
      else if (icon.classList.contains('copy-btn')) icon.textContent = 'ðŸ“‹';
    }
  });
}

function sendToolFeedback(toolName, accountNumber, score, reason = null, thankYouElem = null) {
  fetch('/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      responseId: activeSession,
      feedbackScore: score,
      reason: reason,
      tool_name: toolName,
      account_number: accountNumber
    }),
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === "ok") {
        if (thankYouElem) {
          thankYouElem.classList.remove("hidden");
          setTimeout(() => thankYouElem.classList.add("hidden"), 3000);
        }
      }
    });
}
