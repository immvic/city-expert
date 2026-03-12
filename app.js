const root = document.body;
const app = document.querySelector(".app");
const themeToggle = document.getElementById("themeToggle");
const planForm = document.getElementById("planForm");
const loadPlacesBtn = document.getElementById("loadPlaces");
const weatherOutput = document.getElementById("weatherOutput");
const placesOutput = document.getElementById("placesOutput");
const advisorOutput = document.getElementById("advisorOutput");

const setTheme = (theme) => {
  root.setAttribute("data-theme", theme);
  document.documentElement.setAttribute("data-theme", theme);
  if (app) {
    app.setAttribute("data-theme", theme);
  }
};

const savedTheme = localStorage.getItem("caa-theme");
if (savedTheme) {
  setTheme(savedTheme);
}

themeToggle.addEventListener("click", () => {
  const current = root.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  setTheme(next);
  localStorage.setItem("caa-theme", next);
});

const API_BASE = "http://127.0.0.1:8000";

const renderError = (el, message) => {
  el.innerHTML = `<p class="placeholder">${message}</p>`;
};

const renderWeather = (payload) => {
  const weather = payload.weather || {};
  const temp =
    weather.temperature_c ??
    weather.temp_max_c ??
    weather.temp_min_c ??
    "N/A";
  const time = weather.time || weather.date || "-";
  weatherOutput.innerHTML = `
    <div>
      <strong>${payload.city}</strong>
      <p>Temperature: ${temp}°C</p>
      <p>Updated: ${time}</p>
    </div>
  `;
};

const renderPlaces = (data) => {
  const list = data.places
    .slice(0, 6)
    .map(
      (place) => `
      <div>
        <strong>${place.name}${place.category ? ` - ${place.category}` : ""}</strong>
        <p>${place.address || ""}</p>
      </div>
    `
    )
    .join("");
  placesOutput.innerHTML = list || `<p class="placeholder">No places found</p>`;
};

const renderAdvisor = (data) => {
  advisorOutput.innerHTML = `
    <div>
      <p><strong>Recommendation</strong></p>
      <p>${data.recommendation}</p>
      <p><strong>Wear</strong></p>
      <p>${data.wear}</p>
    </div>
  `;
};

const requestJson = async (url, options) => {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await response.text();
    throw new Error(text || "Unexpected response.");
  }
  const data = await response.json();
  if (data.status !== "ok") {
    throw new Error(data.data.message || "Request failed");
  }
  return data.data;
};

const fetchWeather = async (city) => {
  return requestJson(`${API_BASE}/weather?city=${encodeURIComponent(city)}`);
};

const fetchPlaces = async (activity, city) => {
  return requestJson(
    `${API_BASE}/places?activity=${encodeURIComponent(activity)}&city=${encodeURIComponent(city)}`
  );
};

const fetchAdvisor = async (activity, city, date) => {
  const formData = new FormData();
  formData.append("activity_form", activity);
  formData.append("city_form", city);
  if (date) {
    formData.append("date_form", date);
  }

  return requestJson(`${API_BASE}/advisor`, {
    method: "POST",
    body: formData,
  });
};

planForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const activity = planForm.activity.value.trim();
  const city = planForm.city.value.trim();
  const date = planForm.date.value.trim();

  if (!activity || !city) {
    renderError(advisorOutput, "Please enter activity and city.");
    return;
  }

  try {
    weatherOutput.innerHTML = `<p class="placeholder">Loading weather...</p>`;
    placesOutput.innerHTML = `<p class="placeholder">Loading places...</p>`;
    advisorOutput.innerHTML = `<p class="placeholder">Thinking...</p>`;

    const advisor = await fetchAdvisor(activity, city, date);
    renderWeather({ city, weather: advisor.weather });
    renderPlaces({ places: advisor.places });
    renderAdvisor(advisor);
  } catch (error) {
    const message = error.message || "Something went wrong.";
    renderError(advisorOutput, message);
    renderError(weatherOutput, message);
    renderError(placesOutput, message);
  }
});

loadPlacesBtn.addEventListener("click", async () => {
  const activity = planForm.activity.value.trim();
  const city = planForm.city.value.trim();

  if (!activity || !city) {
    renderError(placesOutput, "Please enter activity and city.");
    return;
  }

  try {
    placesOutput.innerHTML = `<p class="placeholder">Loading places...</p>`;
    const places = await fetchPlaces(activity, city);
    renderPlaces(places);
  } catch (error) {
    renderError(placesOutput, error.message || "Something went wrong.");
  }
});
