"""KnowledgeBrain — the accumulating memory.

Two stores, on purpose:
  - Qdrant  : vector similarity search over fact embeddings (finds).
  - NetworkX: a co-usage / provenance graph over facts (explains). Edges are NOT
              compiler-derived dependencies (documents have none) — an edge means
              "these two facts were cited together in an answer". Its weights feed
              BACK into retrieval (accumulation re-rank), so the graph is functional,
              not decorative.

brain.json (facts + graph + doc registry) is the metadata source of truth and is
written atomically under a lock. Qdrant persists vectors in its own volume.
"""
import json
import os
import threading
from pathlib import Path

import networkx as nx

from gwa.models import Fact

BRAIN_VERSION = 1


class KnowledgeBrain:
    def __init__(self, qdrant, embedder, data_dir, collection="gwa_facts"):
        self.qdrant = qdrant
        self.embedder = embedder
        self.collection = collection
        self.data_dir = Path(data_dir)
        self.brain_path = self.data_dir / "brain.json"
        self.facts: dict[str, Fact] = {}     # id -> Fact (authoritative metadata + live weight)
        self.graph = nx.Graph()              # co-usage graph (undirected, accumulation)
        self.deps: dict[str, list] = {}      # fact_id -> [prerequisite fact_ids] (derivation, directed)
        self.docs: dict[str, dict] = {}      # filename -> {name, n_facts, uploaded_ts}
        self._dim = None
        self._saved_embedder = ""            # embedder name recorded in brain.json
        self._lock = threading.RLock()       # guards the in-memory data structures
        self._save_lock = threading.Lock()   # guards the atomic file replace
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.load()

    # ---- collection -------------------------------------------------------
    def _ensure_collection(self, dim):
        from qdrant_client import models
        self._dim = dim
        if not self.qdrant.collection_exists(self.collection):
            self.qdrant.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

    # ---- ingestion --------------------------------------------------------
    def add_facts(self, facts: list) -> int:
        """Embed + store new facts (dedup by id). Returns count of NEW facts.
        The network embed happens outside the lock; only the fast dict/graph/point
        construction is locked."""
        from qdrant_client import models
        with self._lock:
            new = [f for f in facts if f.id not in self.facts]
        if not new:
            return 0
        vectors = self.embedder.embed([f.searchable for f in new])
        if not vectors:
            return 0
        points = []
        with self._lock:
            if self._dim is None:
                self._ensure_collection(len(vectors[0]))
            for f, vec in zip(new, vectors):
                if f.id in self.facts:
                    continue
                self.facts[f.id] = f
                self.graph.add_node(f.id)
                points.append(models.PointStruct(id=f.id, vector=vec, payload=f.to_dict()))
        if points:
            self.qdrant.upsert(collection_name=self.collection, points=points)
        return len(points)

    def add_dependencies(self, fact_id, dep_ids):
        """Record that `fact_id` is derived from `dep_ids` (directed). Used by the
        derivation ingestion mode to build a real fact->fact dependency DAG."""
        with self._lock:
            if fact_id not in self.facts:
                return
            cur = self.deps.setdefault(fact_id, [])
            for d in dep_ids:
                if d in self.facts and d != fact_id and d not in cur:
                    cur.append(d)

    def dependency_subtree(self, root_ids) -> dict:
        """BFS the derivation DAG from the kept facts, returning the prerequisite facts
        (status 'derived') and the directed 'derives' edges that form the deep tree."""
        with self._lock:
            nodes, links, seen = [], [], set(root_ids)
            frontier = list(root_ids)
            while frontier:
                fid = frontier.pop()
                for dep in self.deps.get(fid, []):
                    if dep not in self.facts:
                        continue
                    links.append({"source": fid, "target": dep, "kind": "derives"})
                    if dep not in seen:
                        seen.add(dep)
                        f = self.facts[dep]
                        nodes.append({
                            "id": dep, "type": "fact", "status": "derived",
                            "label": f.text[:48] + ("…" if len(f.text) > 48 else ""),
                            "text": f.text, "source": f.source_label, "reason": "",
                            "weight": round(f.weight, 3), "uses": f.uses,
                        })
                        frontier.append(dep)
            return {"nodes": nodes, "links": links}

    def register_doc(self, name, n_facts, ts):
        rec = self.docs.get(name)
        if rec:
            rec["n_facts"] += n_facts
            rec["uploaded_ts"] = ts
        else:
            self.docs[name] = {"name": name, "n_facts": n_facts, "uploaded_ts": ts}

    # ---- retrieval --------------------------------------------------------
    def search(self, query_text: str, top_k: int):
        """Return list[(Fact, cosine_score)] for the best top_k matches."""
        if self._dim is None or not self.facts:
            return []
        qv = self.embedder.embed([query_text])
        if not qv:
            return []
        resp = self.qdrant.query_points(
            collection_name=self.collection, query=qv[0], limit=top_k, with_payload=True,
        )
        out = []
        with self._lock:
            for p in resp.points:
                fact = self.facts.get(str(p.id))
                if fact is None and p.payload:          # fallback to stored payload
                    fact = Fact.from_dict(p.payload)
                if fact is not None:
                    out.append((fact, float(p.score)))
        return out

    # ---- accumulation -----------------------------------------------------
    def record_usage(self, kept_facts: list, question: str):
        """A fact cited in an answer gains weight; facts cited together gain a co-usage
        edge. Both feed the next question's retrieval re-rank (the accumulation feature)."""
        with self._lock:
            ids = [f.id for f in kept_facts if f.id in self.facts]
            for fid in ids:
                f = self.facts[fid]
                f.uses += 1
                f.weight += 1.0
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    u, v = ids[i], ids[j]
                    if self.graph.has_edge(u, v):
                        self.graph[u][v]["weight"] += 1.0
                    else:
                        self.graph.add_edge(u, v, weight=1.0)
            return ids

    # ---- graph export -----------------------------------------------------
    def _node_view(self, fid):
        f = self.facts.get(fid)
        if not f:
            return {"id": fid, "label": fid[:8], "type": "fact", "source": "", "text": "", "weight": 1.0}
        return {
            "id": fid, "label": f.text[:48] + ("…" if len(f.text) > 48 else ""),
            "type": "fact", "source": f.source_label, "text": f.text,
            "weight": round(f.weight, 3), "uses": f.uses,
        }

    def whole_graph(self) -> dict:
        with self._lock:
            nodes = [self._node_view(n) for n in self.graph.nodes]
            links = [{"source": u, "target": v, "weight": round(d.get("weight", 1.0), 3)}
                     for u, v, d in self.graph.edges(data=True)]
            return {"nodes": nodes, "links": links,
                    "facts": len(self.facts), "documents": len(self.docs)}

    def co_usage_subgraph(self, fact_ids) -> dict:
        with self._lock:
            ids = [i for i in fact_ids if i in self.graph]
            sg = self.graph.subgraph(ids)
            nodes = [self._node_view(n) for n in sg.nodes]
            links = [{"source": u, "target": v, "weight": round(d.get("weight", 1.0), 3)}
                     for u, v, d in sg.edges(data=True)]
            return {"nodes": nodes, "links": links}

    # ---- status -----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                "facts": len(self.facts),
                "documents": len(self.docs),
                "docs": list(self.docs.values()),
            }

    # ---- persistence ------------------------------------------------------
    def save(self):
        with self._lock:
            data = {
                "version": BRAIN_VERSION,
                "embedder": getattr(self.embedder, "name", ""),
                "facts": [f.to_dict() for f in self.facts.values()],
                "graph": nx.node_link_data(self.graph, edges="links"),
                "deps": self.deps,
                "docs": list(self.docs.values()),
            }
        with self._save_lock:
            tmp = self.brain_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())          # durable file contents before the rename
            os.replace(tmp, self.brain_path)
            try:                               # durable rename
                dfd = os.open(str(self.brain_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass

    def load(self):
        if not self.brain_path.exists():
            return
        try:
            with open(self.brain_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            # do NOT silently start empty and let the next save() overwrite the file:
            # preserve the unreadable brain.json for recovery, then start fresh.
            print(f"[brain] could not load {self.brain_path}: {e}")
            try:
                backup = self.brain_path.with_suffix(".json.corrupt")
                os.replace(self.brain_path, backup)
                print(f"[brain] moved unreadable brain.json to {backup}")
            except Exception as be:  # noqa: BLE001
                print(f"[brain] could not back up corrupt brain.json: {be}")
            return
        self.facts = {d["id"]: Fact.from_dict(d) for d in data.get("facts", [])
                      if "id" in d or d.get("text")}
        # rebuild id keys (from_dict recomputes id if missing)
        self.facts = {f.id: f for f in self.facts.values()}
        try:
            self.graph = nx.node_link_graph(data.get("graph", {"nodes": [], "links": []}),
                                            edges="links")
        except Exception:
            self.graph = nx.Graph()
            self.graph.add_nodes_from(self.facts.keys())
        self.deps = {k: list(v) for k, v in data.get("deps", {}).items()}
        self.docs = {d["name"]: d for d in data.get("docs", [])}
        self._saved_embedder = data.get("embedder", "")
        self._reconcile_qdrant()

    def _reconcile_qdrant(self):
        """Make Qdrant consistent with the persisted facts. Normal restart: the Qdrant
        volume still holds the vectors, so we just restore _dim. Desync (e.g. the volume
        was wiped by `docker compose down -v` while ./data/brain.json survived): re-index
        all facts from their persisted text — self-healing, no manual step needed."""
        from qdrant_client import models
        if not self.facts:
            return
        exists, count = False, 0
        try:
            exists = self.qdrant.collection_exists(self.collection)
            if exists:
                count = self.qdrant.count(self.collection).count
                info = self.qdrant.get_collection(self.collection)
                self._dim = info.config.params.vectors.size
        except Exception as e:  # noqa: BLE001
            print(f"[brain] reconcile: could not inspect collection: {e}")
        # embedder changed since the brain was last saved (e.g. GWA_MOCK flipped:
        # e.g. lexical 256-dim <-> an API 1024-dim) -> the old collection is unusable; recreate.
        current = getattr(self.embedder, "name", "")
        if exists and self._saved_embedder and self._saved_embedder != current:
            print(f"[brain] embedder changed ({self._saved_embedder} -> {current}); recreating collection")
            try:
                self.qdrant.delete_collection(self.collection)
            except Exception as e:  # noqa: BLE001
                print(f"[brain] reconcile: delete failed: {e}")
            exists, count, self._dim = False, 0, None
        if exists and count >= len(self.facts):
            return  # vectors present — nothing to do
        print(f"[brain] re-indexing {len(self.facts)} facts into Qdrant "
              f"(collection {'incomplete' if exists else 'missing'}: {count}/{len(self.facts)})")
        try:
            facts = list(self.facts.values())
            vectors = self.embedder.embed([f.searchable for f in facts])
            if not vectors:
                return
            with self._lock:
                if self._dim is None or not exists:
                    self._ensure_collection(len(vectors[0]))
                points = [models.PointStruct(id=f.id, vector=v, payload=f.to_dict())
                          for f, v in zip(facts, vectors)]
            self.qdrant.upsert(collection_name=self.collection, points=points)
        except Exception as e:  # noqa: BLE001 — a self-heal failure must not crash startup
            print(f"[brain] reconcile: re-index failed, serving without vectors "
                  f"(facts re-embed on next successful ingest/restart): {e}")

    # ---- reset ------------------------------------------------------------
    def reset(self):
        with self._lock:
            try:
                if self.qdrant.collection_exists(self.collection):
                    self.qdrant.delete_collection(self.collection)
            except Exception as e:  # noqa: BLE001
                print(f"[brain] reset: qdrant delete failed: {e}")
            self.facts.clear()
            self.graph = nx.Graph()
            self.deps.clear()
            self.docs.clear()
            self._dim = None
            if self.brain_path.exists():
                self.brain_path.unlink()
