const DATA = window.LEXICON_DATA || {
  entries: [],
  clusters: [],
  kanjiIndex: [],
  stats: { entries: 0, majors: {}, levels: {}, transitivity: {}, kanji: 0 },
};
const EXAMPLE_DATA = window.LEXICON_EXAMPLES || { meta: {}, entries: {} };
const EXAMPLES_BY_ENTRY = EXAMPLE_DATA.entries || {};
const HAN_VARIANT_MAP = buildHanVariantMap(window.HAN_VARIANT_GROUPS || "");
const HAN_RUN_COMBO_LIMIT = 32;
const APP_STORAGE_KEYS = {
  preferences: "lexicon.v1.preferences",
  progress: "lexicon.v1.progress",
};
const LEGACY_STORAGE_KEYS = {
  themeMode: "lexicon.themeMode",
  backgroundImage: "lexicon.backgroundImage",
  backgroundOpacity: "lexicon.backgroundOpacity",
  panelOpacity: "lexicon.panelOpacity",
  starred: "lexicon.starred",
  learned: "lexicon.learned",
};
const DEFAULT_PREFERENCES = {
  themeMode: "system",
  backgroundOpacity: 18,
  panelOpacity: 92,
  batchSize: 48,
  hideKana: false,
  hideGloss: false,
  termOnlySearch: false,
  indexTab: "category",
};
const INDEX_TABS = new Set(["category", "kanji", "saved", "settings"]);
const BATCH_SIZE_OPTIONS = new Set([24, 48, 96, 200]);
const JLPT_LEVEL_ORDER = ["N5", "N4", "N3", "N2", "N1"];
const APP_STORE = createBrowserLexiconStore();
const persistedPreferences = APP_STORE.loadPreferences();
const persistedProgress = APP_STORE.loadProgress();

const state = {
  query: "",
  major: "",
  cluster: "",
  levels: new Set(),
  jlptLevels: new Set(),
  transitivity: "",
  partGroup: "",
  kanji: "",
  kanjiReading: "",
  status: "",
  sort: "rank",
  manualSort: false,
  page: 1,
  batchSize: persistedPreferences.batchSize,
  hideKana: persistedPreferences.hideKana,
  hideGloss: persistedPreferences.hideGloss,
  shuffled: false,
  termOnlySearch: persistedPreferences.termOnlySearch,
  indexTab: persistedPreferences.indexTab,
  themeMode: persistedPreferences.themeMode,
  backgroundImage: "",
  backgroundName: "",
  backgroundOpacity: persistedPreferences.backgroundOpacity,
  panelOpacity: persistedPreferences.panelOpacity,
};

const storage = {
  starred: new Set(persistedProgress.starred),
  learned: new Set(persistedProgress.learned),
};

const TRANSITIVITY_SEQUENCE = ["", "自动词", "他动词", "自他両用"];

const els = {};
let preparedEntries = [];
let filteredEntries = [];
let shuffledIds = [];
let hasVerbCandidates = false;
let activeBackgroundObjectUrl = "";

document.addEventListener("DOMContentLoaded", () => {
  void bootApp();
});

async function bootApp() {
  bindElements();
  prepareData();
  applyAppearance();
  renderStaticIndexes();
  bindEvents();
  syncPreferenceControls();
  applyFilters();
  await restoreStoredBackground();
  void persistPreferences();
  persistStorage();
}

function bindElements() {
  [
    "datasetMeta",
    "searchInput",
    "termOnlySearchBtn",
    "levelFilter",
    "jlptFilter",
    "transitivityToggleBtn",
    "partFilter",
    "sortSelect",
    "categoryIndex",
    "kanjiIndex",
    "kanjiSearch",
    "kanjiDetail",
    "resultCount",
    "majorCount",
    "kanjiCount",
    "activeFilter",
    "prevPageBtn",
    "nextPageBtn",
    "pageLabel",
    "bottomPager",
    "bottomPrevPageBtn",
    "bottomNextPageBtn",
    "bottomPageLabel",
    "batchSizeSelect",
    "hideKanaBtn",
    "resetFiltersBtn",
    "hideGlossBtn",
    "entryGrid",
    "emptyState",
    "categoryPanel",
    "kanjiPanel",
    "savedPanel",
    "settingsPanel",
    "showStarredBtn",
    "showUnlearnedBtn",
    "showLearnedBtn",
    "clearStatusBtn",
    "backgroundUpload",
    "backgroundOpacity",
    "backgroundOpacityLabel",
    "panelOpacity",
    "panelOpacityLabel",
    "backgroundStatus",
    "clearBackgroundBtn",
    "exportDataBtn",
    "importDataBtn",
    "importDataInput",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function prepareData() {
  preparedEntries = DATA.entries.map((entry, index) => {
    const termWritingSearchText = buildTermWritingSearchText(entry);
    const termReadingSearchText = buildTermReadingSearchText(entry);
    const termSearchText = [termWritingSearchText, termReadingSearchText].join(" ");
    const exactTerms = buildExactSearchTerms(entry);

    return {
      ...entry,
      ...exactTerms,
      exactSearchScore: 0,
      sourceIndex: index,
      searchText: normalizeIndexedText(
        [
          entry.word,
          entry.reading,
          termSearchText,
          entry.major,
          entry.cluster,
          entry.subpos,
          entry.transitivity,
          entry.conjugation,
          entry.pair,
          ...(entry.kanji || []),
          ...(entry.writings || []),
          ...(entry.readings || []),
          ...(entry.tags || []),
          ...(entry.gloss || []),
          ...(entry.translation || []),
          entry.translationSource,
        ].join(" "),
      ),
      termSearchText,
      termWritingSearchText,
      termReadingSearchText,
    };
  });

  const total = DATA.stats?.entries || preparedEntries.length;
  const levels = DATA.stats?.levels || {};
  const levelText = Object.entries(levels)
    .map(([level, count]) => `${level}: ${formatNumber(count)}`)
    .join(" / ");
  els.datasetMeta.textContent = `${formatNumber(total)} 词条 · ${levelText}`;
}

function renderStaticIndexes() {
  renderCategoryIndex();
  renderKanjiIndex("");
}

function renderCategoryIndex() {
  const byMajor = new Map();
  for (const [major, count] of Object.entries(DATA.stats?.majors || {})) {
    byMajor.set(major, { count, clusters: [] });
  }
  for (const item of DATA.clusters || []) {
    if (!item.major || !item.cluster) continue;
    if (!byMajor.has(item.major)) byMajor.set(item.major, { count: 0, clusters: [] });
    byMajor.get(item.major).clusters.push(item);
  }

  const fragment = document.createDocumentFragment();
  for (const [major, info] of [...byMajor.entries()].sort((a, b) => b[1].count - a[1].count)) {
    const group = document.createElement("div");
    group.className = "category-group";

    const heading = document.createElement("button");
    heading.type = "button";
    heading.className = "category-heading";
    heading.dataset.major = major;
    heading.dataset.cluster = "";
    heading.innerHTML = `<span>${escapeHtml(major)}</span><span class="count-pill">${formatNumber(info.count)}</span>`;
    group.append(heading);

    const clusterList = document.createElement("div");
    clusterList.className = "cluster-list";
    for (const cluster of info.clusters.sort((a, b) => b.count - a.count)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cluster-button";
      button.dataset.major = major;
      button.dataset.cluster = cluster.cluster;
      button.innerHTML = `<span class="cluster-label">${escapeHtml(cluster.cluster)}</span><span class="count-pill">${formatNumber(cluster.count)}</span>`;
      clusterList.append(button);
    }
    group.append(clusterList);
    fragment.append(group);
  }

  els.categoryIndex.replaceChildren(fragment);
}

function renderKanjiIndex(query) {
  const normalizedQuery = normalizeSearchText(query);
  const visible = (DATA.kanjiIndex || [])
    .filter((item) => {
      if (!normalizedQuery) return true;
      return kanjiIndexItemMatches(item, normalizedQuery);
    })
    .slice(0, 360);

  const fragment = document.createDocumentFragment();
  for (const item of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kanji-button";
    button.dataset.kanji = item.kanji;
    button.title = `${item.kanji} · ${item.on || ""} ${item.kun || ""}`.trim();
    button.innerHTML = `<strong>${escapeHtml(item.kanji)}</strong><span>${formatNumber(item.count)}</span>`;
    fragment.append(button);
  }
  els.kanjiIndex.replaceChildren(fragment);
  updateActiveButtons();
}

function kanjiIndexItemMatches(item, normalizedQuery) {
  if (hasKanji(normalizedQuery)) {
    return normalizeIndexedText(item.kanji).includes(normalizedQuery);
  }
  if (hasKana(normalizedQuery)) {
    return kanjiReadingSearchText(item).includes(normalizedQuery);
  }
  return kanjiRomajiSearchText(item).includes(normalizedQuery);
}

function kanjiReadingSearchText(item) {
  return normalizeSearchText([item.on, item.kun].filter(Boolean).join(" "));
}

function kanjiRomajiSearchText(item) {
  const readings = splitKanjiReadings([item.on, item.kun].filter(Boolean).join("、")).map((reading) =>
    normalizeKanjiReading(reading),
  );
  return normalizeSearchText(
    readings
      .flatMap((reading) => romajiSearchVariants(kanaToRomaji(reading)))
      .join(" "),
  );
}

function renderKanjiDetail() {
  if (!els.kanjiDetail) return;
  if (!state.kanji) {
    els.kanjiDetail.hidden = true;
    els.kanjiDetail.replaceChildren();
    return;
  }

  const item = (DATA.kanjiIndex || []).find((kanjiItem) => kanjiItem.kanji === state.kanji) || {
    kanji: state.kanji,
    count: 0,
    on: "",
    kun: "",
    status: "",
  };
  const ownEntries = ownKanjiEntries(state.kanji).slice(0, 8);
  const entryReadings = uniqueValues(ownEntries.flatMap((entry) => [entry.reading, ...(entry.readings || [])]));
  const onReadings = splitKanjiReadings(item.on);
  const kunReadings = splitKanjiReadings(item.kun);

  els.kanjiDetail.hidden = false;
  els.kanjiDetail.innerHTML = `
    <div class="kanji-detail-head">
      <strong class="kanji-glyph">${escapeHtml(item.kanji)}</strong>
      <div class="kanji-detail-meta">
        <span>${escapeHtml(item.status || "未分类")}</span>
        <span>${formatNumber(item.count)} 词条</span>
      </div>
    </div>
    <div class="kanji-detail-section">
      <div class="kanji-detail-title">本字词条</div>
      <div class="kanji-entry-list">
        ${
          ownEntries.length
            ? ownEntries.map((entry) => renderKanjiMiniEntry(entry)).join("")
            : `<div class="kanji-empty">暂无本字词条</div>`
        }
      </div>
    </div>
    <div class="kanji-detail-section">
      <div class="kanji-detail-title">全部读音</div>
      ${renderReadingChips("音读", onReadings)}
      ${renderReadingChips("训读", kunReadings)}
      ${renderReadingChips("词条", entryReadings)}
    </div>
  `;
}

function ownKanjiEntries(kanji) {
  const normalizedKanji = normalizeSearchText(kanji);
  return preparedEntries
    .filter((entry) => (entry.exactWritingTerms || []).includes(normalizedKanji))
    .sort((a, b) => rankValue(a) - rankValue(b) || a.sourceIndex - b.sourceIndex);
}

function renderKanjiMiniEntry(entry) {
  const translation = (entry.translation || []).find(Boolean) || (entry.gloss || []).find(Boolean) || "暂无释义";
  return `
    <div class="kanji-mini-entry" data-level="${escapeHtml(entry.level || "")}">
      <span class="level-badge">${escapeHtml(entry.level || "-")}</span>
      <div>
        <strong>${escapeHtml(entry.word || "")}</strong>
        <span>${escapeHtml(entry.reading || "")}</span>
        <p>${escapeHtml(translation)}</p>
      </div>
    </div>
  `;
}

function renderReadingChips(label, readings) {
  return `
    <div class="kanji-reading-row">
      <span>${escapeHtml(label)}</span>
      <div class="kanji-reading-chips">
        ${
          readings.length
            ? readings
                .map((reading) => {
                  const normalizedReading = normalizeKanjiReading(reading);
                  const active = normalizedReading && normalizedReading === state.kanjiReading;
                  return `<button class="reading-chip ${active ? "active" : ""}" type="button" data-kanji-reading="${escapeHtml(normalizedReading)}" aria-pressed="${active ? "true" : "false"}">${escapeHtml(reading)}</button>`;
                })
                .join("")
            : `<span class="reading-chip muted">-</span>`
        }
      </div>
    </div>
  `;
}

function splitKanjiReadings(value) {
  return uniqueValues(
    String(value || "")
      .split(/[、,，]/)
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

function normalizeKanjiReading(value) {
  return normalizeSearchText(value)
    .replace(/[.\-‐‑‒–—−]/g, "")
    .replace(/\s+/g, "")
    .trim();
}

function bindEvents() {
  els.searchInput.addEventListener("input", () => {
    state.query = els.searchInput.value.trim();
    state.page = 1;
    applyFilters();
  });

  els.termOnlySearchBtn.addEventListener("click", () => {
    state.termOnlySearch = !state.termOnlySearch;
    state.page = 1;
    void persistPreferences();
    applyFilters();
  });

  els.levelFilter.addEventListener("click", (event) => {
    const button = event.target.closest("[data-level-filter]");
    if (!button) return;
    const level = button.dataset.levelFilter || "";
    if (state.levels.has(level)) {
      state.levels.delete(level);
    } else {
      state.levels.add(level);
    }
    state.page = 1;
    applyFilters();
  });

  els.jlptFilter.addEventListener("click", (event) => {
    const button = event.target.closest("[data-jlpt-filter]");
    if (!button) return;
    const level = button.dataset.jlptFilter || "";
    if (state.jlptLevels.has(level)) {
      state.jlptLevels.delete(level);
    } else {
      state.jlptLevels.add(level);
    }
    state.page = 1;
    applyFilters();
  });

  els.transitivityToggleBtn.addEventListener("click", () => {
    if (els.transitivityToggleBtn.disabled) return;
    state.transitivity = nextTransitivity(state.transitivity);
    if (state.transitivity && state.partGroup && !isVerbPartGroup(state.partGroup)) {
      state.partGroup = "verb";
      els.partFilter.value = state.partGroup;
    }
    state.page = 1;
    applyFilters();
  });

  els.partFilter.addEventListener("change", () => {
    state.partGroup = els.partFilter.value;
    if (state.transitivity && state.partGroup && !isVerbPartGroup(state.partGroup)) {
      state.transitivity = "";
    }
    state.page = 1;
    applyFilters();
  });

  els.sortSelect.addEventListener("change", () => {
    state.sort = els.sortSelect.value;
    state.manualSort = true;
    state.shuffled = state.sort === "random";
    state.page = 1;
    applyFilters();
  });

  els.batchSizeSelect.addEventListener("change", () => {
    state.batchSize = Number(els.batchSizeSelect.value);
    state.page = 1;
    void persistPreferences();
    renderEntries();
  });

  els.hideKanaBtn.addEventListener("click", () => {
    state.hideKana = !state.hideKana;
    els.hideKanaBtn.classList.toggle("active", state.hideKana);
    els.hideKanaBtn.setAttribute("aria-pressed", String(state.hideKana));
    void persistPreferences();
    renderEntries();
  });

  els.resetFiltersBtn.addEventListener("click", () => {
    resetFilters();
  });

  els.prevPageBtn.addEventListener("click", () => {
    changePage(-1);
  });

  els.nextPageBtn.addEventListener("click", () => {
    changePage(1);
  });

  els.bottomPrevPageBtn.addEventListener("click", () => {
    changePage(-1, { scrollToEntries: true });
  });

  els.bottomNextPageBtn.addEventListener("click", () => {
    changePage(1, { scrollToEntries: true });
  });

  els.hideGlossBtn.addEventListener("click", () => {
    state.hideGloss = !state.hideGloss;
    els.hideGlossBtn.classList.toggle("active", state.hideGloss);
    els.hideGlossBtn.setAttribute("aria-pressed", String(state.hideGloss));
    void persistPreferences();
    renderEntries();
  });

  document.querySelectorAll("[data-index-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setIndexTab(button.dataset.indexTab || "category");
    });
  });

  document.addEventListener("click", (event) => {
    const readingButton = event.target.closest("[data-kanji-reading]");
    if (readingButton) {
      const reading = readingButton.dataset.kanjiReading || "";
      state.kanjiReading = state.kanjiReading === reading ? "" : reading;
      state.major = "";
      state.cluster = "";
      state.status = "";
      state.page = 1;
      state.shuffled = state.sort === "random";
      applyFilters();
      return;
    }

    const categoryButton = event.target.closest("[data-major]");
    if (categoryButton) {
      const nextMajor = categoryButton.dataset.major || "";
      const nextCluster = categoryButton.dataset.cluster || "";
      const isCurrentCategory = nextMajor === state.major && nextCluster === state.cluster;
      state.major = isCurrentCategory && (nextMajor || nextCluster) ? "" : nextMajor;
      state.cluster = isCurrentCategory && (nextMajor || nextCluster) ? "" : nextCluster;
      state.kanji = "";
      state.kanjiReading = "";
      state.status = "";
      state.page = 1;
      state.shuffled = state.sort === "random";
      applyFilters();
      return;
    }

    const kanjiButton = event.target.closest("[data-kanji]");
    if (kanjiButton) {
      const nextKanji = kanjiButton.dataset.kanji || "";
      state.kanji = state.kanji === nextKanji ? "" : nextKanji;
      state.kanjiReading = "";
      state.major = "";
      state.cluster = "";
      state.status = "";
      state.page = 1;
      state.shuffled = state.sort === "random";
      applyFilters();
      return;
    }

    const markButton = event.target.closest("[data-action][data-entry-id]");
    if (markButton) {
      toggleEntryStatus(markButton.dataset.entryId, markButton.dataset.action);
    }
  });

  els.kanjiSearch.addEventListener("input", () => {
    renderKanjiIndex(els.kanjiSearch.value.trim());
  });

  els.showStarredBtn.addEventListener("click", () => {
    setStatusFilter("starred");
  });
  els.showUnlearnedBtn.addEventListener("click", () => {
    setStatusFilter("unlearned");
  });
  els.showLearnedBtn.addEventListener("click", () => {
    setStatusFilter("learned");
  });
  els.clearStatusBtn.addEventListener("click", () => {
    const confirmed = window.confirm("确定清空本地状态吗？这会删除已标记和已掌握记录。");
    if (!confirmed) return;
    storage.starred.clear();
    storage.learned.clear();
    persistStorage();
    applyFilters();
  });

  document.querySelectorAll("[data-theme-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.themeMode = button.dataset.themeMode || "system";
      void persistPreferences();
      applyAppearance();
    });
  });

  els.backgroundOpacity.addEventListener("input", () => {
    state.backgroundOpacity = clampNumber(els.backgroundOpacity.value, 0, 70, 18);
    void persistPreferences();
    applyAppearance();
  });

  els.panelOpacity.addEventListener("input", () => {
    state.panelOpacity = clampNumber(els.panelOpacity.value, 45, 100, 92);
    void persistPreferences();
    applyAppearance();
  });

  els.backgroundUpload.addEventListener("change", () => {
    const [file] = els.backgroundUpload.files || [];
    if (file) {
      void loadBackgroundFile(file);
    }
  });

  els.clearBackgroundBtn.addEventListener("click", () => {
    const confirmed = window.confirm("确定清除背景吗？已保存的本地背景图片会被删除。");
    if (!confirmed) return;
    void clearStoredBackground();
  });

  els.exportDataBtn.addEventListener("click", () => {
    void exportUserData();
  });

  els.importDataBtn.addEventListener("click", () => {
    els.importDataInput.click();
  });

  els.importDataInput.addEventListener("change", () => {
    const [file] = els.importDataInput.files || [];
    if (file) {
      void importUserData(file);
    }
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (state.themeMode === "system") {
      applyAppearance();
    }
  });
}

function syncPreferenceControls() {
  if (els.batchSizeSelect) {
    els.batchSizeSelect.value = String(state.batchSize);
  }
  if (els.hideGlossBtn) {
    els.hideGlossBtn.classList.toggle("active", state.hideGloss);
    els.hideGlossBtn.setAttribute("aria-pressed", String(state.hideGloss));
  }
  if (els.hideKanaBtn) {
    els.hideKanaBtn.classList.toggle("active", state.hideKana);
    els.hideKanaBtn.setAttribute("aria-pressed", String(state.hideKana));
  }
  setIndexTab(state.indexTab, { persist: false });
}

function setIndexTab(tab, options = {}) {
  const nextTab = INDEX_TABS.has(tab) ? tab : "category";
  state.indexTab = nextTab;
  document.querySelectorAll("[data-index-tab]").forEach((button) => {
    button.classList.toggle("active", (button.dataset.indexTab || "category") === state.indexTab);
  });
  els.categoryPanel.classList.toggle("active", state.indexTab === "category");
  els.kanjiPanel.classList.toggle("active", state.indexTab === "kanji");
  els.savedPanel.classList.toggle("active", state.indexTab === "saved");
  els.settingsPanel.classList.toggle("active", state.indexTab === "settings");
  if (options.persist !== false) {
    void persistPreferences();
  }
}

async function restoreStoredBackground() {
  const storedBackground = await APP_STORE.loadBackground();
  if (storedBackground?.blob) {
    state.backgroundName = storedBackground.name || "";
    setBackgroundImageUrl(URL.createObjectURL(storedBackground.blob), { objectUrl: true });
    return;
  }

  const legacyDataUrl = APP_STORE.loadLegacyBackgroundDataUrl();
  if (!legacyDataUrl) return;

  setBackgroundImageUrl(legacyDataUrl);
  setBackgroundStatus("背景已从旧存储恢复，正在迁移");
  try {
    const blob = await dataUrlToBlob(legacyDataUrl);
    await APP_STORE.saveBackground(blob, {
      name: "legacy-background",
      type: blob.type,
      size: blob.size,
    });
    APP_STORE.clearLegacyBackgroundDataUrl();
    setBackgroundImageUrl(URL.createObjectURL(blob), { objectUrl: true });
    setBackgroundStatus("背景已迁移到本地图库");
  } catch {
    setBackgroundStatus("背景已应用，旧存储迁移失败");
  }
}

async function loadBackgroundFile(file) {
  if (!file.type.startsWith("image/")) {
    setBackgroundStatus("请选择图片文件");
    return;
  }

  state.backgroundName = file.name || "";
  setBackgroundImageUrl(URL.createObjectURL(file), { objectUrl: true });
  setBackgroundStatus("背景已应用，正在保存");
  try {
    await APP_STORE.saveBackground(file, {
      name: file.name || "background",
      type: file.type,
      size: file.size,
    });
    setBackgroundStatus(file.size > 6000000 ? "背景已保存，大图可能影响加载速度" : "背景已保存");
  } catch {
    setBackgroundStatus("背景已应用于当前会话，未能保存");
  }
}

async function clearStoredBackground() {
  setBackgroundImageUrl("");
  state.backgroundName = "";
  els.backgroundUpload.value = "";
  try {
    await APP_STORE.clearBackground();
    setBackgroundStatus("背景已清除");
  } catch {
    setBackgroundStatus("背景已从当前页面清除，存储清理失败");
  }
}

function setBackgroundImageUrl(url, options = {}) {
  if (activeBackgroundObjectUrl && activeBackgroundObjectUrl !== url) {
    URL.revokeObjectURL(activeBackgroundObjectUrl);
  }
  activeBackgroundObjectUrl = options.objectUrl ? url : "";
  state.backgroundImage = url;
  applyAppearance();
}

function applyAppearance() {
  const resolvedTheme =
    state.themeMode === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : state.themeMode;

  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themeMode = state.themeMode;
  document.documentElement.style.setProperty(
    "--custom-bg-image",
    state.backgroundImage ? `url("${state.backgroundImage.replaceAll('"', '\\"')}")` : "none",
  );
  document.documentElement.style.setProperty("--custom-bg-opacity", String(state.backgroundOpacity / 100));
  document.documentElement.style.setProperty("--panel-opacity", String(state.panelOpacity / 100));

  if (els.backgroundOpacity) {
    els.backgroundOpacity.value = String(state.backgroundOpacity);
  }
  if (els.backgroundOpacityLabel) {
    els.backgroundOpacityLabel.textContent = `${state.backgroundOpacity}%`;
  }
  if (els.panelOpacity) {
    els.panelOpacity.value = String(state.panelOpacity);
  }
  if (els.panelOpacityLabel) {
    els.panelOpacityLabel.textContent = `${state.panelOpacity}%`;
  }
  document.querySelectorAll("[data-theme-mode]").forEach((button) => {
    button.classList.toggle("active", (button.dataset.themeMode || "system") === state.themeMode);
  });
}

function setBackgroundStatus(message) {
  if (els.backgroundStatus) {
    els.backgroundStatus.textContent = message;
  }
}

async function exportUserData() {
  try {
    const background = await APP_STORE.loadBackground();
    const payload = {
      app: "Mio",
      version: 1,
      exportedAt: new Date().toISOString(),
      preferences: snapshotPreferences(),
      progress: snapshotProgress(),
      background: null,
    };
    if (background?.blob) {
      payload.background = {
        name: background.name || "background",
        type: background.type || background.blob.type || "application/octet-stream",
        size: background.size || background.blob.size || 0,
        dataUrl: await blobToDataUrl(background.blob),
      };
    }
    downloadJson(payload, `mio-data-${dateStamp()}.json`);
    setBackgroundStatus("本地数据已导出");
  } catch {
    setBackgroundStatus("导出失败");
  }
}

async function importUserData(file) {
  try {
    const payload = JSON.parse(await file.text());
    const preferences = normalizePreferences(payload.preferences || {});
    const progress = normalizeProgress(payload.progress || {});

    Object.assign(state, {
      themeMode: preferences.themeMode,
      backgroundOpacity: preferences.backgroundOpacity,
      panelOpacity: preferences.panelOpacity,
      batchSize: preferences.batchSize,
      hideKana: preferences.hideKana,
      hideGloss: preferences.hideGloss,
      termOnlySearch: preferences.termOnlySearch,
      indexTab: preferences.indexTab,
    });
    storage.starred = new Set(progress.starred);
    storage.learned = new Set(progress.learned);

    if (payload.background?.dataUrl) {
      const blob = await dataUrlToBlob(payload.background.dataUrl);
      state.backgroundName = payload.background.name || "background";
      await APP_STORE.saveBackground(blob, {
        name: state.backgroundName,
        type: payload.background.type || blob.type,
        size: payload.background.size || blob.size,
      });
      setBackgroundImageUrl(URL.createObjectURL(blob), { objectUrl: true });
    }

    await persistPreferences();
    persistStorage();
    syncPreferenceControls();
    applyAppearance();
    applyFilters();
    setBackgroundStatus("本地数据已导入");
  } catch {
    setBackgroundStatus("导入失败，请确认文件格式");
  } finally {
    els.importDataInput.value = "";
  }
}

function setStatusFilter(status) {
  state.status = state.status === status ? "" : status;
  state.major = "";
  state.cluster = "";
  state.kanji = "";
  state.kanjiReading = "";
  state.page = 1;
  state.shuffled = state.sort === "random";
  applyFilters();
}

function resetFilters() {
  state.major = "";
  state.cluster = "";
  state.levels.clear();
  state.jlptLevels.clear();
  state.transitivity = "";
  state.partGroup = "";
  state.kanji = "";
  state.kanjiReading = "";
  state.status = "";
  state.sort = "rank";
  state.manualSort = false;
  state.page = 1;
  state.shuffled = false;
  shuffledIds = [];

  els.partFilter.value = "";
  els.sortSelect.value = "rank";
  els.kanjiSearch.value = "";
  renderKanjiIndex("");
  applyFilters();
}

function applyFilters() {
  state.query = els.searchInput.value.trim();
  const tokens = normalizeSearchText(state.query)
    .split(/\s+/)
    .filter(Boolean);

  filteredEntries = preparedEntries.filter((entry) => {
    if (state.major && entry.major !== state.major) return false;
    if (state.cluster && entry.cluster !== state.cluster) return false;
    if (state.levels.size && !state.levels.has(entry.level)) return false;
    if (state.jlptLevels.size && !state.jlptLevels.has(entry.jlpt)) return false;
    if (state.partGroup && !matchesPartGroup(entry, state.partGroup)) return false;
    if (state.kanji && !(entry.kanji || []).includes(state.kanji)) return false;
    if (state.kanji && state.kanjiReading && !entryMatchesKanjiReading(entry, state.kanji, state.kanjiReading)) {
      return false;
    }
    if (state.status === "starred" && !storage.starred.has(entry.id)) return false;
    if (state.status === "learned" && !storage.learned.has(entry.id)) return false;
    if (state.status === "unlearned" && storage.learned.has(entry.id)) return false;
    return tokens.every((token) => entryMatchesSearchToken(entry, token));
  });

  hasVerbCandidates = filteredEntries.some((entry) => isVerbEntry(entry));
  if (!hasVerbCandidates && state.transitivity) {
    state.transitivity = "";
  }
  if (state.transitivity) {
    filteredEntries = filteredEntries.filter((entry) => matchesTransitivity(entry, state.transitivity));
  }

  for (const entry of filteredEntries) {
    entry.exactSearchScore = exactSearchScore(entry, tokens);
  }

  sortEntries(filteredEntries);
  if (state.shuffled) {
    shuffledIds = shuffle(filteredEntries.map((entry) => entry.id));
  }
  state.page = Math.min(state.page, totalPages());
  updateSummary();
  updateActiveButtons();
  renderEntries();
}

function matchesPartGroup(entry, partGroup) {
  const major = entry.major || "";
  if (partGroup === "noun") return isNounEntry(entry);
  if (partGroup === "common_noun") return hasAnySubposContaining(entry, ["noun (common)"]);
  if (partGroup === "proper_noun") return normalizePartLabel(entry.bccwjPos).includes("固有名詞");
  if (partGroup === "suru_noun") return hasAnySubposContaining(entry, ["takes the aux. verb suru"]);
  if (partGroup === "no_adjective") return hasAnySubposContaining(entry, ["genitive case particle 'no'"]);
  if (partGroup === "pronoun") return hasSubposExact(entry, "pronoun");
  if (partGroup === "numeric") return hasSubposExact(entry, "numeric");
  if (partGroup === "counter") return hasSubposExact(entry, "counter");
  if (partGroup === "verb") return isVerbEntry(entry);
  if (partGroup === "transitive_verb") return matchesTransitivity(entry, "他动词");
  if (partGroup === "intransitive_verb") return matchesTransitivity(entry, "自动词");
  if (partGroup === "ichidan_verb") return hasAnySubposContaining(entry, ["Ichidan verb"]);
  if (partGroup === "godan_verb") return hasAnySubposContaining(entry, ["Godan verb"]);
  if (partGroup === "suru_verb") return hasAnySubposContaining(entry, ["suru verb"]);
  if (partGroup === "kuru_verb") return hasAnySubposContaining(entry, ["Kuru verb"]);
  if (partGroup === "special_verb") {
    return hasAnySubposContaining(entry, [
      "special class",
      "irregular verb",
      "irregular ru verb",
      "Nidan verb",
      "Yodan verb",
      "su verb",
    ]);
  }
  if (partGroup === "adjective") return isAdjectiveEntry(entry);
  if (partGroup === "i_adjective") return major === "一类形容词" || hasAnySubposContaining(entry, ["adjective (keiyoushi)"]);
  if (partGroup === "na_adjective") {
    return major === "二类形容词" || hasAnySubposContaining(entry, ["adjectival nouns or quasi-adjectives"]);
  }
  if (partGroup === "taru_adjective") return hasSubposExact(entry, "'taru' adjective");
  if (partGroup === "adverb") return hasSubposStartingWith(entry, "adverb");
  if (partGroup === "adverb_to") return hasSubposExact(entry, "adverb taking the 'to' particle");
  if (partGroup === "prenominal") {
    return hasAnySubposContaining(entry, ["pre-noun adjectival", "noun or verb acting prenominally"]);
  }
  if (partGroup === "expression") return hasAnySubposContaining(entry, ["expressions"]);
  if (partGroup === "interjection") return hasAnySubposContaining(entry, ["interjection"]);
  if (partGroup === "conjunction") return hasSubposExact(entry, "conjunction");
  if (partGroup === "particle") return hasSubposExact(entry, "particle");
  if (partGroup === "auxiliary") {
    return hasAnySubposExact(entry, ["auxiliary", "auxiliary verb", "auxiliary adjective", "copula"]);
  }
  if (partGroup === "prefix") return hasSubposStartingWith(entry, "prefix") || hasAnySubposContaining(entry, ["used as a prefix"]);
  if (partGroup === "suffix") return hasSubposStartingWith(entry, "suffix") || hasAnySubposContaining(entry, ["used as a suffix"]);
  if (partGroup === "unclassified") return hasSubposExact(entry, "unclassified");
  return true;
}

function matchesTransitivity(entry, transitivity) {
  if (transitivity === "自动词") return hasSubposExact(entry, "intransitive verb") || entry.transitivity === "自动词";
  if (transitivity === "他动词") return hasSubposExact(entry, "transitive verb") || entry.transitivity === "他动词";
  if (transitivity === "自他両用") {
    return (
      entry.transitivity === "自他両用" ||
      (hasSubposExact(entry, "transitive verb") && hasSubposExact(entry, "intransitive verb"))
    );
  }
  return entry.transitivity === transitivity;
}

function nextTransitivity(value) {
  const index = TRANSITIVITY_SEQUENCE.includes(value) ? TRANSITIVITY_SEQUENCE.indexOf(value) : 0;
  return TRANSITIVITY_SEQUENCE[(index + 1) % TRANSITIVITY_SEQUENCE.length];
}

function transitivityButtonLabel(value) {
  return (
    {
      "": "自他：全部",
      自动词: "自他：自",
      他动词: "自他：他",
      自他両用: "自他：自他",
    }[value] || "自他：全部"
  );
}

function isVerbPartGroup(partGroup) {
  return [
    "verb",
    "transitive_verb",
    "intransitive_verb",
    "ichidan_verb",
    "godan_verb",
    "suru_verb",
    "kuru_verb",
    "special_verb",
  ].includes(partGroup);
}

function isNounEntry(entry) {
  return (
    entry.major === "名词" ||
    hasAnySubposContaining(entry, ["noun", "pronoun", "numeric", "counter"])
  );
}

function isVerbEntry(entry) {
  return (
    entry.major === "动词" ||
    hasAnySubposContaining(entry, [
      "Godan verb",
      "Ichidan verb",
      "suru verb",
      "Kuru verb",
      "su verb",
      "Nidan verb",
      "Yodan verb",
      "irregular ru verb",
      "transitive verb",
      "intransitive verb",
      "auxiliary verb",
    ])
  );
}

function isAdjectiveEntry(entry) {
  return (
    entry.major === "一类形容词" ||
    entry.major === "二类形容词" ||
    hasAnySubposContaining(entry, [
      "adjective (keiyoushi)",
      "adjectival nouns or quasi-adjectives",
      "'taru' adjective",
      "auxiliary adjective",
    ])
  );
}

function hasAnySubposContaining(entry, values) {
  return values.some((value) => subposItems(entry).some((item) => item.includes(normalizePartLabel(value))));
}

function hasAnySubposExact(entry, values) {
  return values.some((value) => hasSubposExact(entry, value));
}

function hasSubposExact(entry, value) {
  const normalizedValue = normalizePartLabel(value);
  return subposItems(entry).some((item) => item === normalizedValue);
}

function hasSubposStartingWith(entry, value) {
  const normalizedValue = normalizePartLabel(value);
  return subposItems(entry).some((item) => item.startsWith(normalizedValue));
}

function subposItems(entry) {
  return String(entry.subpos || "")
    .split(/[；;]/)
    .map((item) => normalizePartLabel(item))
    .filter(Boolean);
}

function normalizePartLabel(value) {
  return String(value || "").normalize("NFKC").toLowerCase();
}

function entryMatchesSearchToken(entry, token) {
  if (!state.termOnlySearch) return entry.searchText.includes(token);
  if (hasKanji(token)) return entry.termWritingSearchText.includes(token);
  return entry.termReadingSearchText.includes(token) || entry.termWritingSearchText.includes(token);
}

function entryMatchesKanjiReading(entry, kanji, reading) {
  const normalizedReading = normalizeKanjiReading(reading);
  if (!normalizedReading || !(entry.kanji || []).includes(kanji)) return false;
  const readings = entryReadingValues(entry);
  const writings = entryWritingValues(entry).filter((writing) => writingContainsKanji(writing, kanji));
  if (!writings.length) {
    return readings.some((item) => readingHasSafeOccurrence(item, normalizedReading));
  }
  return writings.some((writing) =>
    readings.some((item) => readingMatchesKanjiPosition(writing, item, kanji, normalizedReading)),
  );
}

function entryReadingValues(entry) {
  return uniqueValues([entry.reading, ...(entry.readings || [])].map((item) => normalizeSearchText(item)));
}

function entryWritingValues(entry) {
  return uniqueValues([entry.word, ...(entry.writings || [])].map((item) => normalizeSearchText(item)));
}

function writingContainsKanji(writing, kanji) {
  const normalizedKanji = normalizeSearchText(kanji);
  return Array.from(writing || "").some((char) => normalizeIndexedText(char).includes(normalizedKanji));
}

function kanjiPositionsInWriting(writing, kanji) {
  const normalizedKanji = normalizeSearchText(kanji);
  return Array.from(writing || "")
    .map((char, index) => (normalizeIndexedText(char).includes(normalizedKanji) ? index : -1))
    .filter((index) => index >= 0);
}

function readingMatchesKanjiPosition(writing, entryReading, kanji, kanjiReading) {
  if (!readingHasSafeOccurrence(entryReading, kanjiReading)) return false;
  const chars = Array.from(writing || "");
  const positions = kanjiPositionsInWriting(writing, kanji);
  return positions.some((position) => {
    if (position === 0 && entryReading.startsWith(kanjiReading)) return true;
    if (position === chars.length - 1 && entryReading.endsWith(kanjiReading)) return true;
    if (position > 0 && position < chars.length - 1) {
      return readingHasSafeOccurrence(entryReading, kanjiReading);
    }
    return false;
  });
}

function readingHasSafeOccurrence(entryReading, kanjiReading) {
  let index = entryReading.indexOf(kanjiReading);
  while (index >= 0) {
    if (!isUnsafeReadingOccurrence(entryReading, kanjiReading, index)) return true;
    index = entryReading.indexOf(kanjiReading, index + 1);
  }
  return false;
}

function isUnsafeReadingOccurrence(entryReading, kanjiReading, index) {
  if (index <= 0) return false;
  const first = kanjiReading[0] || "";
  const previous = entryReading[index - 1] || "";
  if (first === "う" && /[おこごそぞとどのほぼぽもよょろをぉ]/.test(previous)) return true;
  if (first === "い" && /[えけげせぜてでねへべぺめれぇ]/.test(previous)) return true;
  return false;
}

function exactSearchScore(entry, tokens) {
  if (!tokens.length) return 0;
  let score = Infinity;
  for (const token of tokens) {
    const tokenScore = exactSearchTokenScore(entry, token);
    if (!tokenScore) return 0;
    score = Math.min(score, tokenScore);
  }
  return Number.isFinite(score) ? score : 0;
}

function exactSearchTokenScore(entry, token) {
  if ((entry.exactWritingTerms || []).includes(token)) return 40;
  if ((entry.exactReadingTerms || []).includes(token)) return 32;
  if ((entry.exactRomajiTerms || []).includes(token)) return 30;
  if ((entry.exactKanjiTerms || []).includes(token)) return 20;
  return 0;
}

function shouldPinExactMatches() {
  return Boolean(state.query && !state.manualSort && state.sort === "rank");
}

function sortEntries(entries) {
  const collator = new Intl.Collator("ja-JP");
  const pinExact = shouldPinExactMatches();
  entries.sort((a, b) => {
    if (pinExact && a.exactSearchScore !== b.exactSearchScore) {
      return b.exactSearchScore - a.exactSearchScore;
    }
    if (state.sort === "reading") {
      return collator.compare(a.reading || "", b.reading || "") || collator.compare(a.word || "", b.word || "");
    }
    if (state.sort === "word") {
      return collator.compare(a.word || "", b.word || "") || collator.compare(a.reading || "", b.reading || "");
    }
    if (state.sort === "category") {
      return (
        collator.compare(a.major || "", b.major || "") ||
        collator.compare(a.cluster || "", b.cluster || "") ||
        collator.compare(a.reading || "", b.reading || "")
      );
    }
    return rankValue(a) - rankValue(b) || collator.compare(a.reading || "", b.reading || "");
  });
}

function renderEntries() {
  const pages = totalPages();
  state.page = Math.max(1, Math.min(state.page, pages));
  const ordered = state.shuffled ? orderByShuffle(filteredEntries) : filteredEntries;
  const start = (state.page - 1) * state.batchSize;
  const pageEntries = ordered.slice(start, start + state.batchSize);

  els.emptyState.hidden = filteredEntries.length > 0;
  els.entryGrid.hidden = filteredEntries.length === 0;
  els.prevPageBtn.disabled = state.page <= 1;
  els.nextPageBtn.disabled = state.page >= pages;
  els.bottomPrevPageBtn.disabled = state.page <= 1;
  els.bottomNextPageBtn.disabled = state.page >= pages;
  const pageText = `第 ${formatNumber(state.page)} / ${formatNumber(pages)} 批`;
  els.pageLabel.textContent = pageText;
  els.bottomPageLabel.textContent = pageText;
  els.bottomPager.hidden = filteredEntries.length === 0;
  els.termOnlySearchBtn.classList.toggle("active", state.termOnlySearch);
  els.termOnlySearchBtn.setAttribute("aria-pressed", String(state.termOnlySearch));

  const fragment = document.createDocumentFragment();
  for (const entry of pageEntries) {
    fragment.append(renderEntryCard(entry));
  }
  els.entryGrid.replaceChildren(fragment);
}

function changePage(delta, options = {}) {
  const pages = totalPages();
  const nextPage = Math.max(1, Math.min(state.page + delta, pages));
  if (nextPage === state.page) return;
  state.page = nextPage;
  renderEntries();
  if (options.scrollToEntries) {
    requestAnimationFrame(() => {
      els.entryGrid.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }
}

function renderEntryCard(entry) {
  const card = document.createElement("article");
  card.className = "entry-card";
  card.dataset.level = entry.level || "";
  card.dataset.jlpt = entry.jlpt || "";
  card.classList.toggle("exact-match", Boolean(state.query && entry.exactSearchScore));
  card.classList.toggle("starred", storage.starred.has(entry.id));
  card.classList.toggle("learned", storage.learned.has(entry.id));

  const glossItems = (entry.gloss || []).slice(0, 5);
  const translationItems = (entry.translation || []).slice(0, 5);
  const exampleItems = (EXAMPLES_BY_ENTRY[entry.id] || []).slice(0, 2);
  const translationSource = entry.translationSource || "翻译来源未标注";
  const glossSource = "JMdict/EDRDG";
  const translationText = joinDefinitionItems(translationItems);
  const glossText = joinDefinitionItems(glossItems);
  const readingText = entry.reading || "";
  const readingsText = joinList(entry.readings);
  const rank = entry.rank ? `#${formatNumber(entry.rank)}` : "无频率";
  const meta = [
    entry.major,
    entry.cluster,
    entry.transitivity,
    entry.conjugation,
    rank,
    ...(entry.tags || []).slice(0, 2),
  ].filter(Boolean);

  card.innerHTML = `
    <div class="entry-top">
      <div class="term">
        <div class="word-line">
          <span class="level-badge">${escapeHtml(entry.level || "-")}</span>
          ${renderJlptBadge(entry)}
          <span class="word">${escapeHtml(entry.word || "")}</span>
        </div>
        <div class="reading kana-maskable ${state.hideKana ? "masked" : ""}" data-kana-text="${escapeHtml(readingText)}">${
          state.hideKana ? "" : escapeHtml(readingText)
        }</div>
      </div>
      <div class="card-actions">
        <button class="mark-button ${storage.starred.has(entry.id) ? "active" : ""}" type="button" data-action="star" data-entry-id="${escapeHtml(entry.id)}" aria-label="标记">☆</button>
        <button class="mark-button ${storage.learned.has(entry.id) ? "active" : ""}" type="button" data-action="learned" data-entry-id="${escapeHtml(entry.id)}" aria-label="掌握">✓</button>
      </div>
    </div>
    <div class="meta-row">
      ${meta.map((item) => `<span class="meta-chip">${escapeHtml(item)}</span>`).join("")}
    </div>
    <div class="definition-scroll">
      <section class="definition-block translation-block">
        <div class="section-heading">
          <strong>中文翻译</strong>
          <span>${escapeHtml(translationSource)}</span>
        </div>
        <ul class="translation-list ${state.hideGloss ? "masked" : ""}">
          ${
            state.hideGloss
              ? ""
              : translationText
                ? `<li>${escapeHtml(translationText)}</li>`
                :
                `<li class="muted-text">暂无中文翻译</li>`
          }
        </ul>
      </section>
      <section class="definition-block gloss-block">
        <div class="section-heading">
          <strong>英文释义</strong>
          <span>${escapeHtml(glossSource)}</span>
        </div>
        <ul class="gloss-list ${state.hideGloss ? "masked" : ""}">
          ${
            state.hideGloss
              ? ""
              : glossText
                ? `<li>${escapeHtml(glossText)}</li>`
                :
                `<li class="muted-text">暂无英文释义</li>`
          }
        </ul>
      </section>
      ${renderExamplesSection(exampleItems)}
    </div>
    <div class="details-grid">
      <div><strong>全部表记</strong> ${escapeHtml(joinList(entry.writings))}</div>
      <div><strong>全部读音</strong> <span class="kana-maskable inline-kana ${state.hideKana ? "masked" : ""}" data-kana-text="${escapeHtml(readingsText)}">${
        state.hideKana ? "" : escapeHtml(readingsText)
      }</span></div>
      <div><strong>核心汉字</strong> ${escapeHtml(joinList(entry.kanji))}</div>
      ${entry.pair ? `<div><strong>自他候补</strong> ${escapeHtml(entry.pair)}</div>` : ""}
      ${entry.subpos ? `<div><strong>细品词</strong> ${escapeHtml(entry.subpos)}</div>` : ""}
    </div>
  `;

  if (state.hideKana) {
    card.querySelectorAll(".kana-maskable.masked").forEach((item) => {
      item.addEventListener("click", (event) => {
        const target = event.currentTarget;
        target.classList.remove("masked");
        target.textContent = target.dataset.kanaText || "";
      });
    });
  }

  if (state.hideGloss) {
    const revealList = (selector, items, fallback) => {
      const list = card.querySelector(selector);
      list.addEventListener("click", (event) => {
        const text = joinDefinitionItems(items);
        event.currentTarget.classList.remove("masked");
        event.currentTarget.innerHTML =
          (text ? `<li>${escapeHtml(text)}</li>` : "") || `<li class="muted-text">${escapeHtml(fallback)}</li>`;
      });
    };
    revealList(".translation-list", translationItems, "暂无中文翻译");
    revealList(".gloss-list", glossItems, "暂无英文释义");
    card.querySelectorAll(".example-zh.masked").forEach((line) => {
      line.addEventListener("click", (event) => {
        const target = event.currentTarget;
        target.classList.remove("masked");
        target.textContent = target.dataset.exampleZh || "";
      });
    });
  }

  return card;
}

function renderJlptBadge(entry) {
  if (!entry.jlpt) {
    return "";
  }
  const source = entry.jlptSource || "Tanos JLPT / CC BY";
  const note = entry.jlptNote || "非官方参考等级";
  return `<span class="jlpt-badge" title="${escapeHtml(`${source}；${note}`)}">${escapeHtml(entry.jlpt)}</span>`;
}

function renderExamplesSection(exampleItems) {
  if (!exampleItems.length) {
    return "";
  }
  const sourceLabel = exampleItems[0]?.source || "Tatoeba / CC BY";
  const countLabel = `${exampleItems.length} 条`;
  const items = exampleItems
    .map((example) => {
      const zh = example.zh || "";
      const sentenceId = example.sentenceId || "";
      const sourceUrl = example.url || (sentenceId ? `https://tatoeba.org/en/sentences/show/${sentenceId}` : "");
      return `
        <li class="example-item">
          <p class="example-ja">${escapeHtml(example.ja || "")}</p>
          <p class="example-zh ${state.hideGloss ? "masked" : ""}" data-example-zh="${escapeHtml(zh)}">${
            state.hideGloss ? "" : escapeHtml(zh)
          }</p>
          ${
            sourceUrl
              ? `<a class="example-source" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">#${escapeHtml(sentenceId)}</a>`
              : ""
          }
        </li>
      `;
    })
    .join("");
  return `
    <details class="definition-block examples-block">
      <summary class="examples-summary">
        <span><strong>例句</strong><small>${escapeHtml(countLabel)}</small></span>
        <span>${escapeHtml(sourceLabel)}</span>
      </summary>
      <ol class="example-list">${items}</ol>
    </details>
  `;
}

function updateSummary() {
  const majors = new Set();
  const kanji = new Set();
  for (const entry of filteredEntries) {
    if (entry.major) majors.add(entry.major);
    for (const item of entry.kanji || []) kanji.add(item);
  }
  els.resultCount.textContent = formatNumber(filteredEntries.length);
  els.majorCount.textContent = formatNumber(majors.size);
  els.kanjiCount.textContent = formatNumber(kanji.size);
  els.activeFilter.textContent = describeActiveFilter();
}

function updateActiveButtons() {
  document.querySelectorAll("[data-major]").forEach((button) => {
    button.classList.toggle(
      "active",
      (button.dataset.major || "") === state.major && (button.dataset.cluster || "") === state.cluster,
    );
  });
  document.querySelectorAll("[data-kanji]").forEach((button) => {
    button.classList.toggle("active", (button.dataset.kanji || "") === state.kanji);
  });
  document.querySelectorAll("[data-level-filter]").forEach((button) => {
    const active = state.levels.has(button.dataset.levelFilter || "");
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-jlpt-filter]").forEach((button) => {
    const active = state.jlptLevels.has(button.dataset.jlptFilter || "");
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  els.showStarredBtn.classList.toggle("active", state.status === "starred");
  els.showUnlearnedBtn.classList.toggle("active", state.status === "unlearned");
  els.showLearnedBtn.classList.toggle("active", state.status === "learned");
  els.resetFiltersBtn.classList.toggle("active", hasActiveFilters());
  updateTransitivityToggle();
  renderKanjiDetail();
}

function updateTransitivityToggle() {
  els.transitivityToggleBtn.disabled = !hasVerbCandidates;
  els.transitivityToggleBtn.textContent = hasVerbCandidates ? transitivityButtonLabel(state.transitivity) : "自他：无";
  els.transitivityToggleBtn.title = hasVerbCandidates ? "点击切换全部 / 自 / 他 / 自他" : "当前结果没有动词";
  els.transitivityToggleBtn.classList.toggle("available", hasVerbCandidates);
  els.transitivityToggleBtn.classList.toggle("active", Boolean(state.transitivity));
  els.transitivityToggleBtn.setAttribute("aria-pressed", String(Boolean(state.transitivity)));
}

function describeActiveFilter() {
  const parts = [];
  if (state.major) parts.push(state.major);
  if (state.cluster) parts.push(state.cluster);
  if (state.kanji) parts.push(`核心汉字: ${state.kanji}`);
  if (state.kanjiReading) parts.push(`读音: ${state.kanjiReading}`);
  if (state.levels.size) parts.push(`等级 ${[...state.levels].join("")}`);
  if (state.jlptLevels.size) parts.push(`JLPT ${formatJlptSelection()}`);
  if (state.transitivity) parts.push(state.transitivity);
  if (state.partGroup) parts.push(partGroupLabel(state.partGroup));
  if (state.status === "starred") parts.push("已标记");
  if (state.status === "learned") parts.push("已掌握");
  if (state.status === "unlearned") parts.push("未掌握");
  if (state.manualSort || state.sort !== "rank") parts.push(`排序: ${sortLabel(state.sort)}`);
  if (state.termOnlySearch && !state.query) parts.push("只搜日语");
  if (state.query) parts.push(`${state.termOnlySearch ? "日语词搜索" : "搜索"}: ${state.query}`);
  return parts.length ? parts.join(" / ") : "全部";
}

function hasActiveFilters() {
  return Boolean(
    state.major ||
      state.cluster ||
      state.levels.size ||
      state.jlptLevels.size ||
      state.transitivity ||
      state.partGroup ||
      state.kanji ||
      state.kanjiReading ||
      state.status ||
      state.manualSort ||
      state.sort !== "rank",
  );
}

function formatJlptSelection() {
  return JLPT_LEVEL_ORDER.filter((level) => state.jlptLevels.has(level)).join("/");
}

function partGroupLabel(partGroup) {
  return (
    {
      noun: "名词",
      common_noun: "普通名词",
      proper_noun: "专有名词",
      suru_noun: "サ变名词",
      no_adjective: "の形容词",
      pronoun: "代词",
      numeric: "数词",
      counter: "助数词",
      verb: "动词",
      transitive_verb: "他动词",
      intransitive_verb: "自动词",
      ichidan_verb: "一段动词",
      godan_verb: "五段动词",
      suru_verb: "サ变动词",
      kuru_verb: "カ变动词",
      special_verb: "特殊/古语动词",
      adjective: "形容词",
      i_adjective: "一类形容词",
      na_adjective: "二类形容词",
      taru_adjective: "タル形容词",
      adverb: "副词",
      adverb_to: "と副词",
      prenominal: "连体词",
      expression: "表达/惯用句",
      interjection: "感叹词",
      conjunction: "接续词",
      particle: "助词",
      auxiliary: "助动/助形",
      prefix: "接头词",
      suffix: "接尾词",
      unclassified: "未分类",
    }[partGroup] || partGroup
  );
}

function sortLabel(sort) {
  return (
    {
      rank: "常用度",
      reading: "读音",
      word: "表记",
      category: "类别",
      random: "随机",
    }[sort] || sort
  );
}

function toggleEntryStatus(id, action) {
  if (action === "star") {
    toggleSetValue(storage.starred, id);
  }
  if (action === "learned") {
    toggleSetValue(storage.learned, id);
  }
  persistStorage();
  renderEntries();
  updateActiveButtons();
}

function toggleSetValue(set, value) {
  if (set.has(value)) {
    set.delete(value);
  } else {
    set.add(value);
  }
}

function snapshotPreferences() {
  return normalizePreferences({
    themeMode: state.themeMode,
    backgroundOpacity: state.backgroundOpacity,
    panelOpacity: state.panelOpacity,
    batchSize: state.batchSize,
    hideKana: state.hideKana,
    hideGloss: state.hideGloss,
    termOnlySearch: state.termOnlySearch,
    indexTab: state.indexTab,
  });
}

function snapshotProgress() {
  return normalizeProgress({
    starred: [...storage.starred],
    learned: [...storage.learned],
  });
}

function persistPreferences() {
  return APP_STORE.savePreferences(snapshotPreferences());
}

function persistStorage() {
  void APP_STORE.saveProgress(snapshotProgress());
}

function createBrowserLexiconStore() {
  return {
    loadPreferences() {
      const stored = readStoredJson(APP_STORAGE_KEYS.preferences);
      if (stored) return normalizePreferences(stored);
      return normalizePreferences({
        themeMode: readStoredString(LEGACY_STORAGE_KEYS.themeMode, DEFAULT_PREFERENCES.themeMode),
        backgroundOpacity: readStoredString(
          LEGACY_STORAGE_KEYS.backgroundOpacity,
          String(DEFAULT_PREFERENCES.backgroundOpacity),
        ),
        panelOpacity: readStoredString(LEGACY_STORAGE_KEYS.panelOpacity, String(DEFAULT_PREFERENCES.panelOpacity)),
      });
    },

    async savePreferences(preferences) {
      if (writeStoredJson(APP_STORAGE_KEYS.preferences, normalizePreferences(preferences))) {
        safeRemoveStoredItem(LEGACY_STORAGE_KEYS.themeMode);
        safeRemoveStoredItem(LEGACY_STORAGE_KEYS.backgroundOpacity);
        safeRemoveStoredItem(LEGACY_STORAGE_KEYS.panelOpacity);
      }
    },

    loadProgress() {
      const stored = readStoredJson(APP_STORAGE_KEYS.progress);
      if (stored) return normalizeProgress(stored);
      return normalizeProgress({
        starred: readStoredList(LEGACY_STORAGE_KEYS.starred),
        learned: readStoredList(LEGACY_STORAGE_KEYS.learned),
      });
    },

    async saveProgress(progress) {
      if (writeStoredJson(APP_STORAGE_KEYS.progress, normalizeProgress(progress))) {
        safeRemoveStoredItem(LEGACY_STORAGE_KEYS.starred);
        safeRemoveStoredItem(LEGACY_STORAGE_KEYS.learned);
      }
    },

    async loadBackground() {
      try {
        return await idbGet("background");
      } catch {
        return null;
      }
    },

    async saveBackground(blob, meta = {}) {
      await idbPut({
        id: "background",
        blob,
        name: meta.name || "background",
        type: meta.type || blob.type || "",
        size: meta.size || blob.size || 0,
        updatedAt: new Date().toISOString(),
      });
      this.clearLegacyBackgroundDataUrl();
    },

    async clearBackground() {
      await idbDelete("background");
      this.clearLegacyBackgroundDataUrl();
    },

    loadLegacyBackgroundDataUrl() {
      return readStoredString(LEGACY_STORAGE_KEYS.backgroundImage, "");
    },

    clearLegacyBackgroundDataUrl() {
      safeRemoveStoredItem(LEGACY_STORAGE_KEYS.backgroundImage);
    },
  };
}

function normalizePreferences(value = {}) {
  const themeMode = ["system", "light", "dark"].includes(value.themeMode)
    ? value.themeMode
    : DEFAULT_PREFERENCES.themeMode;
  const indexTab = INDEX_TABS.has(value.indexTab) ? value.indexTab : DEFAULT_PREFERENCES.indexTab;
  const batchSize = BATCH_SIZE_OPTIONS.has(Number(value.batchSize))
    ? Number(value.batchSize)
    : DEFAULT_PREFERENCES.batchSize;

  return {
    themeMode,
    backgroundOpacity: clampNumber(
      value.backgroundOpacity,
      0,
      70,
      DEFAULT_PREFERENCES.backgroundOpacity,
    ),
    panelOpacity: clampNumber(value.panelOpacity, 45, 100, DEFAULT_PREFERENCES.panelOpacity),
    batchSize,
    hideKana: normalizeBoolean(value.hideKana, DEFAULT_PREFERENCES.hideKana),
    hideGloss: normalizeBoolean(value.hideGloss, DEFAULT_PREFERENCES.hideGloss),
    termOnlySearch: normalizeBoolean(value.termOnlySearch, DEFAULT_PREFERENCES.termOnlySearch),
    indexTab,
  };
}

function normalizeProgress(value = {}) {
  return {
    starred: uniqueValues(Array.isArray(value.starred) ? value.starred.map(String).filter(Boolean) : []),
    learned: uniqueValues(Array.isArray(value.learned) ? value.learned.map(String).filter(Boolean) : []),
  };
}

function readStoredJson(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    // Local persistence is best-effort in private or quota-limited browsers.
    return false;
  }
}

function readStoredList(key) {
  const value = readStoredJson(key);
  return Array.isArray(value) ? value : [];
}

function readStoredString(key, fallback = "") {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function safeRemoveStoredItem(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore storage access failures.
  }
}

function normalizeBoolean(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (value === "true") return true;
    if (value === "false") return false;
  }
  return fallback;
}

let lexiconDbPromise = null;

function openLexiconDb() {
  if (!("indexedDB" in window)) {
    return Promise.reject(new Error("IndexedDB is unavailable"));
  }
  if (!lexiconDbPromise) {
    lexiconDbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open("Mio", 1);
      request.addEventListener("upgradeneeded", () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("assets")) {
          db.createObjectStore("assets", { keyPath: "id" });
        }
      });
      request.addEventListener("success", () => {
        resolve(request.result);
      });
      request.addEventListener("error", () => {
        reject(request.error || new Error("Failed to open IndexedDB"));
      });
    });
  }
  return lexiconDbPromise;
}

async function idbGet(id) {
  return idbRequest("readonly", (store) => store.get(id));
}

async function idbPut(record) {
  return idbRequest("readwrite", (store) => store.put(record));
}

async function idbDelete(id) {
  return idbRequest("readwrite", (store) => store.delete(id));
}

async function idbRequest(mode, createRequest) {
  const db = await openLexiconDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("assets", mode);
    const store = transaction.objectStore("assets");
    let request;
    try {
      request = createRequest(store);
    } catch (error) {
      reject(error);
      return;
    }
    request.addEventListener("success", () => {
      resolve(request.result);
    });
    request.addEventListener("error", () => {
      reject(request.error || transaction.error || new Error("IndexedDB request failed"));
    });
    transaction.addEventListener("abort", () => {
      reject(transaction.error || new Error("IndexedDB transaction aborted"));
    });
  });
}

async function dataUrlToBlob(dataUrl) {
  const response = await fetch(dataUrl);
  return response.blob();
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error || new Error("Failed to read blob")));
    reader.readAsDataURL(blob);
  });
}

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function dateStamp() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function totalPages() {
  return Math.max(1, Math.ceil(filteredEntries.length / state.batchSize));
}

function rankValue(entry) {
  return Number.isFinite(entry.rank) ? entry.rank : 99999999 + entry.sourceIndex;
}

function orderByShuffle(entries) {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  return shuffledIds.map((id) => byId.get(id)).filter(Boolean);
}

function shuffle(values) {
  const copy = [...values];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

function normalizeSearchText(value) {
  return katakanaToHiragana(String(value || "").normalize("NFKC").toLowerCase());
}

function normalizeIndexedText(value) {
  const base = normalizeSearchText(value);
  const variants = hanVariantTerms(base);
  return variants.length ? `${base} ${variants.join(" ")}` : base;
}

function hanVariantTerms(value) {
  const terms = new Set();
  for (const match of String(value || "").matchAll(/[\u3400-\u4dbf\u4e00-\u9fff]+/g)) {
    for (const variant of hanRunVariants(match[0])) {
      if (variant && variant !== match[0]) terms.add(variant);
    }
  }
  return [...terms];
}

function hanRunVariants(run) {
  const chars = Array.from(run);
  const choices = chars.map((char) => [char, ...uniqueChars(HAN_VARIANT_MAP[char] || "")]);
  const product = choices.reduce((total, list) => total * list.length, 1);
  if (product <= HAN_RUN_COMBO_LIMIT) {
    return choices.reduce(
      (items, list) => items.flatMap((prefix) => list.map((char) => `${prefix}${char}`)),
      [""],
    );
  }

  const variants = new Set([
    chars.map((char) => (HAN_VARIANT_MAP[char] || "")[0] || char).join(""),
  ]);
  chars.forEach((char, index) => {
    for (const variant of uniqueChars(HAN_VARIANT_MAP[char] || "")) {
      const copy = [...chars];
      copy[index] = variant;
      variants.add(copy.join(""));
    }
  });
  return [...variants];
}

function uniqueChars(value) {
  return [...new Set(Array.from(value || ""))];
}

function uniqueValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function buildHanVariantMap(groups) {
  const map = Object.create(null);
  for (const group of String(groups || "").split("|")) {
    const chars = uniqueChars(group);
    if (chars.length < 2) continue;
    for (const char of chars) {
      map[char] = chars.filter((item) => item !== char).join("");
    }
  }
  return map;
}

function katakanaToHiragana(value) {
  return value.replace(/[\u30a1-\u30f6]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0x60));
}

function buildTermSearchText(entry) {
  return [buildTermWritingSearchText(entry), buildTermReadingSearchText(entry)].join(" ");
}

function buildTermWritingSearchText(entry) {
  const terms = [
    entry.word,
    ...(entry.writings || []),
    ...(entry.kanji || []),
  ].filter(Boolean);
  return normalizeIndexedText(terms.join(" "));
}

function buildTermReadingSearchText(entry) {
  const terms = [
    entry.reading,
    ...(entry.readings || []),
  ].filter(Boolean);
  const normalizedTerms = terms.map((term) => normalizeSearchText(term));
  const romanTerms = normalizedTerms.flatMap((term) => romajiSearchVariants(kanaToRomaji(term)));
  return normalizeSearchText([...normalizedTerms, ...romanTerms].join(" "));
}

function hasKanji(value) {
  return /[\u3400-\u4dbf\u4e00-\u9fff]/.test(String(value || ""));
}

function hasKana(value) {
  return /[\u3040-\u30ff]/.test(String(value || ""));
}

function kanaToRomaji(value) {
  const kana = katakanaToHiragana(String(value || "").normalize("NFKC").toLowerCase());
  let out = "";
  for (let index = 0; index < kana.length; index += 1) {
    const char = kana[index];
    const next = kana[index + 1] || "";

    if (char === "っ") {
      const nextRomaji = kanaPairToRomaji(next, kana[index + 2] || "") || kanaCharToRomaji(next);
      out += nextRomaji ? nextRomaji[0] : "";
      continue;
    }

    if (char === "ー") {
      const vowel = lastVowel(out);
      if (vowel) out += vowel;
      continue;
    }

    const pair = kanaPairToRomaji(char, next);
    if (pair) {
      out += pair;
      index += 1;
      continue;
    }

    out += kanaCharToRomaji(char) || char;
  }
  return out;
}

function kanaPairToRomaji(char, next) {
  return (
    {
      きゃ: "kya",
      きゅ: "kyu",
      きょ: "kyo",
      ぎゃ: "gya",
      ぎゅ: "gyu",
      ぎょ: "gyo",
      しゃ: "sha",
      しゅ: "shu",
      しょ: "sho",
      じゃ: "ja",
      じゅ: "ju",
      じょ: "jo",
      ちゃ: "cha",
      ちゅ: "chu",
      ちょ: "cho",
      にゃ: "nya",
      にゅ: "nyu",
      にょ: "nyo",
      ひゃ: "hya",
      ひゅ: "hyu",
      ひょ: "hyo",
      びゃ: "bya",
      びゅ: "byu",
      びょ: "byo",
      ぴゃ: "pya",
      ぴゅ: "pyu",
      ぴょ: "pyo",
      みゃ: "mya",
      みゅ: "myu",
      みょ: "myo",
      りゃ: "rya",
      りゅ: "ryu",
      りょ: "ryo",
      てぃ: "ti",
      でぃ: "di",
      とぅ: "tu",
      どぅ: "du",
      ふぁ: "fa",
      ふぃ: "fi",
      ふぇ: "fe",
      ふぉ: "fo",
      うぃ: "wi",
      うぇ: "we",
      うぉ: "wo",
      ゔぁ: "va",
      ゔぃ: "vi",
      ゔぇ: "ve",
      ゔぉ: "vo",
    }[`${char}${next}`] || ""
  );
}

function kanaCharToRomaji(char) {
  return (
    {
      あ: "a",
      い: "i",
      う: "u",
      え: "e",
      お: "o",
      か: "ka",
      き: "ki",
      く: "ku",
      け: "ke",
      こ: "ko",
      さ: "sa",
      し: "shi",
      す: "su",
      せ: "se",
      そ: "so",
      た: "ta",
      ち: "chi",
      つ: "tsu",
      て: "te",
      と: "to",
      な: "na",
      に: "ni",
      ぬ: "nu",
      ね: "ne",
      の: "no",
      は: "ha",
      ひ: "hi",
      ふ: "fu",
      へ: "he",
      ほ: "ho",
      ま: "ma",
      み: "mi",
      む: "mu",
      め: "me",
      も: "mo",
      や: "ya",
      ゆ: "yu",
      よ: "yo",
      ら: "ra",
      り: "ri",
      る: "ru",
      れ: "re",
      ろ: "ro",
      わ: "wa",
      を: "wo",
      ん: "n",
      が: "ga",
      ぎ: "gi",
      ぐ: "gu",
      げ: "ge",
      ご: "go",
      ざ: "za",
      じ: "ji",
      ず: "zu",
      ぜ: "ze",
      ぞ: "zo",
      だ: "da",
      ぢ: "ji",
      づ: "zu",
      で: "de",
      ど: "do",
      ば: "ba",
      び: "bi",
      ぶ: "bu",
      べ: "be",
      ぼ: "bo",
      ぱ: "pa",
      ぴ: "pi",
      ぷ: "pu",
      ぺ: "pe",
      ぽ: "po",
      ゔ: "vu",
      ぁ: "a",
      ぃ: "i",
      ぅ: "u",
      ぇ: "e",
      ぉ: "o",
      ゃ: "ya",
      ゅ: "yu",
      ょ: "yo",
    }[char] || ""
  );
}

function romajiSearchVariants(value) {
  const compact = String(value || "").replace(/[^a-z0-9]/g, "");
  if (!compact) return [];
  return [
    compact,
    compact.replaceAll("shi", "si").replaceAll("chi", "ti").replaceAll("tsu", "tu").replaceAll("fu", "hu"),
    compact.replace(/ou/g, "o").replace(/oo/g, "o").replace(/uu/g, "u").replace(/ei/g, "e"),
  ].filter((item, index, items) => item && items.indexOf(item) === index);
}

function buildExactSearchTerms(entry) {
  const writingTerms = exactTextTerms([entry.word, ...(entry.writings || [])], { withHanVariants: true });
  const kanjiTerms = exactTextTerms(entry.kanji || [], { withHanVariants: true });
  const readingTerms = exactTextTerms([entry.reading, ...(entry.readings || [])], { withHanVariants: false });
  const romajiTerms = uniqueValues(
    readingTerms.flatMap((term) => romajiSearchVariants(kanaToRomaji(term)).map((item) => normalizeSearchText(item))),
  );
  return {
    exactWritingTerms: writingTerms,
    exactKanjiTerms: kanjiTerms,
    exactReadingTerms: readingTerms,
    exactRomajiTerms: romajiTerms,
  };
}

function exactTextTerms(values, options = {}) {
  const terms = new Set();
  for (const value of values) {
    const normalized = normalizeSearchText(value).trim();
    if (!normalized) continue;
    terms.add(normalized);
    if (options.withHanVariants && hasKanji(normalized)) {
      for (const variant of hanRunVariants(normalized)) {
        if (variant) terms.add(variant);
      }
    }
  }
  return [...terms];
}

function lastVowel(value) {
  const match = String(value || "").match(/[aeiou](?!.*[aeiou])/);
  return match ? match[0] : "";
}

function joinList(value) {
  return Array.isArray(value) && value.length ? value.join("；") : "-";
}

function joinDefinitionItems(value) {
  return Array.isArray(value) ? value.filter(Boolean).join("；") : "";
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
