const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const state = {
  manifest: null,
  season: null,
  logs: null,
  day: null,
  view: "board",
  date: null,
  query: "",
  team: "",
  sort: "pts",
  minimum: 5,
  playerId: "",
  openKey: "",
  showAll: false,
  chart: "",
  stars: 0,
  scrollChart: false,
  folded: {},
  liveDays: {},
  checking: false,
  playerIndex: null,
  lookups: null,
};

const CHART_CODES = new Set(["pts", "reb", "ast", "fg3m", "pra", "stl", "blk", "dd", "first"]);
const STAR_CODES = new Set(["pts", "reb", "ast", "fg3m", "pra", "stl", "blk"]);

const app = document.querySelector("#app");
const tools = document.querySelector("#tools");
const dates = document.querySelector("#dates");

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => visit(button.dataset.view));
});
document.querySelector("#theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("propcomp-theme", next);
  paintThemeButton();
  if (state.view === "player" && state.logs && state.season) paintPlayer();
  else if (state.view === "board" && state.day) paintBoard();
});
document.querySelector("#copy").addEventListener("click", () => copyLink());
window.addEventListener("popstate", queueRestore);
window.addEventListener("hashchange", queueRestore);
paintThemeButton();

boot().catch((error) => {
  app.textContent = `The board could not load. ${error.message}`;
});

let restoring = false;
let restoreFrame = 0;

function queueRestore() {
  cancelAnimationFrame(restoreFrame);
  restoreFrame = requestAnimationFrame(() => {
    restore().catch((error) => {
      app.textContent = `The board could not load. ${error.message}`;
    });
  });
}

function paintThemeButton() {
  const button = document.querySelector("#theme");
  const dark = document.documentElement.dataset.theme !== "light";
  button.textContent = dark ? "Light" : "Dark";
  button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
}

async function copyLink() {
  const button = document.querySelector("#copy");
  try {
    await navigator.clipboard.writeText(location.href);
    button.textContent = "Copied";
  } catch (error) {
    button.textContent = "Copy the address";
  }
  setTimeout(() => {
    button.textContent = "Copy link";
  }, 1200);
}

async function boot() {
  state.manifest = await fetchJson("data/manifest.json");
  readPlace();
  if (!state.date) {
    const today = state.manifest.today || "";
    const upcoming = state.manifest.dates.find((item) => item.date >= today && item.games);
    state.date = (upcoming || state.manifest.dates[state.manifest.dates.length - 1]).date;
  }
  history.replaceState({ propcomp: true }, "", place());
  state.checking = true;
  const refreshed = refreshOpenSlates();
  paintChrome();
  await setView(state.view);
  refreshed.catch(() => {});
}

function knownDate(date) {
  return state.manifest.dates.some((item) => item.date === date);
}

function readPlace() {
  const raw = location.hash.replace(/^#/, "");
  if (!raw) {
    state.view = "board";
    state.chart = "";
    return;
  }
  if (raw.startsWith("/")) {
    readPath(raw);
    return;
  }
  const params = new URLSearchParams(raw);
  const requested = params.get("d");
  if (knownDate(requested)) state.date = requested;
  const view = params.get("v");
  state.view = view === "season" || view === "player" ? view : "board";
  state.playerId = params.get("p") || "";
  state.chart = CHART_CODES.has(params.get("c")) ? params.get("c") : "";
  readFilters(params);
  state.scrollChart = Boolean(state.chart);
}

function readPath(raw) {
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  const head = parts[0];
  state.chart = "";
  if (head === "season") {
    state.view = "season";
  } else if (head === "player") {
    state.view = "player";
    state.playerId = parts[1] || "";
    state.chart = CHART_CODES.has(parts[2]) ? parts[2] : "";
  } else {
    state.view = "board";
    if (knownDate(parts[1])) state.date = parts[1];
  }
  readFilters(params);
  state.scrollChart = Boolean(state.chart);
}

function readFilters(params) {
  state.query = params.get("q") || "";
  state.team = params.get("team") || "";
  const stars = Number(params.get("stars"));
  state.stars = stars === 1 || stars === 2 || stars === 3 ? stars : 0;
  if (params.get("sort")) state.sort = params.get("sort");
  if (params.get("min")) state.minimum = Number(params.get("min")) || state.minimum;
}

function place() {
  const params = new URLSearchParams();
  if (state.view !== "player") {
    if (state.query) params.set("q", state.query);
    if (state.team) params.set("team", state.team);
  }
  if (state.view === "board" && state.stars) params.set("stars", String(state.stars));
  if (state.view === "season") {
    if (state.sort && state.sort !== "pts") params.set("sort", state.sort);
    if (state.minimum !== 5) params.set("min", String(state.minimum));
  }
  let path = "/board";
  if (state.view === "season") path = "/season";
  else if (state.view === "player") {
    path = state.playerId ? `/player/${state.playerId}` : "/player";
    if (state.playerId && state.chart) path += `/${state.chart}`;
  } else if (state.date) path = `/board/${state.date}`;
  const query = params.toString();
  return `#${path}${query ? `?${query}` : ""}`;
}

function remember(replace) {
  if (restoring) return;
  const next = place();
  if (next === location.hash) return;
  const data = { propcomp: true };
  if (replace) history.replaceState(data, "", next);
  else history.pushState(data, "", next);
}

async function restore() {
  if (!state.manifest) return;
  restoring = true;
  readPlace();
  paintChrome();
  await setView(state.view);
  restoring = false;
}

async function visit(view) {
  state.view = view;
  remember();
  await setView(view);
}

async function setView(view) {
  state.view = view;
  document.querySelectorAll("#tabs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.view === view);
  });
  dates.hidden = view === "season" || view === "player";
  if (view === "board") await showBoard();
  if (view === "season") await showSeason();
  if (view === "player") await showPlayer();
}

function paintChrome() {
  document.querySelector("#title").textContent = `${state.manifest.season} player props`;
  paintMeta();
  document.querySelector("#foot").textContent = `${state.manifest.source}. The two prices on a total are the two sides of the number. ESPN does not label which one is the over. Players who did not play are void. Past slates stay on this site. Opening the board checks today and the next two days, then fills any lines posted since the last publish.`;
  dates.replaceChildren();
  state.manifest.dates.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = shortDate(item.date);
    button.title = `${item.games} game${item.games === 1 ? "" : "s"}`;
    button.classList.toggle("on", item.date === state.date);
    if (item.scheduled) button.classList.add("soon");
    button.addEventListener("click", () => selectDate(item.date));
    dates.appendChild(button);
  });
  const current = dates.querySelector(".on");
  if (current) current.scrollIntoView({inline: "center", block: "nearest"});
}

async function selectDate(date) {
  state.date = date;
  state.openKey = "";
  state.view = "board";
  remember();
  paintChrome();
  await setView("board");
}

async function showBoard() {
  tools.replaceChildren();
  tools.append(
    labeled("Player", input(state.query, "Search a player", (value) => {
      state.query = value;
      remember(true);
      paintBoard();
    })),
    labeled("Team", teamSelect()),
    labeled("Stars", select([["0", "Any"], ["1", "1+"], ["2", "2+"], ["3", "3+"]], String(state.stars || 0), (value) => {
      state.stars = Number(value);
      remember();
      paintBoard();
    }), "wide"),
    toggle("Show every line", state.showAll, (checked) => {
      state.showAll = checked;
      paintBoard();
    }),
  );
  app.textContent = "Loading this slate.";
  const date = state.date;
  const logsPromise = state.logs ? Promise.resolve(state.logs) : fetchJson("data/logs.json");
  const loaded = state.liveDays[date] || await fetchJson(`data/days/${date}.json`);
  const logs = await logsPromise;
  if (state.date !== date || state.view !== "board") return;
  state.logs = logs;
  if (!state.liveDays[date]) state.liveDays[date] = loaded;
  state.day = state.liveDays[date];
  paintBoard();
}

function paintBoard() {
  const core = state.manifest.core;
  const coreCodes = new Set(core.map((market) => market.code));
  app.replaceChildren();
  const games = (state.day && state.day.games) || [];
  paintMeta();
  if (!games.length) {
    app.textContent = "No games on this slate.";
    return;
  }
  const folded = foldedSet();
  const bar = document.createElement("div");
  bar.className = "slate-bar";
  const heading = document.createElement("h2");
  heading.textContent = longDate(state.date);
  const count = document.createElement("p");
  count.className = "slate-count";
  count.textContent = `${games.length} game${games.length === 1 ? "" : "s"}`;
  const actions = document.createElement("div");
  actions.className = "slate-actions";
  actions.append(
    textButton("Collapse all", () => foldGames(games, true)),
    textButton("Expand all", () => foldGames(games, false)),
  );
  bar.append(heading, count, actions);
  const key = document.createElement("p");
  key.className = "keyline";
  key.textContent = "Starters first. Red is out, amber is at risk. A star clears every gate. A filled U is a strong under: minutes have been short for more than one game and the number is still up, or a rebound or steal number is at least a point above the recent average after a single short night. One short night does not mark points, PRA, threes, or assists. A ring U is a lean. A filled O has cleared 80% with the median over the number. Hover a mark for the reason.";
  app.append(bar, key);
  if (state.day && state.day.card) app.append(formulaCard(state.day.card));
  let visible = 0;
  games.forEach((game) => {
    const rows = game.rows.filter((row) => matches(row));
    if (!rows.length && (state.query || state.team || state.stars)) return;
    visible += 1;
    const open = !folded.has(game.id);
    const article = document.createElement("article");
    article.className = open ? "game" : "game shut";
    const toggleRow = document.createElement("button");
    toggleRow.type = "button";
    toggleRow.className = "game-toggle";
    toggleRow.setAttribute("aria-expanded", open ? "true" : "false");
    const title = document.createElement("h2");
    title.textContent = `${game.away} at ${game.home}`;
    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = gameMeta(game);
    const titles = document.createElement("span");
    titles.className = "game-titles";
    titles.append(title, meta);
    toggleRow.append(titles);
    toggleRow.addEventListener("click", () => {
      if (folded.has(game.id)) folded.delete(game.id);
      else folded.add(game.id);
      paintBoard();
    });
    const body = document.createElement("div");
    body.className = "game-body";
    body.hidden = !open;
    article.append(toggleRow, body);
    if (!gameHasLines(game)) {
      const empty = document.createElement("p");
      empty.textContent = lineStatus(game);
      body.append(empty);
      if (!game.rows.length) {
        app.append(article);
        return;
      }
    }
    const table = document.createElement("table");
    const head = document.createElement("tr");
    addCell(head, "th", "Player").classList.add("sticky");
    core.forEach((market) => addCell(head, "th", market.label));
    const thead = document.createElement("thead");
    thead.append(head);
    const tbody = document.createElement("tbody");
    const ordered = (rows.length ? rows : game.rows).slice().sort((left, right) => {
      if (game.status === "final" || game.status === "live") return 0;
      return orderKey(left, game) - orderKey(right, game) || left.name.localeCompare(right.name);
    });
    ordered.forEach((row) => {
      const tr = document.createElement("tr");
      if (row.avail === "out") tr.classList.add("out");
      if (row.avail === "risk") tr.classList.add("risk");
      const name = addCell(tr, "td", "");
      name.classList.add("name");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${row.team} ${row.name}`;
      button.addEventListener("click", () => openPlayer(row.id));
      if (game.status !== "final" && row.role === "starter") addTag(button, "START", "start");
      if (row.avail === "out") addTag(button, "OUT", "out", row.avail_note);
      if (row.avail === "risk") addTag(button, row.avail_label || "RISK", "risk", row.avail_note);
      name.append(button);
      const indexed = indexMain(row.props);
      core.forEach((market) => {
        const prop = indexed.get(market.code);
        fillCell(addCell(tr, "td", ""), prop, starReason(row, prop), prop && prop.lean);
      });
      const extras = row.props.filter((prop) => prop.k === "milestone" || !coreCodes.has(prop.c));
      const key = `${game.id}:${row.id}`;
      if (extras.length) {
        tr.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;
          state.openKey = state.openKey === key ? "" : key;
          if (!state.showAll) paintBoard();
        });
      }
      tbody.append(tr);
      if (extras.length && (state.showAll || state.openKey === key)) {
        const extraRow = document.createElement("tr");
        const cell = addCell(extraRow, "td", "");
        cell.colSpan = core.length + 1;
        cell.append(extraGrid(extras));
        tbody.append(extraRow);
      }
    });
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.append(thead, tbody);
    wrap.append(table);
    body.append(wrap);
    app.append(article);
  });
  if (!visible) {
    const empty = document.createElement("p");
    empty.textContent = "No players match that filter.";
    app.append(empty);
  }
}

async function showSeason() {
  tools.replaceChildren();
  if (!state.season) {
    app.textContent = "Loading the season map.";
    state.season = await fetchJson("data/season.json");
  }
  const markets = state.manifest.core.filter((market) => ["dd", "first"].indexOf(market.code) === -1);
  tools.append(
    labeled("Player", input(state.query, "Search a player", (value) => {
      state.query = value;
      remember(true);
      paintSeason();
    })),
    labeled("Team", teamSelect()),
    labeled("Sort", select(markets.map((market) => [market.code, market.label]), state.sort, (value) => {
      state.sort = value;
      remember();
      paintSeason();
    })),
    labeled("Min games", select([["1", "1"], ["3", "3"], ["5", "5"], ["8", "8"]], String(state.minimum), (value) => {
      state.minimum = Number(value);
      remember();
      paintSeason();
    })),
  );
  paintSeason();
}

function paintSeason() {
  paintMeta();
  const columns = state.manifest.core;
  const players = state.season.players.filter((player) => {
    if (state.team && player.team !== state.team) return false;
    if (state.query && !player.name.toLowerCase().includes(state.query.toLowerCase())) return false;
    return sampleSize(player, state.sort) >= state.minimum || state.query;
  });
  players.sort((left, right) => {
    const delta = rateOf(right, state.sort) - rateOf(left, state.sort);
    if (delta) return delta;
    return right.name < left.name ? 1 : -1;
  });
  app.replaceChildren();
  const league = document.createElement("section");
  league.className = "panel";
  const heading = document.createElement("h2");
  heading.textContent = "League hit rate on the main number";
  league.append(heading, leagueBars());
  const wrap = document.createElement("div");
  wrap.className = "table-wrap panel";
  const table = document.createElement("table");
  table.className = "heat";
  const head = document.createElement("tr");
  addCell(head, "th", "Player").classList.add("sticky");
  columns.forEach((market) => addCell(head, "th", market.label));
  const thead = document.createElement("thead");
  thead.append(head);
  const tbody = document.createElement("tbody");
  players.forEach((player) => {
    const tr = document.createElement("tr");
    const name = addCell(tr, "td", "");
    name.classList.add("name");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${player.team} ${player.name}`;
    button.addEventListener("click", () => openPlayer(player.id));
    name.append(button);
    columns.forEach((market) => {
      const cell = addCell(tr, "td", recordText(player.markets[market.code], market.code));
      const tone = heatTone(player.markets[market.code], market.code);
      if (tone) {
        cell.style.background = tone;
        cell.style.color = "#10141c";
      }
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  app.append(league, wrap);
}

async function showPlayer() {
  tools.replaceChildren();
  if (!state.logs) {
    app.textContent = "Loading player logs.";
    state.logs = await fetchJson("data/logs.json");
  }
  if (!state.season) state.season = await fetchJson("data/season.json");
  const people = state.season.players.slice().sort((left, right) => left.name.localeCompare(right.name));
  tools.append(labeled("Player", select(people.map((player) => [player.id, `${player.team} ${player.name}`]), state.playerId, (value) => {
    state.playerId = value;
    state.chart = "";
    remember();
    paintPlayer();
  })));
  await loadLineDays();
  if (state.view !== "player") return;
  paintPlayer();
}

function paintPlayer() {
  app.replaceChildren();
  paintMeta();
  if (!state.playerId) {
    app.textContent = "Pick a player to see every main line against the result.";
    return;
  }
  const person = (state.season.players || []).find((player) => player.id === state.playerId);
  const log = state.logs[state.playerId] || {};
  const title = document.createElement("h2");
  title.textContent = person ? `${person.team} ${person.name}` : "Player";
  const charts = document.createElement("div");
  charts.className = "charts";
  app.append(title, charts);
  state.manifest.core.forEach((market) => {
    const series = log[market.code] || [];
    const upcoming = openLine(state.playerId, market.code, series);
    if (!series.length && !upcoming) return;
    const card = document.createElement("section");
    card.className = "panel chart-card";
    card.id = `chart-${market.code}`;
    if (state.chart === market.code) card.classList.add("on");
    const heading = document.createElement("h3");
    const counts = person && person.markets[market.code];
    const trend = trailingAverage(series, market.code);
    const link = document.createElement("a");
    link.href = `#/player/${state.playerId}/${market.code}`;
    link.textContent = `${market.label} ${recordText(counts, market.code)}`.trim();
    heading.append(link);
    card.append(heading);
    if (trend || upcoming) {
      const note = document.createElement("p");
      note.className = "trend";
      const parts = [];
      if (trend) {
        parts.push(market.code === "dd" || market.code === "first"
          ? `Last ${trend.n}: ${trend.hits} hit`
          : `Last ${trend.n} average ${trend.avg.toFixed(1)}`);
      }
      if (upcoming) parts.push(`${shortDate(upcoming.date)} line ${formatNumber(upcoming.line)}`);
      note.textContent = parts.join(" · ");
      card.append(note);
    }
    const readout = document.createElement("p");
    readout.className = "hover-readout";
    readout.textContent = upcoming
      ? `${shortDate(upcoming.date)} line ${formatNumber(upcoming.line)} is the open point on the right.`
      : "Hover a point to see the value.";
    if (market.code !== "dd" && market.code !== "first" && (series.length || upcoming)) {
      card.append(lineChart(series, trend ? trend.avg : null, readout, upcoming));
    }
    card.append(readout, resultStrip(series, market.code, upcoming));
    charts.append(card);
  });
  if (!charts.querySelector(".panel")) {
    const empty = document.createElement("p");
    empty.textContent = "No graded main lines yet.";
    app.append(empty);
  }
  if (state.scrollChart && state.chart) {
    state.scrollChart = false;
    requestAnimationFrame(() => {
      const node = app.querySelector(".chart-card.on");
      if (node) node.scrollIntoView({ block: "start" });
    });
  }
}

function lineChart(series, average, readout, upcoming) {
  const values = [];
  series.forEach((row) => {
    const line = Number(row[1]);
    const actual = Number(row[3]);
    if (Number.isFinite(line)) values.push(line);
    if (Number.isFinite(actual)) values.push(actual);
  });
  if (Number.isFinite(average)) values.push(average);
  if (upcoming) values.push(upcoming.line);
  const svg = svgEl("svg");
  svg.classList.add("chart");
  svg.setAttribute("viewBox", "0 0 640 140");
  const count = series.length + (upcoming ? 1 : 0);
  if (values.length < 2 || count < 1) return svg;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const width = 640;
  const height = 140;
  const step = count === 1 ? 0 : (width - 24) / (count - 1);
  const yFor = (value) => {
    if (high === low) return height / 2;
    return height - 16 - ((value - low) / (high - low)) * (height - 32);
  };
  const line = [];
  const actual = [];
  const dots = [];
  series.forEach((row, index) => {
    const x = 12 + index * step;
    if (row[1] !== null && row[1] !== "") {
      const y = yFor(Number(row[1]));
      line.push(`${x},${y}`);
      dots.push(dot(x, y, paintColor("--accent"), `${shortDate(row[0])} line ${row[1]}`, readout));
    }
    if (row[3] !== null && row[3] !== undefined) {
      const y = yFor(Number(row[3]));
      actual.push(`${x},${y}`);
      dots.push(dot(x, y, paintColor("--ink"), `${shortDate(row[0])} actual ${row[3]}, line ${row[1]}`, readout));
    }
  });
  if (upcoming) {
    const x = 12 + series.length * step;
    const y = yFor(upcoming.line);
    line.push(`${x},${y}`);
    const ring = svgEl("circle");
    ring.setAttribute("cx", x);
    ring.setAttribute("cy", y);
    ring.setAttribute("r", "7");
    ring.setAttribute("fill", paintColor("--surface"));
    ring.setAttribute("stroke", paintColor("--accent"));
    ring.setAttribute("stroke-width", "2");
    const label = `${shortDate(upcoming.date)} line ${formatNumber(upcoming.line)}, not played`;
    dots.push(ring);
    dots.push(dot(x, y, paintColor("--accent"), label, readout));
  }
  svg.append(poly(line.join(" "), paintColor("--accent"), "4 4"), poly(actual.join(" "), paintColor("--ink"), ""));
  if (Number.isFinite(average)) {
    const guide = svgEl("line");
    const y = yFor(average);
    guide.setAttribute("x1", "8");
    guide.setAttribute("x2", String(width - 8));
    guide.setAttribute("y1", y);
    guide.setAttribute("y2", y);
    guide.setAttribute("stroke", paintColor("--muted"));
    guide.setAttribute("stroke-dasharray", "3 4");
    svg.append(guide);
  }
  dots.forEach((node) => svg.append(node));
  return svg;
}

function trailingAverage(series, code) {
  const sample = [];
  for (let index = series.length - 1; index >= 0 && sample.length < 5; index -= 1) {
    const row = series[index];
    if (code === "dd" || code === "first") sample.push(row[1] === "y" ? 1 : 0);
    else if (row[3] !== null && row[3] !== undefined && row[3] !== "") sample.push(Number(row[3]));
  }
  const finite = sample.filter((value) => Number.isFinite(value));
  if (finite.length < 3) return null;
  const total = finite.reduce((sum, value) => sum + value, 0);
  return { avg: total / finite.length, n: finite.length, hits: total };
}

function resultStrip(series, code, upcoming) {
  const strip = document.createElement("div");
  strip.className = "strip";
  series.forEach((row) => {
    const button = document.createElement("button");
    button.type = "button";
    const mark = code === "dd" || code === "first" ? row[1] : row[4];
    button.textContent = shortDate(row[0]).split(" ")[1];
    button.classList.add(mark === "o" || mark === "y" ? "hit" : "miss");
    button.title = code === "dd" || code === "first" ? `${row[0]} ${mark}` : `${row[0]} line ${row[1]} actual ${row[3]}`;
    button.addEventListener("click", () => selectDate(row[0]));
    strip.append(button);
  });
  if (upcoming) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "open-line";
    button.textContent = shortDate(upcoming.date).split(" ")[1];
    button.title = `${upcoming.date} line ${formatNumber(upcoming.line)}, not played`;
    button.addEventListener("click", () => selectDate(upcoming.date));
    strip.append(button);
  }
  return strip;
}

function lineDates() {
  const today = easternToday();
  const dates = [];
  if (state.date && knownDate(state.date)) dates.push(state.date);
  for (let offset = 0; offset < 3; offset += 1) {
    const date = addDays(today, offset);
    if (knownDate(date) && !dates.includes(date)) dates.push(date);
  }
  return dates;
}

async function loadLineDays() {
  await Promise.all(lineDates().map(async (date) => {
    if (state.liveDays[date]) return;
    try {
      state.liveDays[date] = await fetchJson(`data/days/${date}.json`);
    } catch (error) {
      return error;
    }
  }));
}

function openLine(playerId, code, series) {
  if (code === "dd" || code === "first") return null;
  const played = new Set((series || []).map((row) => row[0]));
  for (const date of lineDates()) {
    if (played.has(date)) continue;
    const day = state.liveDays[date];
    if (!day) continue;
    for (const game of day.games || []) {
      if (game.status === "final") continue;
      const row = (game.rows || []).find((item) => String(item.id) === String(playerId));
      if (!row) continue;
      const prop = (row.props || []).find((item) => item.c === code && item.k !== "milestone" && item.line !== "");
      const line = prop ? Number(prop.line) : NaN;
      if (!Number.isFinite(line)) continue;
      return { date, line, matchup: `${game.away} at ${game.home}` };
    }
  }
  return null;
}

function leagueBars() {
  const wrap = document.createElement("div");
  wrap.className = "bars";
  state.manifest.core.forEach((market) => {
    const counts = (state.season.league && state.season.league[market.code]) || {};
    const row = document.createElement("div");
    row.className = "bar-row";
    const label = document.createElement("span");
    label.textContent = market.label;
    const track = document.createElement("span");
    track.className = "track";
    const fill = document.createElement("span");
    fill.className = "fill";
    const yesMode = market.code === "dd" || market.code === "first";
    const hits = yesMode ? counts.y || 0 : counts.o || 0;
    const misses = yesMode ? counts.n || 0 : counts.u || 0;
    const sample = hits + misses;
    const width = sample ? Math.round((100 * hits) / sample) : 0;
    fill.style.width = `${width}%`;
    track.append(fill);
    const record = document.createElement("span");
    record.textContent = sample ? `${width}%  ${hits}-${misses}` : "n/a";
    row.append(label, track, record);
    wrap.append(row);
  });
  return wrap;
}

function extraGrid(props) {
  const grid = document.createElement("div");
  grid.className = "extra";
  props.forEach((prop) => {
    const chip = document.createElement("div");
    chip.className = `chip ${tone(prop.r)}`;
    const title = document.createElement("b");
    title.textContent = `${prop.m} ${prop.line || ""}`.trim();
    const detail = document.createElement("div");
    const actual = prop.act == null ? "" : `actual ${prop.act} `;
    detail.textContent = `${actual}${word(prop.r)} ${priceText(prop)}`.trim();
    chip.append(title, detail);
    if (prop.open) {
      const small = document.createElement("small");
      small.textContent = `opened at ${prop.open}`;
      chip.append(small);
    }
    grid.append(chip);
  });
  return grid;
}

function fillCell(cell, prop, reason, lean) {
  if (!prop) return cell;
  cell.classList.add("stat", tone(prop.r));
  const strong = document.createElement("strong");
  const em = document.createElement("em");
  if (prop.r === "void") {
    strong.textContent = "void";
    em.textContent = prop.line || "";
  } else if (prop.k === "yesno") {
    strong.textContent = prop.r === "pending" || prop.r === "ungraded" ? (prop.a || "yes") : prop.r;
    em.textContent = prop.r === "pending" || prop.r === "ungraded" ? "yes" : "";
  } else if (prop.act != null && prop.r !== "pending") {
    strong.textContent = String(prop.act);
    em.textContent = `${word(prop.r)} ${prop.line || ""}`.trim();
  } else {
    strong.textContent = prop.line || "";
    em.textContent = "";
  }
  const value = document.createElement("span");
  value.className = "num";
  value.textContent = strong.textContent;
  strong.textContent = "";
  strong.append(value);
  const call = callMark(prop);
  if (call) strong.append(call);
  cell.append(strong, em);
  if (lean) cell.append(makeMark("lean", "↑", lean));
  if (reason) cell.append(makeMark("star", "★", reason));
  if (prop.open) {
    const small = document.createElement("small");
    small.textContent = `opened at ${prop.open}`;
    cell.append(small);
  }
  const because = reason || "";
  cell.title = `${prop.m} ${prop.line || ""} ${priceText(prop)} ${because}`.trim();
  return cell;
}

function indexMain(props) {
  const indexed = new Map();
  props.forEach((prop) => {
    if (prop.k === "milestone") return;
    if (!indexed.has(prop.c)) indexed.set(prop.c, prop);
  });
  return indexed;
}

function orderKey(row, game) {
  const side = row.team === game.away ? 0 : row.team === game.home ? 1 : 2;
  const role = { starter: 0, rotation: 1 }[row.role];
  const roleRank = role === undefined ? 2 : role;
  const rank = row.rank == null ? 90 : row.rank;
  if (row.avail === "out") return 3000 + side * 100 + roleRank * 10 + rank;
  return side * 1000 + roleRank * 100 + rank;
}

function makeMark(className, text, reason) {
  const star = document.createElement("span");
  star.className = className;
  star.textContent = text;
  star.addEventListener("pointerenter", () => showTip(star, reason));
  star.addEventListener("pointerleave", hideTip);
  star.addEventListener("click", (event) => event.stopPropagation());
  return star;
}

let tipNode;

function showTip(anchor, text) {
  if (!tipNode) {
    tipNode = document.createElement("div");
    tipNode.className = "tip";
    tipNode.hidden = true;
    document.body.append(tipNode);
  }
  tipNode.textContent = text;
  tipNode.hidden = false;
  const box = anchor.getBoundingClientRect();
  const width = Math.min(340, window.innerWidth - 16);
  let left = box.left;
  if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
  if (left < 8) left = 8;
  tipNode.style.width = `${width}px`;
  tipNode.style.left = `${left}px`;
  tipNode.style.top = `${box.bottom + 6}px`;
  const tipBox = tipNode.getBoundingClientRect();
  if (tipBox.bottom > window.innerHeight - 8) {
    tipNode.style.top = `${Math.max(8, box.top - tipBox.height - 6)}px`;
  }
}

function hideTip() {
  if (tipNode) tipNode.hidden = true;
}

function addTag(parent, text, kind, title) {
  const tag = document.createElement("span");
  tag.className = `tag ${kind}`;
  tag.textContent = text;
  if (title) tag.title = title;
  parent.append(tag);
}

function matches(row) {
  if (state.team && row.team !== state.team) return false;
  if (state.query && !row.name.toLowerCase().includes(state.query.toLowerCase())) return false;
  if (state.stars && rowStarCount(row) < state.stars) return false;
  return true;
}

function gameMeta(game) {
  const score = game.status === "final" || game.status === "live"
    ? `${game.away} ${game.away_score}, ${game.home} ${game.home_score} ${game.status}`
    : tipLabel(game.tip);
  const spread = game.spread || "";
  const total = game.total ? `total ${game.total}` : "";
  return [score, spread, total].filter(Boolean).join("  ·  ");
}

function teamSelect() {
  const options = [["", "All teams"]].concat(
    state.manifest.teams.map((team) => [team.abbr, team.abbr]),
  );
  return select(options, state.team, (value) => {
    state.team = value;
    remember();
    if (state.view === "board") paintBoard();
    if (state.view === "season") paintSeason();
  });
}

function openPlayer(playerId) {
  state.playerId = playerId;
  state.chart = "";
  visit("player");
}

function sampleSize(player, code) {
  const counts = (player.markets && player.markets[code]) || {};
  if (code === "dd" || code === "first") return (counts.y || 0) + (counts.n || 0);
  return (counts.o || 0) + (counts.u || 0) + (counts.p || 0);
}

function rateOf(player, code) {
  const counts = (player.markets && player.markets[code]) || {};
  if (code === "dd" || code === "first") {
    const sample = (counts.y || 0) + (counts.n || 0);
    return sample ? counts.y / sample : -1;
  }
  const sample = (counts.o || 0) + (counts.u || 0);
  return sample ? counts.o / sample : -1;
}

function recordText(counts, code) {
  if (!counts) return "";
  if (code === "dd" || code === "first") {
    const sample = (counts.y || 0) + (counts.n || 0);
    return sample ? `${counts.y}-${counts.n}` : "";
  }
  const sample = (counts.o || 0) + (counts.u || 0) + (counts.p || 0);
  if (!sample) return "";
  return counts.p ? `${counts.o}-${counts.u}-${counts.p}` : `${counts.o}-${counts.u}`;
}

function heatTone(counts, code) {
  if (!counts) return "";
  const hits = code === "dd" || code === "first" ? counts.y || 0 : counts.o || 0;
  const misses = code === "dd" || code === "first" ? counts.n || 0 : counts.u || 0;
  const sample = hits + misses;
  if (sample < 3) return "";
  const rate = hits / sample;
  const red = [232, 92, 108];
  const green = [61, 196, 132];
  const mix = red.map((channel, index) => Math.round(channel + (green[index] - channel) * rate));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}

function tone(result) {
  if (result === "over" || result === "yes") return "hit";
  if (result === "under" || result === "no") return "miss";
  if (result === "push") return "push";
  if (result === "void") return "void";
  return "wait";
}

function word(result) {
  return {
    over: "over",
    under: "under",
    push: "push",
    yes: "yes",
    no: "no",
    void: "void",
    pending: "open",
    ungraded: "open",
  }[result] || "";
}

function priceText(prop) {
  if (!prop) return "";
  return [prop.a, prop.b].filter(Boolean).join(" / ");
}

function tipLabel(iso) {
  if (!iso) return "time tba";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(iso));
}

function paintMeta() {
  const counts = state.manifest.counts;
  let slate = "";
  if (state.view === "board" && state.day && state.day.games) {
    const total = state.day.games.length;
    slate = `${longDate(state.date)} · ${total} game${total === 1 ? "" : "s"} · `;
    document.title = `${longDate(state.date)} · ${total} games · Prop Comp`;
  } else if (state.view === "player" && state.playerId) {
    const person = state.season && (state.season.players || []).find((player) => player.id === state.playerId);
    const name = person ? person.name : "Player";
    const chart = state.chart ? ` · ${state.chart.toUpperCase()}` : "";
    document.title = `${name}${chart} · Prop Comp`;
  } else if (state.view === "season") {
    document.title = "Season · Prop Comp";
  } else {
    document.title = "Prop Comp";
  }
  document.querySelector("#meta").textContent = `${slate}${counts.final} finals · ${counts.props} props · updated ${stamp(state.manifest.generated_at)}`;
}

function longDate(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

function foldedSet() {
  if (!state.folded[state.date]) state.folded[state.date] = new Set();
  return state.folded[state.date];
}

function foldGames(games, shut) {
  const folded = foldedSet();
  folded.clear();
  if (shut) games.forEach((game) => folded.add(game.id));
  paintBoard();
}

function textButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function paintColor(token) {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

function rowStarCount(row) {
  const indexed = indexMain(row.props || []);
  let count = 0;
  STAR_CODES.forEach((code) => {
    if (starReason(row, indexed.get(code))) count += 1;
  });
  return count;
}

function callMark(prop) {
  const call = prop && prop.call;
  if (!call || !call.s) return null;
  const side = call.s === "U" ? "under" : "over";
  const strength = call.k === "strong" ? "strong" : "lean";
  return makeMark(`call ${side} ${strength}`, call.s, call.why || "");
}

function starReason(row, prop) {
  if (!row || row.avail === "out" || !prop || prop.k === "milestone") return "";
  const why = prop.why;
  if (!why || !why.length) return "";
  return Array.isArray(why) ? why.join(" ") : String(why);
}

function formulaCard(card) {
  const section = document.createElement("details");
  section.className = "panel card-block";
  section.open = (state.day.games || []).some((game) => game.status !== "final");
  const summary = document.createElement("summary");
  summary.textContent = card.summary || "Formula card";
  section.append(summary);
  const note = document.createElement("p");
  note.className = "card-note";
  note.textContent = "Calls are sorted strongest first. A star needs five prior games, an 80% clear rate, the last five median over the number, a cushion under 3.5, and a number that has not risen by a point. A filled O is that same strict profile and has cashed 59% of the time. A filled U needs the minutes short on more than one of the last three games, with the number still up. A rebound or steal can still be a strong under after one short night when the number is at least a point above the recent average. One short night does not mark points, PRA, threes, or assists. A half-point gap, a moved number, or a single spike does not get a mark. The arrow is a minute ramp. The ceiling is the pregame role and does not star the over.";
  section.append(note);
  if ((card.calls || []).length) {
    section.append(cardTable(
      "Path calls",
      card.calls,
      ["Player", "Game", "Market", "Line", "Call", "Why"],
      (item) => [
        `${item.team} ${item.name}`,
        item.game,
        item.label,
        item.line,
        item.side === "U" ? "Under" : "Over",
        item.why,
      ],
    ));
  }
  section.append(cardTable(
    "Clear stars",
    card.stars || [],
    ["Player", "Game", "Market", "Cap", "Last 5", "Median", "Clear", "Posted", "Status"],
    (item) => [
      `${item.team} ${item.name}`,
      item.game,
      item.label,
      formatNumber(item.cap),
      formatNumber(item.avg),
      formatNumber(item.median),
      `${Math.round(item.rate * 100)}%`,
      item.posted == null ? "waiting" : formatNumber(item.posted),
      item.note || "",
    ],
  ));
  if ((card.pauses || []).length) {
    section.append(cardTable(
      "Points paused",
      card.pauses,
      ["Player", "Game", "Why"],
      (item) => [`${item.team} ${item.name}`, item.game, item.detail],
    ));
  }
  if ((card.ramps || []).length) {
    section.append(cardTable(
      "Minute ramps",
      card.ramps,
      ["Player", "Game", "Lean"],
      (item) => [`${item.team} ${item.name}`, item.game, item.detail],
    ));
  }
  if ((card.ceilings || []).length) {
    section.append(cardTable(
      "Pregame ceiling",
      card.ceilings,
      ["Player", "Game", "Score", "Inputs"],
      (item) => [`${item.team} ${item.name}`, item.game, formatNumber(item.score), item.detail],
    ));
  }
  if ((card.held || []).length) {
    section.append(cardTable(
      "Held for the spread",
      card.held,
      ["Player", "Game", "Why"],
      (item) => [`${item.team} ${item.name}`, item.game, item.detail],
    ));
  }
  return section;
}

function cardTable(heading, rows, headers, cells, titleFor) {
  const block = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = heading;
  block.append(title);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "card-note";
    empty.textContent = "None on this slate.";
    block.append(empty);
    return block;
  }
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  const head = document.createElement("tr");
  headers.forEach((header) => addCell(head, "th", header));
  const thead = document.createElement("thead");
  thead.append(head);
  const tbody = document.createElement("tbody");
  rows.forEach((item) => {
    const tr = document.createElement("tr");
    if (item.ready) tr.classList.add("ready-row");
    const prose = new Set(["Why", "Lean", "Inputs", "Status"]);
    cells(item).forEach((value, index) => {
      const cell = addCell(tr, "td", value == null ? "" : String(value));
      if (prose.has(headers[index])) cell.classList.add("wrap");
      if (titleFor && index === cells(item).length - 1) cell.title = titleFor(item);
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  block.append(wrap);
  return block;
}

function shortDate(iso) {
  const parts = iso.split("-");
  return `${MONTHS[Number(parts[1]) - 1]} ${Number(parts[2])}`;
}

function stamp(iso) {
  if (!iso) return "";
  const eastern = iso.endsWith("-05:00") || iso.endsWith("-04:00");
  return iso.replace("T", " ").replace(/[+-]\d\d:\d\d$/, "") + (eastern ? " ET" : "");
}

function labeled(text, control, extra) {
  const wrap = document.createElement("label");
  wrap.className = extra ? `field ${extra}` : "field";
  const caption = document.createElement("span");
  caption.textContent = text;
  wrap.append(caption, control);
  return wrap;
}

function input(value, placeholder, onInput) {
  const field = document.createElement("input");
  field.value = value;
  field.placeholder = placeholder;
  field.addEventListener("input", () => onInput(field.value));
  return field;
}

function select(options, value, onChange) {
  const field = document.createElement("select");
  options.forEach((option) => {
    const item = document.createElement("option");
    item.value = option[0];
    item.textContent = option[1];
    field.append(item);
  });
  field.value = value;
  field.addEventListener("change", () => onChange(field.value));
  return field;
}

function toggle(text, checked, onChange) {
  const wrap = document.createElement("label");
  wrap.className = "check";
  const field = document.createElement("input");
  field.type = "checkbox";
  field.checked = checked;
  field.addEventListener("change", () => onChange(field.checked));
  wrap.append(field, document.createTextNode(` ${text}`));
  return wrap;
}

function addCell(row, tag, text) {
  const cell = document.createElement(tag);
  if (text) cell.textContent = text;
  row.append(cell);
  return cell;
}

function dot(x, y, color, label, readout) {
  const node = svgEl("circle");
  node.setAttribute("cx", x);
  node.setAttribute("cy", y);
  node.setAttribute("r", "5");
  node.setAttribute("fill", color);
  const title = svgEl("title");
  title.textContent = label;
  node.append(title);
  node.addEventListener("pointerenter", () => {
    readout.textContent = label;
  });
  return node;
}

function poly(points, color, dash) {
  const node = svgEl("polyline");
  node.setAttribute("points", points);
  node.setAttribute("fill", "none");
  node.setAttribute("stroke", color);
  node.setAttribute("stroke-width", "2");
  if (dash) node.setAttribute("stroke-dasharray", dash);
  return node;
}

function svgEl(name) {
  return document.createElementNS("http://www.w3.org/2000/svg", name);
}

async function fetchJson(path, fresh) {
  const href = fresh ? `${path}${path.includes("?") ? "&" : "?"}t=${Date.now()}` : path;
  const response = await fetch(href, fresh ? { cache: "no-store" } : undefined);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

const OU_CODES = {
  "Total Points": "pts",
  "Total Rebounds": "reb",
  "Total Assists": "ast",
  "Total 3-Point Field Goals": "fg3m",
  "Total Steals": "stl",
  "Total Blocks": "blk",
  "Total Turnovers": "tov",
  "Total Points and Rebounds": "pr",
  "Total Points and Assists": "pa",
  "Total Assists and Rebounds": "ra",
  "Total Points, Rebounds, and Assists": "pra",
  "Total Steals and Blocks": "sb",
};

const MILESTONE_CODES = {
  "Points Milestones": "pts_ms",
  "Rebounds Milestones": "reb_ms",
  "Assists Milestones": "ast_ms",
  "3-Point Field Goals Milestones": "fg3m_ms",
  "Steals Milestones": "stl_ms",
  "Blocks Milestones": "blk_ms",
  "Turnovers Milestones": "tov_ms",
  "Points + Rebounds Milestones": "pr_ms",
  "Points + Assists Milestones": "pa_ms",
  "Rebounds + Assists Milestones": "ra_ms",
  "Points + Assists + Rebounds Milestones": "pra_ms",
  "Steals + Blocks Milestones": "sb_ms",
};

const YES_CODES = {
  "First Basket": "first",
  "1st Team FG Scorer": "teamfg",
  "1st Team FG Scorer Exact": "teamfg",
  "1st 3PT FG Scorer": "first3",
  "To Record a Double Double": "dd",
  "To Record a Triple Double": "td",
};

const QUARTER_WORDS = { "1st": 1, "2nd": 2, "3rd": 3, "4th": 4 };
const QUARTER_TOTAL_WORD = { First: 1, Second: 2, Third: 3, Fourth: 4 };
const QUARTER_STAT = {
  Points: "pts",
  Rebounds: "reb",
  Assists: "ast",
  Steals: "stl",
  Blocks: "blk",
  "3-Point Field Goals": "fg3m",
  Turnovers: "tov",
};
const FIELD_CODES = {
  pts: "pts",
  reb: "reb",
  ast: "ast",
  fg3m: "fg3m",
  stl: "stl",
  blk: "blk",
  tov: "tov",
  "pts,reb": "pr",
  "pts,ast": "pa",
  "ast,reb": "ra",
  "reb,ast": "ra",
  "pts,reb,ast": "pra",
  "stl,blk": "sb",
};
const QUARTER_RE = /^(Points|Rebounds|Assists|Steals|Blocks|3-Point Field Goals|Turnovers)(?: \+ (Rebounds|Assists|Blocks))?(?: \+ (Rebounds|Assists))? Milestones - (1st|2nd|3rd|4th) Quarter$/;
const QUARTER_TOTAL_RE = /^Total (First|Second|Third|Fourth) Quarter (Points|Rebounds|Assists|Steals|Blocks|3-Point Field Goals|Turnovers)$/;

function easternToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const bag = {};
  parts.forEach((part) => {
    bag[part.type] = part.value;
  });
  return `${bag.year}-${bag.month}-${bag.day}`;
}

function addDays(iso, days) {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function slateIsOpen(date) {
  const today = easternToday();
  return date >= today && date <= addDays(today, 2);
}

function gameHasLines(game) {
  return (game.rows || []).some((row) => (row.props || []).length);
}

function dayNeedsLines(day) {
  return ((day && day.games) || []).some((game) => game.status !== "final" && !gameHasLines(game));
}

function lineStatus(game) {
  if (state.checking && slateIsOpen(state.date)) return "Checking whether lines are posted.";
  if (game && game.note === "lines could not be checked") return "Lines could not be checked. Reload to try again.";
  return "Lines are not posted yet.";
}

function datesToRefresh() {
  const today = easternToday();
  const wanted = new Set();
  for (let offset = 0; offset < 3; offset += 1) wanted.add(addDays(today, offset));
  if (state.date) wanted.add(state.date);
  return [...wanted].filter((date) => knownDate(date)).sort();
}

// Recheck today and the next two days after first paint. Use a fresh copy of the published slate, and fill from ESPN when that file still has no lines.
async function refreshOpenSlates() {
  state.checking = true;
  try {
    const dates = datesToRefresh();
    const first = dates.includes(state.date) ? state.date : dates[0];
    const rest = dates.filter((date) => date !== first);
    if (first) await refreshSlate(first);
    await Promise.all(rest.map(async (date) => {
      try {
        await refreshSlate(date);
      } catch (error) {
        return error;
      }
    }));
  } finally {
    const wasChecking = state.checking;
    state.checking = false;
    if (wasChecking && state.view === "board" && state.day && dayNeedsLines(state.day)) paintBoard();
  }
}

async function refreshSlate(date) {
  const remote = await fetchJson(`data/days/${date}.json`, true);
  if (!dayNeedsLines(remote)) {
    adoptDay(date, remote);
    return;
  }
  const filled = await populateDay(remote);
  if (filled) adoptDay(date, remote);
}

function adoptDay(date, day) {
  state.liveDays[date] = day;
  if (state.view === "board" && state.date === date) {
    state.day = day;
    paintBoard();
  }
  if (state.view === "player" && state.logs && state.season) paintPlayer();
}

async function populateDay(day) {
  const pending = (day.games || []).filter((game) => game.status !== "final" && !gameHasLines(game));
  if (!pending.length) return false;
  await ensureLookups();
  const filled = await mapPool(pending, 4, (game) => loadGameLines(game));
  return filled.some(Boolean);
}

async function mapPool(items, limit, worker) {
  const results = new Array(items.length);
  let cursor = 0;
  async function run() {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await worker(items[index]);
    }
  }
  const workers = Math.min(limit, items.length);
  await Promise.all(Array.from({ length: workers }, () => run()));
  return results;
}

async function loadGameLines(game) {
  try {
    const items = await fetchPropBets(game.id);
    if (!items || !items.length) return false;
    let odds = null;
    try {
      odds = await fetchOdds(game.id);
    } catch (error) {
      odds = null;
    }
    mergeGame(game, items, odds);
    return true;
  } catch (error) {
    game.note = "lines could not be checked";
    return false;
  }
}

async function fetchPropBets(eventId) {
  const rows = [];
  let page = 1;
  let pageCount = 1;
  while (page <= pageCount) {
    const payload = await fetchExternal(propUrl(eventId, page));
    if (!payload) return page === 1 ? null : rows;
    if (page === 1) pageCount = Math.min(Number(payload.pageCount || 1), 6);
    rows.push(...(payload.items || []));
    page += 1;
  }
  return rows;
}

function propUrl(eventId, page) {
  return `https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/${eventId}/competitions/${eventId}/odds/100/propBets?limit=500&page=${page}`;
}

async function fetchOdds(eventId) {
  const payload = await fetchExternal(
    `https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/${eventId}/competitions/${eventId}/odds/100`,
  );
  if (!payload) return null;
  const body = payload.items ? payload.items[0] : payload;
  if (!body) return null;
  const total = Number(body.overUnder);
  return {
    spread: body.details || "",
    total: Number.isFinite(total) ? total : null,
  };
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchExternal(url) {
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let response;
    try {
      response = await fetch(url, { cache: "no-store" });
    } catch (error) {
      lastError = error;
      if (attempt === 2) throw error;
      await wait(350 * (attempt + 1));
      continue;
    }
    if (response.ok) return response.json();
    lastError = new Error(`${url} returned ${response.status}`);
    if (response.status === 404 && attempt === 2) return null;
    if (response.status !== 404 && response.status !== 429 && response.status < 500) throw lastError;
    await wait(350 * (attempt + 1));
  }
  throw lastError;
}

async function ensureLookups() {
  if (!state.lookups) {
    state.lookups = (async () => {
      const jobs = [];
      if (!state.season) {
        jobs.push(fetchJson("data/season.json").then((data) => {
          state.season = data;
        }));
      }
      if (!state.logs) {
        jobs.push(fetchJson("data/logs.json").then((data) => {
          state.logs = data;
        }));
      }
      await Promise.all(jobs);
      state.playerIndex = new Map((state.season.players || []).map((player) => [String(player.id), player]));
    })();
  }
  try {
    await state.lookups;
  } catch (error) {
    state.lookups = null;
  }
}

function mergeGame(game, items, odds) {
  const grouped = new Map();
  collapseProps(items).forEach((prop) => {
    const list = grouped.get(prop.player_id) || [];
    list.push(prop);
    grouped.set(prop.player_id, list);
  });
  const rows = (game.rows || []).map((row) => {
    const props = grouped.get(String(row.id));
    if (!props) return row;
    return { ...row, props: packProps(props, row) };
  });
  const seen = new Set(rows.map((row) => String(row.id)));
  grouped.forEach((props, playerId) => {
    if (seen.has(playerId)) return;
    rows.push(newRow(playerId, props));
  });
  rows.sort((left, right) => orderKey(left, game) - orderKey(right, game) || left.name.localeCompare(right.name));
  game.rows = rows;
  game.note = "";
  if (odds && odds.spread) game.spread = odds.spread;
  if (odds && odds.total != null) game.total = odds.total;
}

function packProps(props) {
  return sortProps(props.map(compactProp));
}

function sortProps(props) {
  return props.sort((left, right) => {
    if (left.k !== right.k) return left.k < right.k ? -1 : 1;
    if (left.m !== right.m) return left.m < right.m ? -1 : 1;
    return (left.line || "").localeCompare(right.line || "");
  });
}

function newRow(playerId, props) {
  const person = (state.playerIndex && state.playerIndex.get(String(playerId))) || {};
  const row = {
    id: String(playerId),
    name: person.name || `Player ${playerId}`,
    team: person.team || "",
    pos: person.pos || "",
    min: "",
    starter: false,
    role: "",
    rank: 90,
    avail: "",
    avail_label: "",
    avail_note: "",
    stat: null,
    props: [],
  };
  row.props = packProps(props);
  return row;
}

function compactProp(prop) {
  const packed = {
    m: prop.market,
    c: prop.code,
    k: prop.kind,
    line: prop.line || "",
    r: "pending",
  };
  if (prop.line_open && prop.line_open !== prop.line) packed.open = prop.line_open;
  if (prop.price_a) packed.a = prop.price_a;
  if (prop.price_b) packed.b = prop.price_b;
  return packed;
}

function collapseProps(rows) {
  const grouped = new Map();
  rows.forEach((row) => {
    const playerId = athleteId(row);
    if (!playerId) return;
    const market = (row.type && row.type.name) || "Unknown";
    const kind = kindFor(market);
    const current = (row.current && row.current.target) || {};
    const opened = (row.open && row.open.target) || {};
    const odds = row.odds || {};
    const line = current.displayValue || (odds.total && odds.total.value) || "";
    const lineOpen = opened.displayValue || (odds.total && odds.total.open) || "";
    const american = odds.american || {};
    const lineKey = kind === "milestone" ? line : "";
    const key = `${playerId}|${market}|${lineKey}`;
    let entry = grouped.get(key);
    if (!entry) {
      entry = {
        player_id: playerId,
        market,
        kind,
        code: codeFor(market),
        line: line || "",
        line_open: lineOpen || "",
        prices: [],
      };
      grouped.set(key, entry);
    }
    if (line) entry.line = line;
    if (lineOpen && !entry.line_open) entry.line_open = lineOpen;
    entry.prices.push([american.value, american.open]);
  });
  const collapsed = [];
  grouped.forEach((entry) => {
    const prices = entry.prices.slice().sort((left, right) => americanValue(left[0]) - americanValue(right[0]));
    const first = prices[0] || [null, null];
    const second = prices[1] || [null, null];
    collapsed.push({
      player_id: entry.player_id,
      market: entry.market,
      code: entry.code,
      kind: entry.kind,
      line: entry.line || "",
      line_num: parseLine(entry.line),
      line_open: entry.line_open || "",
      price_a: first[0],
      price_b: second[0],
    });
  });
  return collapsed;
}

function athleteId(row) {
  const athlete = row.athlete || {};
  if (athlete.id) return String(athlete.id);
  const ref = athlete.$ref || "";
  const marker = "/athletes/";
  const at = ref.indexOf(marker);
  if (at < 0) return "";
  return ref.slice(at + marker.length).split("?")[0];
}

function kindFor(market) {
  if (OU_CODES[market] || quarterTotalSpec(market)) return "ou";
  if (MILESTONE_CODES[market] || market.includes("Milestones")) return "milestone";
  if (YES_CODES[market]) return "yesno";
  return "other";
}

function codeFor(market) {
  if (OU_CODES[market]) return OU_CODES[market];
  if (MILESTONE_CODES[market]) return MILESTONE_CODES[market];
  if (YES_CODES[market]) return YES_CODES[market];
  const quarter = quarterSpec(market) || quarterTotalSpec(market);
  if (quarter) return `${quarter.stat}_q${quarter.period}`;
  const slug = market.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return (slug || "other").slice(0, 40);
}

function quarterTotalSpec(market) {
  const match = QUARTER_TOTAL_RE.exec(market);
  if (!match) return null;
  return { stat: QUARTER_STAT[match[2]], period: QUARTER_TOTAL_WORD[match[1]] };
}

function quarterSpec(market) {
  const match = QUARTER_RE.exec(market);
  if (!match) return null;
  const names = [match[1], match[2], match[3]].filter(Boolean);
  return { stat: codeForFields(names), period: QUARTER_WORDS[match[4]] };
}

function codeForFields(names) {
  const key = names.map((name) => QUARTER_STAT[name]).join(",");
  return FIELD_CODES[key] || key.replace(/,/g, "_");
}

function parseLine(display) {
  if (!display) return null;
  const value = Number(String(display).replace("+", "").trim());
  return Number.isFinite(value) ? value : null;
}

function americanValue(price) {
  if (!price) return 0;
  const value = Number(String(price).replace("+", ""));
  return Number.isFinite(value) ? value : 0;
}

function recentActuals(playerId, code, count) {
  const series = ((state.logs || {})[playerId] || {})[code] || [];
  const values = [];
  for (let index = series.length - 1; index >= 0 && values.length < count; index -= 1) {
    const actual = Number(series[index][3]);
    if (!Number.isFinite(actual)) continue;
    values.push(actual);
  }
  return values;
}

function formatNumber(value) {
  const text = Number(value).toFixed(1);
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}
