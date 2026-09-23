(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const N = new Map(D.nodes.map(n => [n.id, n]));
  const OUT = new Map();
  const IN = new Map();
  const requestsByGid = new Map();
  const nf = new Intl.NumberFormat("ru-RU");
  const state = { selected: null, cluster: null, tab: "priority", showAllRequests: false };
  const rankByGid = new Map(D.nodes.slice().sort((a, b) => b.pr - a.pr || a.id.localeCompare(b.id))
    .map((node, index) => [node.id, index + 1]));
  let network = null;

  D.edges.forEach(edge => {
    if (!OUT.has(edge[0])) OUT.set(edge[0], []);
    if (!IN.has(edge[1])) IN.set(edge[1], []);
    OUT.get(edge[0]).push(edge);
    IN.get(edge[1]).push(edge);
  });
  D.requests.forEach(request => {
    if (!requestsByGid.has(request.gid)) requestsByGid.set(request.gid, []);
    requestsByGid.get(request.gid).push(request);
  });

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }
  function clear(node) { node.replaceChildren(); }
  function text(parent, tag, className, value) {
    const child = element(tag, className, value);
    parent.appendChild(child);
    return child;
  }
  function number(value) { return nf.format(value); }
  function money(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "нет данных";
    if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(1).replace(".", ",") + " млн KZT";
    if (Math.abs(value) >= 1e3) return number(Math.round(value / 1e3)) + " тыс KZT";
    return number(Math.round(value)) + " KZT";
  }
  function percent(value, digits = 0) {
    return value === null || value === undefined ? "нет данных" : (value * 100).toFixed(digits).replace(".", ",") + "%";
  }
  function shortGid(gid) { return gid.slice(-10, -3); }
  function roleName(role) { return D.roleRu[role] || role; }
  function roleBadge(role) {
    const badge = element("span", "badge");
    const color = D.colors[role] || "#657987";
    badge.style.setProperty("--badge-dot", color);
    badge.style.setProperty("--badge-bg", color + "18");
    badge.style.setProperty("--badge-fg", color);
    badge.appendChild(element("i"));
    text(badge, "span", "", roleName(role));
    return badge;
  }
  function requestName(type) {
    return {
      next_hop_outgoing: "Исходящие 5-го хопа",
      incoming_external: "Внешние входящие",
      seed_no_outgoing: "Seed без исходящих"
    }[type] || type;
  }

  function renderSummary() {
    $("metric-nodes").textContent = number(D.summary.nodes);
    $("metric-seeds").textContent = number(D.nodes.filter(n => n.seed).length);
    $("metric-edges").textContent = number(D.summary.edges);
    $("metric-clusters").textContent = number(D.summary.clusters);
    $("request-count").textContent = number(D.requests.length);
    document.querySelector("#tab-clusters .count").textContent = number(D.clusters.length) + " групп";
    const select = $("role-filter");
    Object.keys(D.roleRu).forEach(role => {
      const option = document.createElement("option");
      option.value = role;
      option.textContent = roleName(role);
      select.appendChild(option);
      $("role-legend-items").appendChild(roleBadge(role));
    });
  }

  function matches(node) {
    const query = $("gid-search").value.trim();
    const role = $("role-filter").value;
    const seed = $("seed-filter").value;
    return (!query || node.id.includes(query)) &&
      (!role || node.role === role) &&
      (!seed || (seed === "seed") === node.seed);
  }
  function renderPriority() {
    const all = D.nodes.filter(matches).sort((a, b) => b.pr - a.pr || a.id.localeCompare(b.id));
    $("result-count").textContent = number(all.length) + " из " + number(D.nodes.length);
    const list = $("priority-list");
    clear(list);
    if (!all.length) {
      text(list, "p", "empty", "Узлы не найдены. Уточните gid или сбросьте фильтры.");
      return;
    }
    const query = $("gid-search").value.trim();
    const visible = all.slice(0, query ? 50 : 40);
    visible.forEach(node => {
      const button = element("button", "item" + (state.selected === node.id ? " active" : ""));
      button.type = "button";
      button.setAttribute("aria-label", "Открыть клиента " + node.id + ", " + roleName(node.role));
      const top = text(button, "div", "item-top");
      const title = text(top, "span", "item-id");
      text(title, "span", "rank", "#" + rankByGid.get(node.id) + " · ");
      title.appendChild(document.createTextNode(node.id));
      text(top, "span", "score", node.pr.toFixed(3));
      const bottom = text(button, "div", "item-bottom");
      bottom.appendChild(roleBadge(node.role));
      text(bottom, "span", "small-tag", (node.seed ? "seed · " : "") + "кластер " + node.cl);
      text(button, "div", "item-note", node.ev);
      button.addEventListener("click", () => selectNode(node.id));
      list.appendChild(button);
    });
    if (all.length > visible.length) text(list, "p", "help", "Показаны первые " + visible.length + " по приоритету. Поиск охватывает все узлы.");
  }

  function renderClusters() {
    const list = $("cluster-list");
    clear(list);
    const clusters = D.clusters.slice().sort((a, b) => b.n_seed - a.n_seed || b.n_nodes - a.n_nodes);
    clusters.forEach(cluster => {
      const button = element("button", "item" + (state.cluster === cluster.cluster_id ? " active" : ""));
      button.type = "button";
      const top = text(button, "div", "item-top");
      text(top, "span", "item-id", "Кластер " + cluster.cluster_id);
      text(top, "span", "small-tag", number(cluster.n_nodes) + " узлов");
      const bottom = text(button, "div", "item-bottom");
      text(bottom, "span", "badge", cluster.n_seed + " seed");
      text(bottom, "span", "small-tag", money(cluster.sum_kzt_internal));
      text(button, "div", "item-note", cluster.hypothesis);
      button.addEventListener("click", () => focusCluster(cluster.cluster_id));
      list.appendChild(button);
    });
  }

  function renderRequests() {
    const list = $("request-list");
    clear(list);
    const query = $("gid-search").value.trim();
    const groups = ["next_hop_outgoing", "incoming_external", "seed_no_outgoing"];
    let shown = 0;
    groups.forEach(type => {
      const all = D.requests.filter(r => r.request_type === type && (!query || r.gid.includes(query)))
        .sort((a, b) => b.weight - a.weight);
      if (!all.length) return;
      const title = element("h3", "", requestName(type) + " · " + number(all.length));
      title.style.margin = "11px 0 5px";
      list.appendChild(title);
      const visible = all.slice(0, state.showAllRequests || query ? 60 : 5);
      visible.forEach(request => {
        const button = element("button", "item");
        button.type = "button";
        const top = text(button, "div", "item-top");
        text(top, "span", "item-id", request.gid);
        text(top, "span", "small-tag", requestName(type));
        text(button, "div", "item-note", request.reason);
        button.addEventListener("click", () => selectNode(request.gid));
        list.appendChild(button);
        shown++;
      });
      if (all.length > visible.length) text(list, "p", "help", "Показаны первые " + visible.length + " по весу запроса.");
    });
    if (!shown) text(list, "p", "empty", "Для этого gid запросов нет.");
    if (!query && !state.showAllRequests) {
      const more = element("button", "button", "Показать больше запросов");
      more.type = "button";
      more.addEventListener("click", () => { state.showAllRequests = true; renderRequests(); });
      list.appendChild(more);
    }
  }

  function svg(tag, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function renderImpact() {
    const rows = D.res;
    const chart = $("impact-chart");
    clear(chart);
    const width = 360, height = 184, left = 33, top = 16, right = 10, bottom = 28;
    const x = n => left + (width - left - right) * n / (rows.length - 1);
    const y = p => top + (height - top - bottom) * (1 - p);
    const root = svg("svg", { viewBox: "0 0 360 184", "aria-hidden": "true" });
    [0, .5, 1].forEach(level => {
      root.appendChild(svg("line", { x1: left, x2: width - right, y1: y(level), y2: y(level), stroke: "#dce4e8", "stroke-width": 1 }));
      const label = svg("text", { x: 0, y: y(level) + 4, fill: "#5c6c77", "font-size": 10 });
      label.textContent = Math.round(level * 100) + "%";
      root.appendChild(label);
    });
    [["tainted_flow_left", "#15658a"], ["random_flow_left", "#a96b2d"]].forEach(([key, color]) => {
      root.appendChild(svg("polyline", {
        points: rows.map((r, i) => x(i) + "," + y(r[key])).join(" "),
        fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round"
      }));
    });
    chart.appendChild(root);
    const legend = text(chart, "div", "legend");
    text(legend, "span", "", "● Топ по приоритету").style.color = "#15658a";
    text(legend, "span", "", "● Случайные узлы").style.color = "#a96b2d";
    const list = $("impact-list");
    clear(list);
    [5, 10, 20, 30].forEach(n => {
      const r = rows.find(row => row.n_blocked === n);
      if (!r) return;
      const row = text(list, "div", "impact-row");
      text(row, "strong", "", "Топ-" + n);
      text(row, "span", "", percent(r.tainted_flow_left) + " осталось");
      text(row, "span", "", percent(r.random_flow_left) + " случайно");
    });
  }

  function neighbours(gid, depth, direction) {
    const found = new Set([gid]);
    let frontier = [gid];
    for (let step = 0; step < depth; step++) {
      const next = [];
      frontier.forEach(id => {
        const edges = [];
        if (direction !== "in") edges.push(...(OUT.get(id) || []));
        if (direction !== "out") edges.push(...(IN.get(id) || []));
        edges.sort((a, b) => b[2] - a[2]);
        edges.forEach(edge => {
          const other = edge[0] === id ? edge[1] : edge[0];
          if (!found.has(other) && found.size < 220) { found.add(other); next.push(other); }
        });
      });
      frontier = next;
    }
    return [...found];
  }
  function drawGraph() {
    const selected = N.get(state.selected);
    if (!selected) return;
    let ids, note;
    if (state.cluster !== null) {
      const all = D.nodes.filter(n => n.cl === state.cluster).sort((a, b) => b.pr - a.pr);
      ids = all.slice(0, 180).map(n => n.id);
      note = "Кластер " + state.cluster + " · " + number(all.length) + " узлов";
      if (all.length > ids.length) note += " · показаны 180 приоритетных";
      $("graph-title").textContent = "Кластер " + state.cluster;
    } else {
      const depth = Number($("depth-filter").value);
      ids = neighbours(selected.id, depth, $("direction-filter").value);
      note = depth + (depth === 1 ? " хоп" : " хопа") + " вокруг " + selected.id + " · " + ids.length + " узлов";
      if (ids.length === 220) note += " · показаны первые 220";
      $("graph-title").textContent = "Окружение узла";
    }
    $("graph-note").textContent = note;
    $("graph-loading").classList.remove("hidden");
    const set = new Set(ids);
    const nodes = ids.map(id => {
      const n = N.get(id);
      return {
        id, label: shortGid(id),
        title: id + "\n" + roleName(n.role) + " · приоритет " + n.pr.toFixed(3),
        shape: n.seed ? "diamond" : "dot",
        size: 9 + 17 * n.pr,
        color: { background: D.colors[n.role], border: n.id === selected.id ? "#152d3a" : D.colors[n.role] },
        borderWidth: n.id === selected.id ? 4 : 1.5,
        font: { size: n.id === selected.id ? 14 : 10, color: "#263a46", strokeWidth: 3, strokeColor: "#fff" }
      };
    });
    const edges = D.edges.filter(e => set.has(e[0]) && set.has(e[1])).map((edge, i) => ({
      id: i, from: edge[0], to: edge[1], arrows: { to: { enabled: true, scaleFactor: .55 } },
      width: Math.max(1, Math.min(5, Math.log10(edge[2]) - 2.5)),
      title: money(edge[2]) + " · " + edge[3] + " переводов",
      color: { color: "#8095a1", opacity: .58 },
      smooth: { type: "continuous", roundness: .13 }
    }));
    if (network) network.destroy();
    network = new vis.Network($("network"), { nodes, edges }, {
      layout: { randomSeed: 42, improvedLayout: true },
      physics: { solver: "forceAtlas2Based", stabilization: { iterations: 180, updateInterval: 30 } },
      interaction: { hover: true, tooltipDelay: 120, navigationButtons: false },
      nodes: { chosen: true }
    });
    const finish = () => {
      $("graph-loading").classList.add("hidden");
      network.setOptions({ physics: false });
      if (set.has(selected.id)) network.selectNodes([selected.id]);
    };
    network.once("stabilized", finish);
    network.once("stabilizationIterationsDone", finish);
    network.on("click", event => { if (event.nodes.length) selectNode(String(event.nodes[0]), true); });
    window.setTimeout(() => $("graph-loading").classList.add("hidden"), 3000);
  }

  function roleRule(node) {
    const c = D.rules;
    switch (node.role) {
      case "coordinator": return "Плательщики " + node.ind + " ≥ " + c.coordinator_min_in_deg +
        "; получатели " + node.outd + " ≥ " + c.coordinator_min_out_deg +
        "; посредничество в верхних " + Math.round((1 - c.coordinator_min_betweenness_pct) * 100) + "%.";
      case "distributor": return "Получатели " + node.outd + " ≥ " + c.distributor_min_out_deg +
        "; их число как минимум в " + c.distributor_fanout_ratio + " раза больше числа плательщиков.";
      case "consolidator": return "Разных плательщиков " + node.ind + " ≥ " + c.consolidator_min_in_deg + ".";
      case "transit": return "Передано " + percent(node.pt) + " от видимого входа; быстрый исходящий поток " +
        percent(node.fs) + ". Правило: диапазон " + Math.round(c.transit_pt_low * 100) + "–" +
        Math.round(c.transit_pt_high * 100) + "% либо быстрый поток ≥ " +
        Math.round(c.transit_min_fast_share * 100) + "% при передаче ≥ 50% видимого входа.";
      case "terminal": return "Исходящих ≥ " + number(D.summary.min_tx_kzt || 5000) + " KZT нет на полностью наблюдаемом хопе " + node.d + ".";
      case "truncated": return "Хоп 4: исходящие не входили в выгрузку. Этот узел нельзя считать конечным получателем.";
      default: return "Порогов других ролей узел не достиг; для seed без связей требуется дополнительная выгрузка.";
    }
  }
  function detailRow(parent, label, value) {
    text(parent, "span", "", label);
    text(parent, "span", "", value);
  }
  function connectionColumn(parent, label, edges, direction) {
    const column = text(parent, "div");
    text(column, "h4", "", label);
    if (!edges.length) text(column, "span", "help", "В выборке нет");
    edges.slice().sort((a, b) => b[2] - a[2]).slice(0, 5).forEach(edge => {
      const gid = direction === "in" ? edge[0] : edge[1];
      const button = element("button", "", gid);
      button.type = "button";
      text(button, "span", "", money(edge[2]) + " · " + edge[3] + " перев.");
      button.addEventListener("click", () => selectNode(gid));
      column.appendChild(button);
    });
  }
  function renderCard() {
    const node = N.get(state.selected);
    const root = $("node-card");
    clear(root);
    if (!node) return;
    const card = text(root, "div", "card");
    const top = text(card, "div", "card-top");
    const title = text(top, "div");
    text(title, "span", "eyebrow", "Карточка клиента");
    text(title, "h2", "", node.id);
    const score = text(top, "div", "score-large", node.pr.toFixed(3));
    text(score, "small", "", "приоритет 0–1");
    const badges = text(card, "div", "card-badges");
    badges.appendChild(roleBadge(node.role));
    if (node.seed) text(badges, "span", "badge", "seed");
    text(badges, "span", "badge", "хоп " + node.d);
    text(badges, "span", "badge", "кластер " + node.cl);

    const evidence = text(card, "section", "card-section");
    text(evidence, "h3", "", "Почему эта роль");
    text(evidence, "div", "evidence", node.ev);
    text(evidence, "p", "rule", roleRule(node));
    const actions = text(evidence, "div", "card-actions");
    const copy = element("button", "button slim", "Скопировать обоснование");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      const content = node.id + " · " + roleName(node.role) + ". " + node.ev +
        " Приоритет " + node.pr.toFixed(3) + ". Гипотеза для проверки.";
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(content);
        else {
          const field = element("textarea");
          field.value = content; document.body.appendChild(field); field.select();
          document.execCommand("copy"); field.remove();
        }
        copy.textContent = "Скопировано";
        window.setTimeout(() => { copy.textContent = "Скопировать обоснование"; }, 1800);
      } catch (_) { copy.textContent = "Не удалось скопировать"; }
    });
    actions.appendChild(copy);
    const cluster = element("button", "button slim", "Показать кластер");
    cluster.type = "button";
    cluster.addEventListener("click", () => { setTab("clusters"); focusCluster(node.cl); });
    actions.appendChild(cluster);

    const metrics = text(card, "section", "card-section");
    text(metrics, "h3", "", "Наблюдаемые признаки");
    const kv = text(metrics, "div", "kv");
    detailRow(kv, "Входящие", money(node.ink) + " · " + node.ind + " плательщиков");
    detailRow(kv, "Исходящие", money(node.outk) + " · " + node.outd + " получателей");
    detailRow(kv, "Быстрый исходящий поток", percent(node.fs));
    detailRow(kv, "Достижим от seed", node.sources + " источников");
    detailRow(kv, "Прослеживаемый вход", money(node.ti) + " · " + percent(node.ts));
    detailRow(kv, "Оценка роли", node.rs.toFixed(2) + " · выраженность признаков");
    if (node.po !== null) detailRow(kv, "P(переводит дальше)", percent(node.po) + " · AUC модели " + D.summary.cutoff_model.cv_auc);
    const details = text(metrics, "details", "");
    text(details, "summary", "", "Как считается приоритет");
    const weightNames = {
      tainted_in: "прослеживаемый вход", block_impact: "модельный эффект исключения",
      role: "роль", betweenness: "посредничество", seed_sources: "seed источники",
      turnover: "оборот"
    };
    const weights = Object.entries(D.weights).map(([key, value]) =>
      weightNames[key] + " " + Math.round(value * 100) + "%").join(", ");
    text(details, "p", "help", "Взвешенные ранги: " + weights + ". Итог нормирован к 0–1.");

    const connections = text(card, "section", "card-section");
    text(connections, "h3", "", "Крупнейшие связи");
    const lists = text(connections, "div", "connection-list");
    connectionColumn(lists, "От кого", IN.get(node.id) || [], "in");
    connectionColumn(lists, "Кому", OUT.get(node.id) || [], "out");

    const model = text(card, "section", "card-section");
    text(model, "h3", "", "Что проверить дальше");
    const requests = requestsByGid.get(node.id) || [];
    if (requests.length) requests.forEach(r => text(model, "p", "attention", r.reason));
    else text(model, "p", "attention", "Сверить роль и крупные связи с полной банковской выпиской и данными вне этой выборки.");
    text(model, "p", "help", "Модельное исключение узла уменьшает прослеживаемый поток на " +
      percent(node.bi, 1) + ". Это сценарий по наблюдаемым связям, не доказательство вины.");
  }

  function selectNode(gid, preserveGraph = false) {
    if (!N.has(gid)) return;
    state.selected = gid;
    if (!preserveGraph) state.cluster = null;
    window.location.hash = "gid=" + encodeURIComponent(gid);
    renderPriority();
    renderClusters();
    renderCard();
    if (preserveGraph && network) network.selectNodes([gid]);
    else drawGraph();
  }
  function focusCluster(cid) {
    const members = D.nodes.filter(n => n.cl === cid).sort((a, b) => b.pr - a.pr);
    if (!members.length) return;
    state.cluster = cid;
    state.selected = members[0].id;
    renderPriority();
    renderClusters();
    renderCard();
    drawGraph();
  }
  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tab").forEach(button => {
      const active = button.dataset.tab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === "tab-" + tab));
  }
  function search() {
    const query = $("gid-search").value.trim();
    renderPriority();
    renderRequests();
    if (!query) {
      $("search-status").textContent = "Можно искать любого из " + number(D.nodes.length) + " узлов.";
      setTab("priority");
      return;
    }
    const matches = D.nodes.filter(n => n.id.includes(query)).sort((a, b) => b.pr - a.pr);
    $("search-status").textContent = matches.length
      ? "Найдено " + number(matches.length) + ". Открыт узел с наибольшим приоритетом."
      : "Gid не найден. Проверьте номер.";
    setTab("priority");
    if (matches.length) {
      $("role-filter").value = "";
      $("seed-filter").value = "";
      selectNode(matches[0].id);
    }
  }

  document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => setTab(button.dataset.tab)));
  document.querySelector(".tabs").addEventListener("keydown", event => {
    const tabs = [...document.querySelectorAll(".tab")];
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    let next = current;
    if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    tabs[next].focus();
    setTab(tabs[next].dataset.tab);
  });
  $("search-button").addEventListener("click", search);
  $("gid-search").addEventListener("keydown", event => { if (event.key === "Enter") search(); });
  $("gid-search").addEventListener("input", () => { renderPriority(); renderRequests(); });
  $("role-filter").addEventListener("change", renderPriority);
  $("seed-filter").addEventListener("change", renderPriority);
  $("direction-filter").addEventListener("change", () => { state.cluster = null; drawGraph(); });
  $("depth-filter").addEventListener("change", () => { state.cluster = null; drawGraph(); });
  $("reset-graph").addEventListener("click", () => { state.cluster = null; drawGraph(); });

  renderSummary();
  renderImpact();
  renderRequests();
  const hashGid = decodeURIComponent((window.location.hash.match(/gid=([^&]+)/) || [])[1] || "");
  selectNode(N.has(hashGid) ? hashGid : D.nodes.slice().sort((a, b) => b.pr - a.pr)[0].id);
})();
