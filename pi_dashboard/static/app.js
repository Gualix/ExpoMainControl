
const socket = io();

const elTemps = document.getElementById("temps");
const elAvg = document.getElementById("avg");
const elTS = document.getElementById("ts");
const elBomba = document.getElementById("gpio-bomba");
const elReleV = document.getElementById("gpio-relev");
const elTrig = document.getElementById("gpio-trigger");

function setStatus(el, val) {
  if (val === 1) {
    el.textContent = "ON";
    el.classList.add("on");
    el.classList.remove("off");
  } else if (val === 0) {
    el.textContent = "OFF";
    el.classList.add("off");
    el.classList.remove("on");
  } else {
    el.textContent = "--";
    el.classList.remove("on","off");
  }
}

// Chart.js setup
const ctx = document.getElementById("chart");
const datasetTemplate = alias => ({
  label: alias,
  data: [],
  borderWidth: 2,
  fill: false,
  tension: 0.2,
});
const chart = new Chart(ctx, {
  type: "line",
  data: {
    labels: [],
    datasets: SENSOR_ALIASES.map(datasetTemplate),
  },
  options: {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { title: { display: true, text: "Tiempo" } },
      y: { title: { display: true, text: "°C" } }
    }
  }
});

function pushSample(ts, temps) {
  chart.data.labels.push(ts);
  SENSOR_ALIASES.forEach((alias, i) => {
    const v = temps?.[alias] ?? null;
    chart.data.datasets[i].data.push(v);
  });
  // mantener ~10 minutos si INTERVALO_SEG ~2s => 300 puntos
  if (chart.data.labels.length > 300) {
    chart.data.labels.shift();
    chart.data.datasets.forEach(ds => ds.data.shift());
  }
  chart.update();
}

function renderTemps(temps) {
  elTemps.innerHTML = SENSOR_ALIASES.map(a => {
    const v = temps?.[a];
    return `<div><strong>${a}</strong>: ${v != null ? v.toFixed(3) + " °C" : "N/A"}</div>`;
  }).join("");
}

socket.on("telemetry", (msg) => {
  renderTemps(msg.temps);
  elAvg.textContent = msg.avg != null ? msg.avg.toFixed(3) + " °C" : "--";
  elTS.textContent = msg.ts ?? "--";
  pushSample(msg.ts ?? "", msg.temps);
  setStatus(elBomba, msg.gpio?.bomba);
  setStatus(elReleV, msg.gpio?.relay_v);
  setStatus(elTrig, msg.gpio?.trigger);
});

socket.on("telemetry_error", (msg) => {
  console.warn("Telemetry error:", msg);
});

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  });
  return r.json();
}

document.getElementById("bomba-on").onclick = async () => {
  await postJSON("/api/bomba", {action: "on"});
};
document.getElementById("bomba-off").onclick = async () => {
  await postJSON("/api/bomba", {action: "off"});
};
document.getElementById("relev-on").onclick = async () => {
  await postJSON("/api/relev", {action: "on"});
};
document.getElementById("relev-off").onclick = async () => {
  await postJSON("/api/relev", {action: "off"});
};
