/* GWA Brain — knowledge tree (hand-built vanilla SVG, no libraries).
 *
 * Renders a node-link `dependency_tree` (from the /ask answer event) or the
 * whole co-usage graph (from GET /graph). Supports pan + zoom (mouse wheel and
 * drag on desktop; one-finger drag + two-finger pinch on touch) and a tooltip
 * shown when a node is clicked / tapped.
 *
 * Public API:  const tree = GWATree(hostElement);
 *   tree.render(treeData)   // {nodes:[...], links:[...]}  — null/empty => placeholder
 *   tree.reset()            // recenter + reset zoom (fit-to-view)
 *   tree.clear()            // empty the tree
 *
 * Colors come from CSS variables / classes in style.css (no inline palette here).
 */
(function () {
  "use strict";

  var SVG = "http://www.w3.org/2000/svg";
  var NODE_W = 212, NODE_H = 46;

  function el(tag, attrs) {
    var e = document.createElementNS(SVG, tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function trunc(s, n) {
    s = String(s == null ? "" : s);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  window.GWATree = function (host) {
    host.classList.add("tree-host");
    host.innerHTML = "";

    var svg = el("svg", { class: "tree-svg" });
    // arrowhead marker for the derivation tree's parent -> child edges
    var defs = el("defs");
    var marker = el("marker", {
      id: "tree-arrow", viewBox: "0 0 10 10", refX: "9.5", refY: "5",
      markerWidth: "8", markerHeight: "8", orient: "auto", markerUnits: "userSpaceOnUse"
    });
    marker.appendChild(el("path", { d: "M0,0 L10,5 L0,10 z", class: "tree-arrow-head" }));
    defs.appendChild(marker);
    svg.appendChild(defs);
    var viewport = el("g", { class: "viewport" });
    var gLinks = el("g", { class: "links" });
    var gNodes = el("g", { class: "nodes" });
    viewport.appendChild(gLinks);
    viewport.appendChild(gNodes);
    svg.appendChild(viewport);
    host.appendChild(svg);

    var placeholder = document.createElement("div");
    placeholder.className = "tree-empty";
    placeholder.textContent = "No tree yet – ask a question or open the overview.";
    host.appendChild(placeholder);

    var tip = document.createElement("div");
    tip.className = "tree-tip hidden";
    host.appendChild(tip);

    var t = { x: 0, y: 0, k: 1 };          // viewport transform
    var nodeById = {};                      // id -> laid-out node
    var openId = null;                      // currently shown tooltip node

    // ---- transform helpers -------------------------------------------------
    function apply() {
      viewport.setAttribute("transform",
        "translate(" + t.x + "," + t.y + ") scale(" + t.k + ")");
      if (openId) positionTip(openId);
    }
    function zoomAround(px, py, factor) {
      var wx = (px - t.x) / t.k, wy = (py - t.y) / t.k;
      var nk = clamp(t.k * factor, 0.15, 4);
      t.k = nk; t.x = px - wx * nk; t.y = py - wy * nk;
    }
    function size() {
      return { w: host.clientWidth || 600, h: host.clientHeight || 400 };
    }

    // ---- layout ------------------------------------------------------------
    function stackCol(arr, x, rowY) {
      var n = arr.length;
      arr.forEach(function (nd, i) { nd.x = x; nd.y = (i - (n - 1) / 2) * rowY; });
    }
    function layout(data) {
      var nodes = data.nodes.map(function (n) { return Object.assign({}, n); });
      nodeById = {};
      nodes.forEach(function (n) { nodeById[n.id] = n; });

      var answer = nodes.filter(function (n) { return n.type === "answer"; })[0];
      if (answer) {
        var kept = nodes.filter(function (n) { return n.type === "fact" && n.status === "kept"; });
        var other = nodes.filter(function (n) { return n.type === "fact" && n.status !== "kept" && n.status !== "struck"; });
        var struck = nodes.filter(function (n) { return n.type === "fact" && n.status === "struck"; });
        var gaps = nodes.filter(function (n) { return n.type === "gap"; });
        answer.x = 0; answer.y = 0;
        var colX = 330, rowY = 64;
        stackCol(kept.concat(other), -colX, rowY);   // kept facts to the left
        stackCol(struck, colX, rowY);                 // struck facts to the right
        stackCol(gaps, colX * 2, rowY);               // gaps to the side
      } else {
        // whole-graph overview: show only the CONNECTED co-usage graph (facts that
        // have been cited together). Thousands of isolated facts have no tree structure
        // and would blow the layout up into an unreadable ring, so we drop them.
        var linked = {};
        (data.links || []).forEach(function (l) { linked[l.source] = 1; linked[l.target] = 1; });
        var conn = nodes.filter(function (nd) { return linked[nd.id]; });
        if (!conn.length) return [];                  // nothing connected yet
        nodeById = {};
        conn.forEach(function (nd) { nodeById[nd.id] = nd; });
        var n = conn.length;
        var R = Math.max(170, Math.min(n * 26, 1400));
        if (n === 1) { conn[0].x = 0; conn[0].y = 0; }
        else conn.forEach(function (nd, i) {
          var a = (i / n) * Math.PI * 2 - Math.PI / 2;
          nd.x = Math.cos(a) * R; nd.y = Math.sin(a) * R;
        });
        return conn;
      }
      return nodes;
    }

    // ---- hierarchical (derivation) layout ----------------------------------
    // Used when any link kind === "derives": draw a top-down dependency tree
    // rooted at the answer. children(answer) = kept facts via support links;
    // children(fact) = its prerequisites via derives links. Struck facts and
    // gaps are parked in side columns to the right so they stay visible.
    function stackRow(arr, y, colX) {
      var n = arr.length;
      arr.forEach(function (nd, i) { nd.x = (i - (n - 1) / 2) * colX; nd.y = y; });
    }
    function stackColAt(arr, x, midY, rowGap) {
      var n = arr.length;
      arr.forEach(function (nd, i) { nd.x = x; nd.y = midY + (i - (n - 1) / 2) * rowGap; });
    }
    function layoutHier(data) {
      var nodes = data.nodes.map(function (n) { return Object.assign({}, n); });
      nodeById = {};
      nodes.forEach(function (n) { nodeById[n.id] = n; });
      var answer = nodes.filter(function (n) { return n.type === "answer"; })[0];

      // child adjacency per the contract's rule
      var childrenOf = {};
      nodes.forEach(function (n) { childrenOf[n.id] = []; });
      (data.links || []).forEach(function (l) {
        if (l.kind === "support" && l.target === answer.id) {
          if (childrenOf[answer.id]) childrenOf[answer.id].push(l.source);
        } else if (l.kind === "derives") {
          if (childrenOf[l.source]) childrenOf[l.source].push(l.target);
        }
      });

      // reachable set (walk from the answer down the child edges)
      var reachable = {}; reachable[answer.id] = true;
      var stack = [answer.id];
      while (stack.length) {
        var cur = stack.pop();
        (childrenOf[cur] || []).forEach(function (c) {
          if (nodeById[c] && !reachable[c]) { reachable[c] = true; stack.push(c); }
        });
      }

      // longest-path depth from the answer so a shared prerequisite sits at its
      // MAX depth; relaxation is capped by node count to stay safe on cycles.
      var depth = {}; depth[answer.id] = 0;
      var ids = Object.keys(reachable);
      var changed = true, guard = 0;
      while (changed && guard <= ids.length + 1) {
        changed = false; guard++;
        ids.forEach(function (pid) {
          var pd = depth[pid]; if (pd == null) return;
          (childrenOf[pid] || []).forEach(function (c) {
            if (!reachable[c]) return;
            if (depth[c] == null || depth[c] < pd + 1) { depth[c] = pd + 1; changed = true; }
          });
        });
      }

      // group by level and spread siblings evenly on x, top -> down on y
      var levels = {}, maxLevel = 0;
      ids.forEach(function (id) {
        var d = depth[id] == null ? 0 : depth[id];
        (levels[d] = levels[d] || []).push(id);
        if (d > maxLevel) maxLevel = d;
      });
      var ROW = 110, COLX = 248;
      Object.keys(levels).forEach(function (lvKey) {
        stackRow(levels[lvKey].map(function (id) { return nodeById[id]; }), (+lvKey) * ROW, COLX);
      });

      var hierMaxX = 0, hierMidY = (maxLevel * ROW) / 2;
      ids.forEach(function (id) { hierMaxX = Math.max(hierMaxX, nodeById[id].x); });

      // hierarchy-eligible nodes the answer can't reach: keep them visible on an
      // extra row below the tree rather than dropping them.
      var leftover = nodes.filter(function (n) {
        return !reachable[n.id] && (n.type === "answer" || (n.type === "fact" && n.status !== "struck"));
      });
      if (leftover.length) stackRow(leftover, (maxLevel + 1) * ROW, COLX);

      // struck facts + gaps live in side columns to the right
      var struck = nodes.filter(function (n) { return n.type === "fact" && n.status === "struck"; });
      var gaps = nodes.filter(function (n) { return n.type === "gap"; });
      stackColAt(struck, hierMaxX + 360, hierMidY, 86);
      stackColAt(gaps, hierMaxX + 680, hierMidY, 86);

      // tree edges, parent -> child, downward only (skip cycle back-edges)
      var edges = [], seen = {};
      ids.forEach(function (pid) {
        (childrenOf[pid] || []).forEach(function (cid) {
          if (!reachable[cid]) return;
          if (depth[cid] == null || depth[cid] <= depth[pid]) return;
          var key = pid + "|" + cid;
          if (seen[key]) return; seen[key] = 1;
          edges.push({ parent: pid, child: cid, kind: pid === answer.id ? "support" : "derives" });
        });
      });

      return { nodes: nodes, edges: edges };
    }

    // ---- rendering ---------------------------------------------------------
    function nodeClass(n) {
      if (n.type === "answer") return "tnode tnode-answer";
      if (n.type === "gap") return "tnode tnode-gap";
      if (n.status === "kept") return "tnode tnode-kept";
      if (n.status === "struck") return "tnode tnode-struck";
      if (n.status === "derived") return "tnode tnode-derived";
      return "tnode tnode-fact";
    }
    function linkClass(l) {
      if (l.kind === "support") return "tlink tlink-support";
      if (l.kind === "derives") return "tlink tlink-derives";
      if (l.kind === "struck") return "tlink tlink-struck";
      if (l.kind === "gap") return "tlink tlink-gap";
      return "tlink tlink-cousage"; // co_usage and overview links
    }

    function appendNode(n) {
      var g = el("g", { class: nodeClass(n), "data-id": n.id,
        transform: "translate(" + n.x + "," + n.y + ")" });
      var rect = el("rect", {
        x: -NODE_W / 2, y: -NODE_H / 2, width: NODE_W, height: NODE_H, rx: 9, ry: 9
      });
      var label = trunc(n.label || n.text || n.id, 30);
      var txt = el("text", { x: 0, y: 1, "text-anchor": "middle", "dominant-baseline": "middle" });
      txt.textContent = label;
      g.appendChild(rect);
      g.appendChild(txt);
      gNodes.appendChild(g);
    }

    function draw(nodes, links) {
      gLinks.textContent = "";
      gNodes.textContent = "";

      (links || []).forEach(function (l) {
        var a = nodeById[l.source], b = nodeById[l.target];
        if (!a || !b) return;
        var line = el("line", {
          class: linkClass(l),
          x1: a.x, y1: a.y, x2: b.x, y2: b.y
        });
        gLinks.appendChild(line);
      });

      nodes.forEach(appendNode);
    }

    // Top-down hierarchical render: dashed struck/gap links from the raw link
    // list, then solid support/derives tree edges (parent -> child) each with an
    // arrowhead, then the nodes. co_usage edges are omitted to reduce clutter.
    function drawHier(nodes, edges, links) {
      gLinks.textContent = "";
      gNodes.textContent = "";

      (links || []).forEach(function (l) {
        if (l.kind !== "struck" && l.kind !== "gap") return;
        var a = nodeById[l.source], b = nodeById[l.target];
        if (!a || !b) return;
        gLinks.appendChild(el("line", {
          class: linkClass(l), x1: a.x, y1: a.y, x2: b.x, y2: b.y
        }));
      });

      edges.forEach(function (e) {
        var p = nodeById[e.parent], c = nodeById[e.child];
        if (!p || !c) return;
        gLinks.appendChild(el("line", {
          class: e.kind === "derives" ? "tlink tlink-derives" : "tlink tlink-support",
          x1: p.x, y1: p.y + NODE_H / 2, x2: c.x, y2: c.y - NODE_H / 2,
          "marker-end": "url(#tree-arrow)"
        }));
      });

      nodes.forEach(appendNode);
    }

    // ---- fit / reset -------------------------------------------------------
    function fit(nodes) {
      var s = size();
      if (!nodes || !nodes.length) { t = { x: s.w / 2, y: s.h / 2, k: 1 }; apply(); return; }
      var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
      nodes.forEach(function (n) {
        minx = Math.min(minx, n.x - NODE_W / 2); maxx = Math.max(maxx, n.x + NODE_W / 2);
        miny = Math.min(miny, n.y - NODE_H / 2); maxy = Math.max(maxy, n.y + NODE_H / 2);
      });
      var pad = 36;
      var bw = Math.max(1, maxx - minx), bh = Math.max(1, maxy - miny);
      var k = clamp(Math.min((s.w - 2 * pad) / bw, (s.h - 2 * pad) / bh), 0.05, 1.4);
      t.k = k;
      t.x = s.w / 2 - ((minx + maxx) / 2) * k;
      t.y = s.h / 2 - ((miny + maxy) / 2) * k;
      apply();
    }

    var DEFAULT_HINT = "No tree yet – ask a question or open the overview.";
    var lastNodes = [];
    function showHint(msg) {
      gLinks.textContent = ""; gNodes.textContent = "";
      lastNodes = []; nodeById = {};
      placeholder.textContent = msg;
      placeholder.classList.remove("hidden");
    }
    function render(data) {
      hideTip();
      if (!data || !data.nodes || !data.nodes.length) { showHint(DEFAULT_HINT); return; }
      // Derivation tree: top-down hierarchical layout when `derives` links exist.
      var hasDerives = (data.links || []).some(function (l) { return l.kind === "derives"; });
      var hasAnswer = data.nodes.some(function (n) { return n.type === "answer"; });
      if (hasDerives && hasAnswer) {
        var h = layoutHier(data);
        placeholder.classList.add("hidden");
        lastNodes = h.nodes;
        drawHier(h.nodes, h.edges, data.links);
        fit(h.nodes);
        return;
      }
      var laid = layout(data);
      if (!laid.length) {
        // overview with facts but no co-usage links yet
        var n = data.facts != null ? data.facts : data.nodes.length;
        showHint("No connections yet — ask questions, then jointly substantiated " +
                 "facts will link up into the knowledge tree. (" + n + " facts stored.)");
        return;
      }
      placeholder.classList.add("hidden");
      lastNodes = laid;
      draw(lastNodes, data.links);
      fit(lastNodes);
    }

    // ---- tooltip -----------------------------------------------------------
    function tipHtml(n) {
      var h = "";
      if (n.source) h += '<div class="tt-src">' + esc(n.source) + "</div>";
      h += '<div class="tt-text">' + esc(n.text || n.label) + "</div>";
      if (n.status === "struck" && n.reason)
        h += '<div class="tt-reason">✗ Reason: ' + esc(n.reason) + "</div>";
      if (n.type === "fact") {
        var bits = [];
        if (n.weight != null) bits.push("Weight " + n.weight);
        if (n.uses != null) bits.push(n.uses + " uses");
        if (bits.length) h += '<div class="tt-meta">' + esc(bits.join(" · ")) + "</div>";
      }
      if (n.type === "gap") h += '<div class="tt-reason">⚠ uncovered sub-requirement</div>';
      return h;
    }
    function positionTip(id) {
      var n = nodeById[id];
      if (!n) { hideTip(); return; }
      var s = size();
      var sx = n.x * t.k + t.x, sy = n.y * t.k + t.y;
      tip.style.left = "0px"; tip.style.top = "0px"; // measure
      var tw = tip.offsetWidth, th = tip.offsetHeight;
      var left = clamp(sx - tw / 2, 6, Math.max(6, s.w - tw - 6));
      var top = sy + (NODE_H / 2) * t.k + 8;
      if (top + th > s.h - 6) top = sy - (NODE_H / 2) * t.k - th - 8; // flip above
      top = clamp(top, 6, Math.max(6, s.h - th - 6));
      tip.style.left = left + "px";
      tip.style.top = top + "px";
    }
    function showTip(id) {
      var n = nodeById[id];
      if (!n) return;
      openId = id;
      tip.innerHTML = tipHtml(n);
      tip.classList.remove("hidden");
      positionTip(id);
    }
    function hideTip() { openId = null; tip.classList.add("hidden"); }

    // ---- pan / zoom / tap (Pointer Events) ---------------------------------
    var pointers = new Map();
    var last = null, pinch = null, downPos = null, downTarget = null, moved = false;

    svg.addEventListener("pointerdown", function (e) {
      svg.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) {
        last = { x: e.clientX, y: e.clientY };
        downPos = { x: e.clientX, y: e.clientY };
        downTarget = e.target; moved = false;
      } else if (pointers.size === 2) {
        var p = Array.from(pointers.values());
        pinch = { d: dist(p[0], p[1]), mx: (p[0].x + p[1].x) / 2, my: (p[0].y + p[1].y) / 2 };
        last = null;
      }
    });

    svg.addEventListener("pointermove", function (e) {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      var rect = svg.getBoundingClientRect();
      if (pointers.size >= 2 && pinch) {
        var p = Array.from(pointers.values());
        var nd = dist(p[0], p[1]), nmx = (p[0].x + p[1].x) / 2, nmy = (p[0].y + p[1].y) / 2;
        zoomAround(nmx - rect.left, nmy - rect.top, nd / (pinch.d || nd));
        t.x += (nmx - pinch.mx); t.y += (nmy - pinch.my);
        pinch = { d: nd, mx: nmx, my: nmy };
        moved = true; apply();
      } else if (pointers.size === 1 && last) {
        var dx = e.clientX - last.x, dy = e.clientY - last.y;
        if (Math.abs(e.clientX - downPos.x) > 6 || Math.abs(e.clientY - downPos.y) > 6) moved = true;
        t.x += dx; t.y += dy;
        last = { x: e.clientX, y: e.clientY };
        apply();
      }
    });

    function endPointer(e) {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 1) {
        var p = Array.from(pointers.values())[0];
        last = { x: p.x, y: p.y };
      }
      if (pointers.size === 0) {
        if (!moved && downTarget) {
          var g = downTarget.closest ? downTarget.closest(".tnode") : null;
          if (g) showTip(g.getAttribute("data-id"));
          else hideTip();
        }
        last = null; downTarget = null;
      }
    }
    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);

    svg.addEventListener("wheel", function (e) {
      e.preventDefault();
      var rect = svg.getBoundingClientRect();
      var factor = Math.pow(1.0015, -e.deltaY);
      zoomAround(e.clientX - rect.left, e.clientY - rect.top, factor);
      apply();
    }, { passive: false });

    return {
      render: render,
      reset: function () { fit(lastNodes); },
      clear: function () { render(null); }
    };
  };
})();
