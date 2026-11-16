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
};

const app = document.querySelector("#app");
const tools = document.querySelector("#tools");
const dates = document.querySelector("#dates");

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

boot().catch((error) => {
  app.textContent = `The board could not load. ${error.message}`;
});

async function boot() {
  state.manifest = await fetchJson("data/manifest.json");
  const requested = new URLSearchParams(location.hash.replace(/^#/, "")).get("d");
  const known = state.manifest.dates.map((item) => item.date);
  const today = state.manifest.today || "";
  const upcoming = state.manifest.dates.find((item) => item.date >= today && item.games);
  state.date = known.includes(requested) ? requested : (upcoming || known[known.length - 1]).date;
  paintChrome();
  await setView(state.view);
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
  const counts = state.manifest.counts;
  document.querySelector("#title").textContent = `${state.manifest.season} player props`;
  document.querySelector("#meta").textContent = `${counts.final} finals · ${counts.props} props · updated ${stamp(state.manifest.generated_at)}`;
  document.querySelector("#foot").textContent = `${state.manifest.source}. The two prices on a total are the two sides of the number. ESPN does not label which one is the over. Players who did not play are void. Past slates stay on this site, and only today plus the next two days are refreshed.`;
  dates.replaceChildren();
  state.manifest.dates.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = shortDate(item.date);
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
  history.replaceState(null, "", `#d=${date}`);
  paintChrome();
  if (state.view !== "board") await setView("board");
  else await showBoard();
}

async function showBoard() {
  tools.replaceChildren();
  tools.append(
    labeled("Player", input(state.query, "Search a player", (value) => {
      state.query = value;
      paintBoard();
    })),
    labeled("Team", teamSelect()),
    toggle("Show every line", state.showAll, (checked) => {
      state.showAll = checked;
      paintBoard();
    }),
  );
  app.textContent = "Loading this slate.";
  state.day = await fetchJson(`data/days/${state.date}.json`);
  paintBoard();
}

function paintBoard() {
  const core = state.manifest.core;
  const coreCodes = new Set(core.map((market) => market.code));
  app.replaceChildren();
  const games = (state.day && state.day.games) || [];
  if (!games.length) {
    app.textContent = "No games on this slate.";
    return;
  }
  let visible = 0;
  games.forEach((game) => {
    const rows = game.rows.filter((row) => matches(row));
    if (!rows.length && (state.query || state.team)) return;
    visible += 1;
    const article = document.createElement("article");
    article.className = "game";
    const title = document.createElement("h2");
    title.textContent = `${game.away} at ${game.home}`;
    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = gameMeta(game);
    article.append(title, meta);
    if (!game.rows.length) {
      const empty = document.createElement("p");
      empty.textContent = "Lines are not posted yet. The next refresh will pick them up.";
      article.append(empty);
      app.append(article);
      return;
    }
    const table = document.createElement("table");
    const head = document.createElement("tr");
    addCell(head, "th", "Player").classList.add("sticky");
    core.forEach((market) => addCell(head, "th", market.label));
    const thead = document.createElement("thead");
    thead.append(head);
    const tbody = document.createElement("tbody");
    (rows.length ? rows : game.rows).forEach((row) => {
      const tr = document.createElement("tr");
      const name = addCell(tr, "td", "");
      name.classList.add("name");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${row.team} ${row.name}`;
      button.addEventListener("click", () => openPlayer(row.id));
      name.append(button);
      const indexed = indexMain(row.props);
      core.forEach((market) => fillCell(addCell(tr, "td", ""), indexed.get(market.code)));
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
    article.append(wrap);
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
      paintSeason();
    })),
    labeled("Team", teamSelect()),
    labeled("Sort", select(markets.map((market) => [market.code, market.label]), state.sort, (value) => {
      state.sort = value;
      paintSeason();
    })),
    labeled("Min games", select([["1", "1"], ["3", "3"], ["5", "5"], ["8", "8"]], String(state.minimum), (value) => {
      state.minimum = Number(value);
      paintSeason();
    })),
  );
  paintSeason();
}

function paintSeason() {
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
        cell.style.color = "#10140f";
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
    paintPlayer();
  })));
  paintPlayer();
}

function paintPlayer() {
  app.replaceChildren();
  if (!state.playerId) {
    app.textContent = "Pick a player to see every main line against the result.";
    return;
  }
  const person = state.season.players.find((player) => player.id === state.playerId);
  const log = state.logs[state.playerId] || {};
  const title = document.createElement("h2");
  title.textContent = person ? `${person.team} ${person.name}` : "Player";
  app.append(title);
  state.manifest.core.forEach((market) => {
    const series = log[market.code] || [];
    if (!series.length) return;
    const card = document.createElement("section");
    card.className = "panel chart-card";
    const heading = document.createElement("h3");
    const counts = person && person.markets[market.code];
    heading.textContent = `${market.label} ${recordText(counts, market.code)}`;
    card.append(heading);
    if (market.code !== "dd" && market.code !== "first") card.append(lineChart(series));
    card.append(resultStrip(series, market.code));
    app.append(card);
  });
  if (!app.querySelector(".panel")) {
    const empty = document.createElement("p");
    empty.textContent = "No graded main lines yet.";
    app.append(empty);
  }
}

function lineChart(series) {
  const values = [];
  series.forEach((row) => {
    const line = Number(row[1]);
    const actual = Number(row[3]);
    if (Number.isFinite(line)) values.push(line);
    if (Number.isFinite(actual)) values.push(actual);
  });
  const svg = svgEl("svg");
  svg.classList.add("chart");
  svg.setAttribute("viewBox", "0 0 640 140");
  if (values.length < 2) return svg;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const width = 640;
  const height = 140;
  const step = series.length === 1 ? 0 : (width - 24) / (series.length - 1);
  const yFor = (value) => {
    if (high === low) return height / 2;
    return height - 16 - ((value - low) / (high - low)) * (height - 32);
  };
  const line = [];
  const actual = [];
  series.forEach((row, index) => {
    const x = 12 + index * step;
    if (row[1] !== null && row[1] !== "") line.push(`${x},${yFor(Number(row[1]))}`);
    if (row[3] !== null && row[3] !== undefined) actual.push(`${x},${yFor(Number(row[3]))}`);
  });
  svg.append(poly(line.join(" "), "#d6f25c", "4,4"), poly(actual.join(" "), "#f4f7ef", ""));
  return svg;
}

function resultStrip(series, code) {
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
  return strip;
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
      small.textContent = `opened ${prop.open}`;
      chip.append(small);
    }
    grid.append(chip);
  });
  return grid;
}

function fillCell(cell, prop) {
  if (!prop) return cell;
  cell.classList.add(tone(prop.r));
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
  cell.append(strong, em);
  if (prop.open) {
    const small = document.createElement("small");
    small.textContent = `opened ${prop.open}`;
    cell.append(small);
  }
  cell.title = `${prop.m} ${prop.line || ""} ${priceText(prop)}`.trim();
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

function matches(row) {
  if (state.team && row.team !== state.team) return false;
  if (state.query && !row.name.toLowerCase().includes(state.query.toLowerCase())) return false;
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
    if (state.view === "board") paintBoard();
    if (state.view === "season") paintSeason();
  });
}

function openPlayer(playerId) {
  state.playerId = playerId;
  setView("player");
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

function shortDate(iso) {
  const parts = iso.split("-");
  return `${MONTHS[Number(parts[1]) - 1]} ${Number(parts[2])}`;
}

function stamp(iso) {
  if (!iso) return "";
  return iso.replace("T", " ").replace(/-\d\d:\d\d$/, "");
}

function labeled(text, control) {
  const wrap = document.createElement("label");
  wrap.append(document.createTextNode(`${text} `), control);
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

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}
