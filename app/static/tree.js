(function () {
  "use strict";

  var box = document.getElementById("tree");
  if (!box || !window.d3) return;

  var svg = d3.select("#tree-svg");
  var root = svg.append("g");
  var edgeLayer = root.append("g").attr("class", "edges");
  var nodeLayer = root.append("g").attr("class", "nodes");

  var selName = document.getElementById("tree-sel-name");
  var selTitle = document.getElementById("tree-sel-title");
  var selLink = document.getElementById("tree-sel-link");
  var personUrl = box.dataset.personUrl;
  var viewButtons = Array.prototype.slice.call(document.querySelectorAll(".view-switch button"));

  var zoom = d3.zoom().scaleExtent([0.15, 2.5]).on("zoom", function (e) {
    root.attr("transform", e.transform);
  });
  svg.call(zoom).on("dblclick.zoom", null);

  var state = { view: box.dataset.view || "all", selected: box.dataset.main, data: null, byId: {} };
  var card = { w: 128, h: 60 };

  function size() {
    var r = box.getBoundingClientRect();
    return { w: r.width, h: r.height };
  }

  function centerOn(id, scale, animate) {
    var n = state.byId[id];
    if (!n) return;
    var s = size();
    var k = scale || d3.zoomTransform(svg.node()).k || 1;
    var t = d3.zoomIdentity.translate(s.w / 2 - n.x * k, s.h / 2 - n.y * k).scale(k);
    (animate ? svg.transition().duration(450) : svg).call(zoom.transform, t);
  }

  function fitAll() {
    var nodes = state.data.nodes;
    var s = size();
    var xs = nodes.map(function (n) { return n.x; });
    var ys = nodes.map(function (n) { return n.y; });
    var minX = d3.min(xs) - card.w, maxX = d3.max(xs) + card.w;
    var minY = d3.min(ys) - card.h, maxY = d3.max(ys) + card.h;
    var k = Math.min(s.w / (maxX - minX), s.h / (maxY - minY), 1.2);
    var t = d3.zoomIdentity
      .translate(s.w / 2 - ((minX + maxX) / 2) * k, s.h / 2 - ((minY + maxY) / 2) * k)
      .scale(k);
    svg.transition().duration(450).call(zoom.transform, t);
  }

  function syncUrl() {
    var params = new URLSearchParams();
    var n = state.byId[state.selected];
    if (n && !n.me) params.set("main", state.selected);
    if (state.view !== "all") params.set("view", state.view);
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function select(id) {
    var n = state.byId[id];
    if (!n) return;
    state.selected = id;
    nodeLayer.selectAll("g.person").classed("selected", function (d) { return d.id === id; });
    selName.textContent = n.name;
    selTitle.textContent = n.me ? "나" : (n.title || "");
    selLink.href = personUrl + id;
    syncUrl();
  }

  function draw(data) {
    card = data.card;
    state.data = data;
    state.byId = {};
    data.nodes.forEach(function (n) { state.byId[n.id] = n; });

    edgeLayer.selectAll("path")
      .data(data.edges)
      .join("path")
      .attr("d", function (e) { return e.d; })
      .attr("class", function (e) {
        var cls = "edge edge-" + e.type;
        if (e.type === "child" && e.kind && e.kind !== "biological") cls += " edge-dashed";
        if (e.type === "spouse" && e.status && e.status !== "married") cls += " edge-dashed";
        return cls;
      });

    var g = nodeLayer.selectAll("g.person")
      .data(data.nodes, function (d) { return d.id; })
      .join(function (enter) {
        var g = enter.append("g").on("click", function (e, d) { select(d.id); });
        g.append("rect").attr("rx", 8);
        g.append("text").attr("class", "name").attr("y", 24);
        g.append("text").attr("class", "sub").attr("y", 44);
        return g;
      });

    g.attr("class", function (d) {
      return "person gender-" + (d.gender || "unknown") + (d.me ? " me" : "") + (d.deceased ? " deceased" : "");
    }).attr("transform", function (d) {
      return "translate(" + (d.x - card.w / 2) + "," + (d.y - card.h / 2) + ")";
    });
    g.select("rect").attr("width", card.w).attr("height", card.h);
    // textContent로 넣으므로 이름에 태그가 있어도 그대로 글자로 보인다.
    g.select("text.name").attr("x", card.w / 2)
      .text(function (d) { return d.name + (d.deceased ? " (고인)" : ""); });
    g.select("text.sub").attr("x", card.w / 2)
      .text(function (d) { return [d.me ? "나" : d.title, d.birth].filter(Boolean).join(" · "); });

    // 이전에 고른 사람이 이 범위에 없으면 나로 돌아간다.
    var start = state.byId[state.selected] ? state.selected : data.me;
    select(start);
    centerOn(start, d3.zoomTransform(svg.node()).k || 1, false);
  }

  function load(view) {
    state.view = view;
    viewButtons.forEach(function (b) { b.setAttribute("aria-selected", b.dataset.view === view ? "true" : "false"); });
    var url = box.dataset.src + (view !== "all" ? "?view=" + encodeURIComponent(view) : "");
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(draw)
      .catch(function () {
        edgeLayer.selectAll("*").remove();
        nodeLayer.selectAll("*").remove();
        selTitle.textContent = "가계도를 불러오지 못했어요. 새로고침해 주세요.";
      });
  }

  viewButtons.forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.dataset.view !== state.view) load(b.dataset.view);
    });
  });
  document.getElementById("tree-me").addEventListener("click", function () {
    if (!state.data) return;
    centerOn(state.data.me, 1, true);
    select(state.data.me);
  });
  document.getElementById("tree-fit").addEventListener("click", function () {
    if (state.data) fitAll();
  });

  load(state.view);
})();
