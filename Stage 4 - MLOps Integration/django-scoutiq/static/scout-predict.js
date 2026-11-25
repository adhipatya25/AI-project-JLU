/* ScoutIQ Django - predict page.
 * Ported line-for-line from the FastAPI frontend (fastapi-service/frontend/script.js).
 * Only difference: requests go to Django's /ui/... endpoints (same-origin + CSRF);
 * Django asks the FastAPI model service for the rating and stores it in the database.
 */
const API_URL = "/ui/predict/";
const EXTRACT_URL = "/ui/extract-report/";
const PREDICT_PDF_URL = "/ui/predict-from-report/";
const PREDICT_CSV_URL = "/ui/predict-from-csv/";
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').content;
const SERVER_DOWN = "Cannot reach the Django server. Is runserver still running?";

function postToDjango(url, body, isJson = false) {
  const headers = { "X-CSRFToken": CSRF_TOKEN, Accept: "application/json" };
  if (isJson) headers["Content-Type"] = "application/json";
  return fetch(url, { method: "POST", headers, body: isJson ? JSON.stringify(body) : body, credentials: "same-origin" });
}

const form = document.getElementById("prediction-form");
const positionSelect = document.getElementById("position");
const subPositionSelect = document.getElementById("sub_position");
const sampleProfileSelect = document.getElementById("sample-profile");
const loadSampleButton = document.getElementById("load-sample-button");
const sampleStatus = document.getElementById("sample-status");
const predictButton = document.getElementById("predict-button");
const predictButtonLabel = document.getElementById("predict-button-label");

// --- PDF / CSV upload elements (run with app-2.py) ---
const reportFile = document.getElementById("report-file");
const extractButton = document.getElementById("extract-button");
const predictPdfButton = document.getElementById("predict-pdf-button");
const uploadStatus = document.getElementById("upload-status");
const extractedGrid = document.getElementById("extracted-grid");
const csvFile = document.getElementById("csv-file");
const csvButton = document.getElementById("csv-button");
const csvStatus = document.getElementById("csv-status");
const csvResults = document.getElementById("csv-results");

// Single source of truth for "completely filled": the same rules the
// prediction itself enforces (see collectPayload), checked without throwing.
function formIsComplete() {
  for (const name of numericFields) {
    const raw = form.elements[name].value.trim();
    if (raw === "") return false;
    const number = Number(raw);
    if (!Number.isFinite(number) || number < 0) return false;
    if (name !== "total_minutes" && !Number.isInteger(number)) return false;
  }
  if (!form.checkValidity()) return false;
  const selectedPosition = positionSelect.value;
  if (!subPositionsByPosition[selectedPosition]?.includes(subPositionSelect.value)) return false;
  return ["position", "sub_position", "foot", "competition_code", "confederation"].every(
    (name) => form.elements[name].value !== ""
  );
}

function updatePredictButtonLabel(isPredicting = false) {
  if (isPredicting) {
    predictButtonLabel.textContent = "Predicting…";
    return;
  }
  predictButtonLabel.textContent = formIsComplete()
    ? "Predict Player Potential"
    : "Generate player prediction";
}

const validationMessage = document.getElementById("validation-message");
const resultCard = document.getElementById("result-card");
const resultBadge = document.getElementById("result-badge");
const resultRating = document.getElementById("result-rating");
const resultDescription = document.getElementById("result-description");
const resultSaved = document.getElementById("result-saved");

const numericFields = [
  "height_in_cm",
  "international_caps",
  "market_value_in_eur",
  "matches_played",
  "total_minutes",
  "total_goals",
  "total_assists",
  "yellow_cards",
  "red_cards"
];

const allFields = [...numericFields, "position", "sub_position", "foot", "competition_code", "confederation"];

const subPositionsByPosition = {
  Attack: ["Centre-Forward", "Left Winger", "Right Winger", "Second Striker"],
  Midfield: ["Attacking Midfield", "Central Midfield", "Defensive Midfield", "Left Midfield", "Right Midfield"],
  Defender: ["Centre-Back", "Left-Back", "Right-Back"],
  Goalkeeper: ["Goalkeeper"]
};

// These example profiles are based on complete rows from the project's dataset.
// They are demo inputs, not promises about what the model will predict.
const sampleProfiles = {
  outperforming: {
    height_in_cm: 187,
    international_caps: 6,
    market_value_in_eur: 500000,
    matches_played: 197,
    total_minutes: 15223,
    total_goals: 7,
    total_assists: 4,
    yellow_cards: 38,
    red_cards: 2,
    position: "Defender",
    sub_position: "Centre-Back",
    foot: "right",
    competition_code: "liga-portugal",
    confederation: "europa"
  },
  average: {
    height_in_cm: 191,
    international_caps: 6,
    market_value_in_eur: 900000,
    matches_played: 35,
    total_minutes: 1953,
    total_goals: 0,
    total_assists: 2,
    yellow_cards: 2,
    red_cards: 0,
    position: "Defender",
    sub_position: "Centre-Back",
    foot: "right",
    competition_code: "superliga",
    confederation: "europa"
  },
  underperforming: {
    height_in_cm: 191,
    international_caps: 4,
    market_value_in_eur: 25000,
    matches_played: 1,
    total_minutes: 90,
    total_goals: 0,
    total_assists: 0,
    yellow_cards: 1,
    red_cards: 0,
    position: "Defender",
    sub_position: "Centre-Back",
    foot: "right",
    competition_code: "serie-a",
    confederation: "europa"
  }
};

function updateSubPositions(preferredValue = "") {
  const position = positionSelect.value;
  const options = subPositionsByPosition[position] || [];

  subPositionSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = position ? "Select sub-position" : "Select a position first";
  placeholder.disabled = true;
  placeholder.selected = true;
  subPositionSelect.appendChild(placeholder);
  subPositionSelect.disabled = options.length === 0;

  options.forEach((subPosition) => {
    const option = document.createElement("option");
    option.value = subPosition;
    option.textContent = subPosition;
    subPositionSelect.appendChild(option);
  });

  if (options.includes(preferredValue)) {
    subPositionSelect.value = preferredValue;
  }
}

const RESULT_STATES = ["rating-outperforming", "rating-average", "rating-underperforming", "rating-error"];

function clearResultState() {
  // Never touch the base "panel result-card tilt" classes — replacing
  // className outright strips the card's background/border styling.
  resultCard.classList.remove(...RESULT_STATES);
  showSaved(null);
}

// Django stores every complete prediction: show where it went.
function showSaved(data) {
  resultSaved.replaceChildren();
  resultSaved.hidden = !(data && data.player_url);
  if (resultSaved.hidden) return;
  resultSaved.append(`Saved to history as Prediction #${data.prediction_id}. `);
  const link = document.createElement("a");
  link.href = data.player_url;
  link.textContent = "Open player record →";
  resultSaved.appendChild(link);
}

function resetResult() {
  clearResultState();
  resultBadge.textContent = "Awaiting input";
  resultRating.textContent = "Your prediction will appear here.";
  resultDescription.textContent = "Enter player information and select “Predict Player Potential” to see the model's estimate.";
}

function showPageError(message) {
  validationMessage.textContent = message;
  validationMessage.classList.add("is-visible");
}

function clearPageError() {
  validationMessage.textContent = "";
  validationMessage.classList.remove("is-visible");
}

// Single-source rule helpers: only the input path actually used stays visible.
function clearPdfUI() {
  if (reportFile) reportFile.value = "";
  setUploadStatus("");
  if (extractedGrid) {
    extractedGrid.hidden = true;
    extractedGrid.replaceChildren();
  }
}

function clearCsvUI() {
  if (csvFile) csvFile.value = "";
  setCsvStatus("");
  if (csvResults) {
    csvResults.hidden = true;
    csvResults.replaceChildren();
  }
}

function clearSampleUI() {
  sampleStatus.textContent = "";
  sampleProfileSelect.value = "";
}

function loadSelectedSample() {
  const profileName = sampleProfileSelect.value;
  const profile = sampleProfiles[profileName];

  sampleStatus.classList.remove("is-error");
  if (!profile) {
    sampleStatus.textContent = "Choose a sample profile first.";
    sampleStatus.classList.add("is-error");
    return;
  }

  fillFormFromObject(profile);

  clearPageError();
  resetResult();
  clearPdfUI();
  clearCsvUI();
  updatePredictButtonLabel();
  updatePlayerSnapshot();
  sampleStatus.textContent = `${capitalize(profileName)} example loaded. Click “Predict Player Potential” to run the model.`;
}

function fillFormFromObject(obj) {
  numericFields.forEach((name) => {
    if (obj[name] !== null && obj[name] !== undefined && obj[name] !== "") {
      form.elements[name].value = obj[name];
    }
  });
  if (obj.position) {
    positionSelect.value = obj.position;
    updateSubPositions(obj.sub_position || "");
  }
  ["foot", "competition_code", "confederation"].forEach((name) => {
    if (obj[name]) {
      try {
        form.elements[name].value = obj[name];
      } catch { /* unknown option value: leave for user */ }
    }
  });
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function getRatingExplanation(rating) {
  const explanations = {
    Outperforming: "The model places this player in the Outperforming future-potential category based on the supplied statistics.",
    Average: "The model places this player in the Average future-potential category based on the supplied statistics.",
    Underperforming: "The model places this player in the Underperforming future-potential category based on the supplied statistics."
  };
  return explanations[rating] || "The model returned a rating, but no explanation is available for that label.";
}

function displayPrediction(rating, extra = "") {
  clearResultState();
  resultBadge.textContent = "Model prediction";
  resultRating.textContent = rating;
  resultDescription.textContent = getRatingExplanation(rating) + (extra ? ` ${extra}` : "");

  if (rating === "Outperforming") {
    resultCard.classList.add("rating-outperforming");
  } else if (rating === "Average") {
    resultCard.classList.add("rating-average");
  } else if (rating === "Underperforming") {
    resultCard.classList.add("rating-underperforming");
  }
}

function collectPayload() {
  const payload = {};
  numericFields.forEach((name) => {
    const element = form.elements[name];
    const value = element.value.trim();
    if (value === "") {
      throw new Error(`Please enter a value for ${element.labels[0].textContent}.`);
    }
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) {
      throw new Error(`${element.labels[0].textContent} must be a valid non-negative number.`);
    }
    if (name !== "total_minutes" && !Number.isInteger(number)) {
      throw new Error(`${element.labels[0].textContent} must be a whole number.`);
    }
    payload[name] = number;
  });

  if (!form.checkValidity()) {
    form.reportValidity();
    throw new Error("Please complete all fields with valid values before predicting.");
  }

  const selectedPosition = positionSelect.value;
  if (!subPositionsByPosition[selectedPosition]?.includes(subPositionSelect.value)) {
    throw new Error("Choose a sub-position that matches the selected position.");
  }

  ["position", "sub_position", "foot", "competition_code", "confederation"].forEach((name) => {
    payload[name] = form.elements[name].value;
  });
  payload.name = form.elements.name.value.trim();

  return payload;
}

// --- PDF upload flow ---
function setUploadStatus(message, isError = false) {
  uploadStatus.textContent = message;
  uploadStatus.classList.toggle("is-error", isError);
}

function renderExtracted(extracted, missing) {
  extractedGrid.hidden = false;
  extractedGrid.replaceChildren();
  allFields.forEach((name) => {
    const chip = document.createElement("div");
    chip.className = "extract-chip" + (missing.includes(name) ? " is-missing" : " is-found");
    const v = extracted[name];
    chip.innerHTML = `<span>${name.replaceAll("_", " ")}</span><strong>${v === null || v === undefined ? "missing — fill manually" : v}</strong>`;
    extractedGrid.appendChild(chip);
  });
}

function getSelectedPdf() {
  const f = reportFile.files && reportFile.files[0];
  if (!f) {
    setUploadStatus("Choose a PDF report first.", true);
    return null;
  }
  if (!/pdf$/i.test(f.type) && !/\.pdf$/i.test(f.name)) {
    setUploadStatus("That file is not a PDF. Please choose a .pdf report.", true);
    return null;
  }
  if (f.size > 10 * 1024 * 1024) {
    setUploadStatus("PDF too large (max 10 MB).", true);
    return null;
  }
  return f;
}

async function handleExtract() {
  const pdf = getSelectedPdf();
  if (!pdf) return;
  setUploadStatus("Extracting fields from PDF…");
  extractButton.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", pdf, pdf.name);
    const res = await postToDjango(EXTRACT_URL, fd);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Server returned HTTP ${res.status}.`);
    fillFormFromObject(data.extracted || {});
    clearPageError();
    resetResult();
    clearSampleUI();
    clearCsvUI();
    updatePredictButtonLabel();
    updatePlayerSnapshot();
    renderExtracted(data.extracted || {}, data.missing || []);
    const nMissing = (data.missing || []).length;
    setUploadStatus(
      nMissing === 0
        ? `Extracted all 14 fields from ${pdf.name}. Verify, then predict.`
        : `Extracted from ${pdf.name}: ${14 - nMissing}/14 found. Missing: ${(data.missing || []).join(", ")}. Highlighted below — fill manually, then predict.`
    );
  } catch (err) {
    setUploadStatus(
      err.message.includes("Failed to fetch")
        ? SERVER_DOWN
        : err.message,
      true
    );
  } finally {
    extractButton.disabled = false;
  }
}

async function handlePredictPdf() {
  const pdf = getSelectedPdf();
  if (!pdf) return;
  setUploadStatus("Predicting directly from PDF…");
  resultBadge.textContent = "Working";
  resultRating.textContent = "Generating prediction…";
  resultDescription.textContent = "The model is processing the uploaded report.";
  predictPdfButton.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", pdf, pdf.name);
    const res = await postToDjango(PREDICT_PDF_URL, fd);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Server returned HTTP ${res.status}.`);
    // Also fill the form so stakeholders see what was used
    fillFormFromObject(data.extracted || {});
    clearSampleUI();
    clearCsvUI();
    updatePredictButtonLabel();
    updatePlayerSnapshot();
    renderExtracted(data.extracted || {}, data.missing_fields_filled_by_model_median || []);
    const missing = data.missing_fields_filled_by_model_median || [];
    displayPrediction(
      data.predicted_future_potential_rating,
      missing.length ? `(PDF partial: ${missing.join(", ")} filled with training medians — verify before trusting.)` : "(all fields read from PDF.)"
    );
    showSaved(data);
    setUploadStatus(`Predicted from ${pdf.name}. ${data.warning || ""}`);
  } catch (err) {
    clearResultState();
    resultCard.classList.add("rating-error");
    resultBadge.textContent = "Prediction failed";
    resultRating.textContent = "Unable to generate prediction";
    resultDescription.textContent = err.message.includes("Failed to fetch")
      ? SERVER_DOWN
      : err.message;
    setUploadStatus(err.message, true);
  } finally {
    predictPdfButton.disabled = false;
  }
}

// --- CSV batch flow ---
function setCsvStatus(message, isError = false) {
  csvStatus.textContent = message;
  csvStatus.classList.toggle("is-error", isError);
}

function renderCsvResults(results) {
  csvResults.hidden = false;
  csvResults.replaceChildren();
  const table = document.createElement("table");
  table.className = "csv-table";
  table.innerHTML = "<thead><tr><th>ROW</th><th>PLAYER</th><th>PREDICTED RATING</th></tr></thead>";
  const body = document.createElement("tbody");
  results.forEach((r) => {
    const tr = document.createElement("tr");
    const rowCell = document.createElement("td");
    rowCell.textContent = `#${r.row}`;
    const nameCell = document.createElement("td");
    if (r.ok) {
      const link = document.createElement("a");
      link.href = r.player_url;
      link.textContent = r.name;
      nameCell.appendChild(link);
    } else {
      nameCell.textContent = r.name;
    }
    const ratingCell = document.createElement("td");
    if (r.ok) {
      const pill = document.createElement("span");
      pill.className = `csv-pill csv-${r.rating}`;
      pill.textContent = r.rating;
      ratingCell.appendChild(pill);
    } else {
      ratingCell.className = "csv-row-error";
      ratingCell.textContent = r.error;
    }
    tr.append(rowCell, nameCell, ratingCell);
    body.appendChild(tr);
  });
  table.appendChild(body);
  csvResults.appendChild(table);
}

async function handlePredictCsv() {
  const f = csvFile.files && csvFile.files[0];
  if (!f) {
    setCsvStatus("Choose a CSV file built on the template first.", true);
    return;
  }
  if (!/\.csv$/i.test(f.name)) {
    setCsvStatus("That file is not a .csv file.", true);
    return;
  }
  if (f.size > 5 * 1024 * 1024) {
    setCsvStatus("CSV too large (max 5 MB).", true);
    return;
  }
  setCsvStatus(`Predicting ${f.name}…`);
  csvButton.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", f, f.name);
    const res = await postToDjango(PREDICT_CSV_URL, fd);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Server returned HTTP ${res.status}.`);
    clearSampleUI();
    clearPdfUI();
    renderCsvResults(data.results || []);
    const stored = (data.results || []).filter((r) => r.ok).length;
    setCsvStatus(`Predicted ${data.count} player${data.count === 1 ? "" : "s"} from ${f.name}: ${stored} stored in history. Exact template columns — no imputation.`);
  } catch (err) {
    setCsvStatus(
      err.message.includes("Failed to fetch")
        ? SERVER_DOWN
        : err.message,
      true
    );
  } finally {
    csvButton.disabled = false;
  }
}

function handleManualEdit() {
  clearPageError();
  // The form no longer equals the loaded sample, so that claim is dropped.
  // PDF/CSV reports stay: they describe uploaded files, still the reference
  // for fields the user completes by hand.
  sampleStatus.textContent = "";
  if (resultBadge.textContent !== "Awaiting input") {
    resetResult();
  }
  updatePredictButtonLabel();
}

positionSelect.addEventListener("change", () => {
  updateSubPositions();
  resetResult();
  sampleStatus.textContent = "";
  updatePredictButtonLabel();
});

loadSampleButton.addEventListener("click", loadSelectedSample);
if (extractButton) extractButton.addEventListener("click", handleExtract);
if (predictPdfButton) predictPdfButton.addEventListener("click", handlePredictPdf);
if (csvButton) csvButton.addEventListener("click", handlePredictCsv);

form.addEventListener("input", () => {
  handleManualEdit();
  updatePlayerSnapshot();
});

form.addEventListener("change", () => {
  handleManualEdit();
  updatePlayerSnapshot();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearPageError();
  sampleStatus.textContent = "";
  updatePlayerSnapshot();

  let payload;
  try {
    if (!form.checkValidity()) {
      form.reportValidity();
      throw new Error("Please complete all fields with valid values before predicting.");
    }
    payload = collectPayload();
  } catch (error) {
    showPageError(error.message);
    return;
  }

  predictButton.disabled = true;
  updatePredictButtonLabel(true);
  resultBadge.textContent = "Working";
  resultRating.textContent = "Generating prediction…";
  resultDescription.textContent = "The model is processing the player statistics.";

  try {
    const response = await postToDjango(API_URL, payload, true);

    let responseData;
    try {
      responseData = await response.json();
    } catch {
      throw new Error("The API returned an unreadable response.");
    }

    if (!response.ok) {
      throw new Error(responseData.detail || `The API returned HTTP ${response.status}.`);
    }

    const rating = responseData.predicted_future_potential_rating;
    if (typeof rating !== "string" || !rating.trim()) {
      throw new Error("The API response did not contain a predicted rating.");
    }

    displayPrediction(rating);
    showSaved(responseData);
  } catch (error) {
    clearResultState();
    resultCard.classList.add("rating-error");
    resultBadge.textContent = "Prediction failed";
    resultRating.textContent = "Unable to generate prediction";
    resultDescription.textContent = error.message.includes("Failed to fetch")
      ? SERVER_DOWN
      : error.message;
  } finally {
    predictButton.disabled = false;
    updatePredictButtonLabel();
  }
});

// Start with empty form values and a dependent sub-position dropdown.
updateSubPositions();

// Keep the player snapshot in sync with the values entered in the form.
const snapshotFields = {
  height_in_cm: "snapshot-height",
  market_value_in_eur: "snapshot-value",
  matches_played: "snapshot-matches",
  total_goals: "snapshot-goals"
};

function updatePlayerSnapshot() {
  Object.entries(snapshotFields).forEach(([fieldName, elementId]) => {
    const input = form.elements[fieldName];
    const target = document.getElementById(elementId);
    const rawValue = input.value.trim();
    if (!rawValue) {
      target.textContent = "—";
    } else if (fieldName === "market_value_in_eur") {
      const amount = Number(rawValue);
      target.textContent = Number.isFinite(amount)
        ? amount.toLocaleString("en-IN", { maximumFractionDigits: 0 })
        : "—";
    } else {
      target.textContent = Number(rawValue).toLocaleString("en-IN", { maximumFractionDigits: 1 });
    }
  });

  const position = positionSelect.value;
  const subPosition = subPositionSelect.value;
  document.getElementById("snapshot-position").textContent = position
    ? `${position}${subPosition ? ` · ${subPosition}` : ""}`
    : "Position not selected";
}

form.addEventListener("reset", () => {
  window.setTimeout(() => {
    updateSubPositions();
    updatePlayerSnapshot();
    clearPageError();
    clearSampleUI();
    clearPdfUI();
    clearCsvUI();
    updatePredictButtonLabel();
    resetResult();
  }, 0);
});

updatePlayerSnapshot();
updatePredictButtonLabel();

