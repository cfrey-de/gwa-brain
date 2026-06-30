# GWA Brain — Nachvollziehbares, geerdetes Dokument-Q&A

*🌐 Sprache: [English](README.md) · **Deutsch***

[![Open in Spaces](https://huggingface.co/datasets/huggingface/badges/resolve/main/open-in-hf-spaces-sm.svg)](https://huggingface.co/spaces/carstenfrey/gwa-brain) — **Live-Demo**: Frag einen Beispiel-Datensatz und sieh den Entscheidungsweg.

Stelle Fragen zu deinen Dokumenten — und sieh, **warum** das System so geantwortet hat.
Jede Antwort enthält **nur das, was wirklich in den Dokumenten steht** — mit exakten
Quellenangaben, den **verworfenen Kandidaten (und warum)**, einer ehrlichen Deklaration
dessen, was nicht abgedeckt ist, und — bei Rechnungen — der vollständigen Herleitung. Ziel
ist ein **nachvollziehbarer Entscheidungsweg**, keine Black-Box-Antwort.

**GWA** steht für *Global Workspace Agent* — eine Anspielung (aus dem Eltern-Projekt) auf
die Global-Workspace-Theorie der Kognitionswissenschaft, in der ein gemeinsamer
„Arbeitsraum" der Ort ist, in den Information geschrieben und aus dem gelesen wird. Hier
ist dieser Arbeitsraum das akkumulierende **Gehirn**: ein persistenter Wissensspeicher,
aus dem jede Frage liest und in den jede Antwort zurückschreibt.

Es spricht mit **jedem OpenAI-kompatiblen Endpunkt** — einer gehosteten API oder einem
lokalen Server wie vLLM / Ollama / TGI — für Chat **und** Embeddings; konfiguriere
Endpunkt und Modelle in `.env`. Ein Befehl startet den ganzen Stack:
`docker compose up --build`.

![GWA-Brain-Demo — der Live-Entscheidungsweg: jeder Fakt als behalten oder gestrichen mit Grund, dann die zitierte Antwort](docs/demo.gif)

*Der Live-**Entscheidungsweg** für eine Frage: jeder Kandidat wird behalten oder gestrichen
**mit Grund** gezeigt, die Antwort zitiert ihre Quellen, und der von den Dokumenten nicht
gedeckte Teil wird **als Lücke deklariert** — du siehst also, **wie** die Antwort zustande
kam und was sie ehrlich nicht beantworten konnte. (Konstruierte Illustration; das
gestrichene Item ist ein numerischer Near-Neighbour.)*

---

## TL;DR

- **Nachvollziehbare Antworten** — sieh *warum* das System das antwortet: welche Quellen, welche Fakten behalten, welche **gestrichen (und warum)**, und was es nicht beantworten konnte.
- **Geerdetes Dokument-Q&A** — Antworten enthalten nur, was in deinen Dokumenten steht, mit Quellenangaben.
- **Lücken werden deklariert, nicht überspielt** — Ungedecktes wird benannt, nicht weghalluziniert.
- **Echte Fakt→Fakt-Ableitungsbäume** — bei Rechnungen wird *wie* eine Zahl hergeleitet wurde sichtbar.
- **Ehrlich by design:** belegte Erdung (Stufe 2), nicht bewiesen; *erzwungen* vs. *instruiert* wird offengelegt; noch kein Benchmark im Repo.
- **Läuft überall:** FastAPI + Qdrant + beliebiges OpenAI-kompatibles LLM (gehostet oder lokal), ein `docker compose up`.

---

## Was unterscheidet das — du kannst die Antwort nachvollziehen

Normales RAG liefert dir eine Antwort; es sagt dir selten *warum* diese Antwort, oder was
es ignoriert hat. Der Punkt hier ist ein **einsehbarer Entscheidungsweg**:

- **Jeder Satz soll seine Quelle tragen** (Dokument, Seite, Absatz). Der Formulier-Schritt
  bekommt *nur* die Fakten, die einen Wächter überlebt haben (erzwungen), und wird
  *angewiesen*, nichts darüber hinaus zu ergänzen (Best-Effort — siehe *Ehrliche Reichweite*).
- **Verwerfungen sind sichtbar, mit Grund.** Ein Kandidat, der thematisch nah ist, aber
  eine *andere* Frage beantwortet, wird gestrichen — und gezeigt, samt Begründung. Du
  siehst, was draußen blieb, nicht nur, was reinkam.
- **Überschriften disambiguieren Entitäten.** Jeder Fakt erbt seine Dokument-Überschrift
  als *Scope* fürs Matching, sodass ein Fakt „the operating pressure is 3.7 bar" unter der
  Überschrift „Pump Station P-12" trotzdem „Wie hoch ist der **P-12**-Druck?" beantwortet —
  deterministisch, ohne den Fakt-Text umzuschreiben (siehe `demo/`).
- **Lücken werden deklariert, nicht umschrieben.** Ist ein Teil der Frage nicht gedeckt,
  sagt die Antwort das.
- **Der Graph akkumuliert.** Ein für Frage 3 abgerufener Fakt kann Frage 17 direkt
  belegen, und gemeinsam genutzte Fakten gewinnen Gewicht, das **künftiges Retrieval
  re-rankt** — kein bloßes Bild (siehe *Akkumulation*).
- **Es zeigt die Herleitung, nicht nur die Antwort.** Jede Antwort rendert einen
  Wissensbaum; bei *Ableitungs*-Dokumenten ist dieser Baum eine echte mehrstufige
  Abhängigkeitskette (siehe *Extraktionsmodi & der Abhängigkeitsbaum*).

---

## Ehrliche Reichweite — was das System ist und was nicht

Dieses System bietet **belegte Erdung** („attested"): jeder ausgelieferte Satz lässt sich
auf eine benannte Quelle zurückführen. Es bietet **keine bewiesene Erdung**: es gibt
keinen Compiler oder kein Orakel, das prüft, ob das Dokument *korrekt* ist. Ist ein
Dokument falsch, ist der Fakt falsch — und das System merkt es nicht.

Die Garantie ist daher präzise und eng:

> **„Die Dokumente sagen es so — Quellenkorrektheit vorausgesetzt."**

| ✓ Was die Pipeline erzwingt | ✗ Was es NICHT garantiert |
|---|---|
| Nur vom Wächter behaltene Fakten erreichen die Antwort | Dass die Dokumente korrekt sind |
| Numerische Near-Neighbours werden vetiert und gezeigt | Dass jede gedruckte Zitation korrekt ist (LLM-instruiert) |
| Jede ungedeckte Teil-Anforderung wird als Lücke erkannt | Vollständige Antworten oder Orakel-Beweis (kein Compiler) |

**Erzwungen vs. instruiert.** Die erzwungenen Garantien sind strukturell — nur vom Wächter behaltene Fakten erreichen die Antwort, Stufe B vetiert numerische Near-Neighbours hart, jede ungedeckte Teil-Anforderung wird zur deklarierten Lücke, und Akkumulation re-rankt das Retrieval. Die Teile, die davon abhängen, dass das LLM dem Prompt folgt — **dass jeder Satz seine Zitation tatsächlich druckt, dass nichts außerhalb der gelieferten Fakten ergänzt wird, und dass Lücken in der Prosa benannt werden** — sind *instruiert, Best-Effort und nicht code-validiert*. Dieses README verkauft die instruierten Teile nie als garantiert.

---

## Retrieval: semantische Suche mit deterministischer Absicherung

Meistens rankt ein gutes Embedding-Modell den richtigen Fakt ohnehin nach oben. In einem
kurzen Check mit bge-m3 lag der on-target-Fakt bei **cosine ≈ 0.82** zur Frage gegenüber
**≈ 0.74** für einen numerischen Beinahe-Treffer — er rankte also von allein zuerst. Aber
diese Marge ist **nicht garantiert**: sie schrumpft mit schwächeren Embeddern, längeren
Fakten oder enger beieinanderliegenden Werten, und das Eltern-Forschungsprojekt maß einen
mit der Kompositionstiefe fallenden semantischen Recall (etwa **0.375** flach, **0.167**
tief; exaktes compiler-prüfbares Keying erreicht dort 1.0/1.0 — Dokumente haben keinen
solchen Schlüssel, was sie schwerer macht).

Retrieval ist hier also semantische Suche **plus** eine deterministische Absicherung — und,
ebenso wichtig, **jeder Schritt ist sichtbar**:

1. **Stufe A — breite semantische Suche** (Qdrant, hoher Recall).
2. **Stufe B — Term-Spezifitäts-Filter** (kein LLM): ein Kandidat, der einen Qualifizierer
   teilt (z. B. *Stunden*), aber eine *andere Zahl* trägt als die Anforderung, wird als
   **numerischer Near-Neighbour** markiert und herabgestuft — nie still substituiert.
3. **Stufe C — Wächter** (das Chat-LLM): vetiert die Stufe-B-Near-Neighbours hart und
   entscheidet für jeden anderen Kandidaten keep/strike per semantischer Implikation
   (falsche Entität, Negation, Themendrift). Im Zweifel: streichen — und der Grund wird
   gezeigt.

Was nach A+B+C für eine Teil-Anforderung ungedeckt bleibt, wird als **Lücke** deklariert —
kein Fuzzy-Fallback. Der Wert liegt nicht nur darin, dass ein falscher Fakt gefiltert wird,
sondern dass du **siehst, warum** jeder Kandidat behalten oder gestrichen wurde.

---

## Extraktionsmodi & der Abhängigkeitsbaum

Wie ein Dokument in Fakten zerlegt wird, wählt man **pro Upload** (Dropdown in der UI oder
das Feld `mode` an `/upload/stream`):

| Modus | Was extrahiert wird | Baum-Form |
|---|---|---|
| **factual** | konkrete Fakten (Zahlen, Einheiten, Bedingungen) — Datenblätter, Berichte | Stern: Antwort ← Belege |
| **prose** | Aussagen aus Erzähltext / Dialog / Prosa — Briefe, Literatur | Stern: Antwort ← Belege |
| **auto** *(Default)* | erst factual; fällt auf prose zurück, wenn ein Chunk nichts liefert | Stern: Antwort ← Belege |
| **derivation** | Schritt-für-Schritt-Rechnungen/Argumente **mit ihren Abhängigkeiten** | **tiefer Abhängigkeitsbaum** |

Im **derivation**-Modus extrahiert das Modell jeden Schritt *mit den früheren Schritten,
die er nutzt* (`depends_on`) und baut so einen gerichteten Fakt→Fakt-DAG. Eine Antwort
expandiert dann den Vorgänger-Abschluss des zitierten Fakts, sodass der Wissensbaum eine
echte mehrstufige Kette wird:

```
Profit margin ─► Operating profit ─► Gross profit ─► Revenue
            │                   │               └─► Cost of goods
            │                   └─► Operating expenses
            └─► Revenue
```

![GWA-Brain — ein Ableitungsbaum: profit margin (16%) aus operating profit, gross profit und den Eingangsgrößen, jeder Fakt auf seine Vorgänger zurückgeführt](docs/demo-tree.gif)

*Ein Ableitungslauf: die Antwort bleibt in einem zitierten Fakt geerdet, der Baum zeigt die
Herleitung — `Profit margin ← Operating profit ← Gross profit ← {Revenue, Cost of goods}` —
genau wie es das Dokument sagt. Das ist Nachvollziehbarkeit für Zahlen: nicht nur *was* das
Ergebnis ist, sondern *wie* es aus den Eingangsgrößen folgt.*

Das ist die ehrliche Grenze eines „echt verzweigten Baums": gewöhnliche Dokumente
(Datenblätter, Prosa) nennen **unabhängige** Fakten, ihr Baum ist also ein Stern (Antwort
← Belege). Eine tiefe Fakt-aus-Fakt-Kette entsteht nur, wenn der *Inhalt selbst* eine
Ableitung ist — es gibt kein Orakel, das Abhängigkeiten erfindet (das wäre Stufe 1).

---

## Zwei Ideen im Detail

### 1. Der Term-Spezifitäts-Filter (Stufe B)

Dichtes Retrieval rankt nach Embedding-Cosine. Zwei Fakten, die sich nur in einer Zahl
unter einem geteilten Qualifizierer unterscheiden — „160 cm nach **500** Stunden" vs.
„180 cm nach **100** Stunden" — liegen im Embedding-Raum nah beieinander (hier ≈ 0.85
zueinander). Ein starker Embedder rankt den richtigen oft trotzdem zuerst; aber mit einem
schwächeren Modell, längeren Fakten oder enger beieinanderliegenden Werten kann diese Marge
verschwinden, und die semantische Suche allein reicht dem LLM womöglich den falschen. Diese
Stufe ist die **deterministische Absicherung** — und sie macht die Verwerfung **sichtbar**.

Es ist eine kleine, **LLM-freie** Stufe nach dem breiten Retrieval. Für jede
Teil-Anforderung extrahiert sie die **tragenden Größen** — `(Zahl, Qualifizierer)`-Paare,
deren Qualifizierer ein erkanntes Einheiten-/Bedingungswort ist, z. B. `('500', 'stunden')`
(`quantity_terms` in `gwa/qa/term_filter.py`). Dann pro Kandidat:

- teilt das **gleiche** `(Zahl, Qualifizierer)` → **on-target**;
- teilt den Qualifizierer, aber eine **andere Zahl** → markiert als **numerischer
  Near-Neighbour** (`quantity_conflict`): gleiches Thema, falscher Wert;
- nicht-numerische Anforderung → Rückfall auf lexikalische Token-Überlappung (≥ 2 geteilte
  Tokens oder ≥ 50 % der Anforderungs-Terme).

Ein `quantity_conflict`-Kandidat wird vom Wächter **hart vetiert** (das Eine, worin eine
rein lexikalische Stufe verlässlich gut ist) und als *gestrichener* Kandidat **mit Grund**
gezeigt — die Verwerfung ist also deterministisch **und** sichtbar. Alles andere bleibt dem
semantischen Urteil des LLM-Wächters überlassen. Diese Arbeitsteilung — **Stufe B fängt
numerische Substitution; der Wächter fängt semantische Nicht-Implikation** — spiegelt die
`min_overlap = 2`-Regel des Eltern-Projekts: ein einzelner geteilter (oft stoppwort-naher)
Qualifizierer darf nie genügen, um einen Fakt durch einen anderen zu ersetzen.

### 2. Ableitungs-Provenienz (der tiefe Baum)

Für Dokumente, die eine Ableitung *enthalten* — eine Rechnung, ein verkettetes Argument,
einen Schritt-für-Schritt-Prozess — bittet der **derivation**-Extraktionsmodus das Modell,
geordnete Schritte zurückzugeben, jeden mit einer `depends_on`-Liste der früheren Schritte,
deren Ergebnis er nutzt (`parse_steps` in `gwa/ingestion/fact_parser.py`). Diese Kanten
werden zu einem gerichteten **Fakt → Vorgänger-DAG**, gespeichert neben dem ungerichteten
Co-Usage-Graphen (`add_dependencies` / `dependency_subtree` in `gwa/graph/brain.py`).

Wird eine Frage beantwortet, läuft der **Vorgänger-Abschluss** des zitierten Fakts ab
(`build_tree` in `gwa/qa/pipeline.py`), sodass der Wissensbaum eine echte mehrstufige Kette
wird — z. B. *Umsatzrendite ← Betriebsgewinn ← Rohertrag ← {Umsatz, Herstellungskosten}*.
Die **Antwort bleibt im direkt relevanten Fakt geerdet**; der **Baum zeigt, wie dieser Fakt
hergeleitet wurde**, genau wie es das Dokument sagt. Das ist die Nachvollziehbarkeits-Story
in ihrer schärfsten Form: eine Zahl, die man bis zu ihren Eingangsgrößen zurückverfolgen kann.

Das ist „Provenienz" im belegten (Stufe-2-)Sinn: die Abhängigkeiten sind **das, was der
Text selbst behauptet** („C ist A minus B"), kein Beweis. Es gibt kein Orakel, das
Ableitungen erfindet — das wäre Stufe 1. Gewöhnliche Dokumente (unabhängige Fakten) ergeben
also einen flachen Stern, und nur echter Ableitungs-Inhalt ergibt einen tiefen Baum.

> **Prototyp — ausführbare Provenienz:** `gwa/codegen.py` macht aus so einem Baum lauffähiges
> Python (eine reine Funktion je abgeleiteter Größe, jede mit Quell-Zitat) und prüft es gegen
> die im Dokument genannten Werte — *ausführbare*, aus Dokumenten geerdete Provenienz (das
> Stufe-1-Ende, aber dokument-geerdet). Siehe [ROADMAP](docs/ROADMAP.md); probiere
> `python -m gwa.codegen demo/brain.json "profit margin"`.

---

## Architektur

```
            Browser (responsive UI: Upload · Frage · Antwort+Zitate · Wissensbaum)
                                  │  HTTP / SSE
        ┌─────────────────────────▼──────────────────────────┐
        │              brain  (FastAPI, Python)               │
        │   /upload/stream  /ask/stream  /graph  /brain/reset │
        │                                                     │
        │   Q&A:  Decompose → Retrieve → Guard → Gap → Form   │
        │            │                       │                │
        │   ┌────────▼────────┐     ┌────────▼─────────┐      │
        │   │ NetworkX        │     │  OpenAI-kompat.  │      │
        │   │ Co-Usage +      │     │  LLM-Endpunkt:   │      │
        │   │ Derivation-DAG  │     │  Chat + Embed    │      │
        │   │ + brain.json    │     └──────────────────┘      │
        │   └─────────────────┘                               │
        └─────────────────────────┬──────────────────────────┘
                                  │
                ┌─────────────────▼──────────────────┐
                │  qdrant  (Vektor-DB, Port 6333)     │
                └─────────────────────────────────────┘
```

- **Qdrant** findet (Vektor-Ähnlichkeit, persistent, produktionsreif).
- **NetworkX** erklärt: ein ungerichteter **Co-Usage**-Graph (welche Fakten gemeinsam
  zitiert wurden — seine Gewichte fließen ins Retrieval-Ranking zurück) plus ein
  gerichteter **Derivation**-Graph (Fakt→Vorgänger, für den tiefen Baum).

---

## Schnellstart (Docker)

```bash
cp .env.example .env          # dann LLM-Endpunkt, API-Key und Modelle eintragen
docker compose up --build     # uid 1000 als Default; Hinweis unten für andere Hosts
# http://localhost:8000 öffnen
```

Der Container läuft als Nicht-Root-User. Via docker compose läuft er als deine **Host-uid**
(Default 1000), damit nach `./data` geschriebene Dateien dir gehören (ohne sudo löschbar);
ist dein Host-User nicht 1000, nutze `BRAIN_UID=$(id -u) BRAIN_GID=$(id -g) docker compose
up --build`. (Ein einfaches `docker run` ohne compose nutzt die im Image eingebaute uid
10001.) Der Port wird per Default **nur auf localhost** veröffentlicht (keine Auth —
Single-User-PoC); setze `BRAIN_BIND=0.0.0.0` fürs LAN und `BRAIN_PORT=8080`, falls 8000
belegt ist. (`BRAIN_BIND`/`BRAIN_PORT` steuern das Host-seitige Port-Publishing von Docker
Compose; für ein direktes `python run.py` nutze stattdessen `BRAIN_HOST`/`PORT`.)

Lade eine PDF-/Word-/Textdatei hoch (Modus wählen), stelle eine Frage, beobachte das
Live-Pipeline-Log und den Wissensbaum. Der Header zeigt das wachsende Gehirn: „N facts ·
M documents".

> Eigene Modelle: setze `LLM_BASE_URL`, `GWA_MODEL`, `GWA_EMBED_MODEL` und den API-Key in
> `.env`. Jeder OpenAI-kompatible Chat-+Embeddings-Endpunkt funktioniert — eine gehostete
> API, Mistral oder ein lokaler Server. Beispiele siehe `.env.example`.

## Lokale Entwicklung (ohne Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# Offline-Smoke-Lauf — kein Key, kein Qdrant-Server, deterministisches Mock-Backend:
GWA_MOCK=1 QDRANT_LOCATION=:memory: python run.py      # http://localhost:8000

# die Testsuite (Mock-LLM + lexikalische Embeddings + In-Memory-Qdrant):
pytest -q
```

---

## Gehostete Demo (Hugging Face Space)

Ein Ein-Space-Deployment — echtes Chat-LLM über den Hugging-Face-Router, lexikalische
Embeddings, vorgeladenes Demo-Gehirn (sofortiger Start) — ist in [`hf-space/`](hf-space/)
vorbereitet; siehe [`hf-space/SETUP.md`](hf-space/SETUP.md). Es braucht nur dein `HF_TOKEN`
als Space-Secret. (`GWA_EMBED=lexical` betreibt ein echtes LLM mit dem abhängigkeitsfreien
Embedder, da der HF-Router keine Embeddings-Route hat.)

---

## Wie es funktioniert (die Pipeline)

`gwa/qa/pipeline.py` läuft pro Frage:

1. **Decompose** → die konkreten Teil-Anforderungen, die eine Antwort decken muss (nah am
   Wortlaut der Frage — erfindet keine Definitionen/Formeln, die die Frage nicht verlangt).
2. **Retrieve** → Qdrant Top-k pro Teil-Anforderung, dann der **Term-Spezifitäts-Filter**
   (`gwa/qa/term_filter.py`), dann das **Akkumulations-Re-Ranking**.
3. **Guard** (`gwa/qa/guard.py`) → numerische Near-Neighbours werden hart vetiert; jeder
   andere Kandidat wird vom LLM behalten/gestrichen. Gestrichene Kandidaten erscheinen mit
   Grund.
4. **Gap-Check** → jede Teil-Anforderung ohne deckenden Fakt wird zur deklarierten Lücke.
5. **Formulate** → zitierte Prosa, nur aus behaltenen Fakten.
6. **Accumulate** → zitierte Fakten gewinnen Gewicht + Co-Usage-Kanten (siehe unten); bei
   Ableitungs-Dokumenten expandiert der Baum die Abhängigkeitskette des zitierten Fakts.

Jede Stufe streamt per Server-Sent-Events in die UI — die Demo *zeigt* also den
Entscheidungsweg live: warum jeder Fakt behalten oder gestrichen wird.

## Akkumulation (das tragende Feature)

Jeder Upload lässt das Gehirn dauerhaft wachsen (Fakten aus Dokument A bleiben, wenn
Dokument B kommt). Jede Antwort hinterlässt eine Spur: zitierte Fakten gewinnen **Gewicht**,
gemeinsam zitierte Fakten eine **Co-Usage-Kante**. Dieses Gewicht ist **funktional**, nicht
kosmetisch — es re-rankt künftiges Retrieval:

```
final_score = (1 − w)·(0.6·cosine + 0.4·term_specificity) + w·normalized_graph_weight
```

so überholt ein häufig co-zitierter Fakt einen cosine-gleichen Neuling. Ein Fakt aus einer
Frage kann eine spätere direkt beantworten, ohne erneutes Embedding. (Das unterscheidet das
System von einem zustandslosen RAG-Chat: es hat ein akkumulierendes, gewichtetes Gedächtnis
über Fragen hinweg.)

## Der Wächter, ehrlich

Der Wächter läuft auf dem **gleichen Chat-Modell** wie der Rest (per Default ein
Single-Model-Guard). Das ist eine bewusste, eng umrissene Wahl:

- Die Guard-*Ablation* des Eltern-Projekts (auf eigenen Daten) fand einen Cross-Model-Guard
  **byte-identisch** zum Same-Model-Guard — ein zweites Modell brachte dort nichts.
- Dieselbe Ablation registrierte den semantischen Guard als **unzureichend auf der harten
  Suite** (Precision unter der gelockten 0.85-Schwelle). Das ist also ein **konservativer,
  UNGEMESSENER Produkt-Guard** — er streicht im Zweifel und zeigt, was er strich. Er ist
  **kein** validierter Guard, und dieses README erhebt keinen gemessenen Erdungs-Anspruch.
- Für einen *Mess*-Pfad würde man verschiedene Modelle für Generator / Guard / Judge nutzen,
  um Selbstbewertungs-Zirkularität zu vermeiden. Ein **optionaler Cross-Model-Guard-Hook**
  existiert dafür (`GUARD_CROSS_*` in `.env`), ist aber **per Default aus** und nicht Teil
  der Demo.

---

## Konfiguration

Alle Einstellungen sind Umgebungsvariablen (siehe `.env.example`). Die wichtigen:
`LLM_BASE_URL`, `GWA_MODEL`, `GWA_EMBED_MODEL` und der Chat-API-Key (benannt durch
`LLM_API_KEY_ENV`), plus `QDRANT_HOST` / `QDRANT_PORT` und `BRAIN_DATA_DIR`. Optional:
`GWA_EXTRACT_MODE`, `GWA_TOP_K`, `GWA_ACCUM_WEIGHT`, der `GUARD_CROSS_*`-Hook und
`GWA_MOCK` / `QDRANT_LOCATION` für Offline-Läufe.

## Persistenz & Reset

- **Qdrant-Embeddings** liegen im `qdrant_data`-Docker-Volume — sie überleben
  `docker compose restart` und `docker compose down` (ohne `-v`).
- **Die Graphen + Fakten + brain.json** liegen im host-gemounteten `./data/` — sie
  überleben alles außer manuellem Löschen. Schreibvorgänge sind atomar (Temp-Datei +
  `fsync` + Replace).
- **Selbstheilung:** Wird das Qdrant-Volume gelöscht, aber `./data/brain.json` überlebt
  (z. B. `docker compose down -v`), **re-indiziert** die App die Fakten beim nächsten Start
  aus ihrem gespeicherten Text — die Suche funktioniert weiter. Deshalb ist `down -v`
  allein **kein** vollständiger Reset.
- **Voller Reset:** der „Reset brain"-Button / `POST /brain/reset`, oder lösche
  `./data/brain.json` (und `docker compose down -v` für die Vektoren).

## Grenzen & Sicherheit (PoC-Scope)

Uploads sind begrenzt (`BRAIN_MAX_UPLOAD_BYTES`, Default 25 MB) und werden auf Platte
gestreamt. Der Container läuft als Nicht-Root-User. Es gibt **keine Authentifizierung** —
die App ist per Default an localhost gebunden; setze sie ohne Reverse-Proxy/Auth nicht in
ein nicht vertrauenswürdiges Netz. Ein Reasoning-Modell + ein enges Rate-Limit machen das
Einlesen großer Dokumente langsam; halte Demo-Dokumente klein. Parallele SSE-Streams sind
gedeckelt (`GWA_MAX_STREAMS`, Default 16 → überzählige Anfragen erhalten HTTP 429), und der
Event-Puffer je Stream ist beschränkt (verwirft Events an einen getrennten/langsamen
Client, statt unbegrenzt zu wachsen).

## Projektaufbau

```
gwa/
  config.py · deps.py            # Settings + Client-Verdrahtung (beliebiger OpenAI-kompat. Endpunkt)
  transport.py · llm.py · embedder.py            # OpenAI-kompatibler HTTP-Stack (+ Batching)
  models.py                      # Fact, Candidate, QAResult
  ingestion/  extractor.py · fact_parser.py · ingest.py   # Chunking; factual/prose/auto/derivation
  graph/      brain.py           # Qdrant + NetworkX (Co-Usage + Derivation) + atomares brain.json
  qa/         term_filter.py · retriever.py · guard.py · pipeline.py · prompts.py
  ui/         app.py · static/   # FastAPI + SSE; Vanilla-HTML/CSS/SVG-Baum (Stern + hierarchisch)
tests/                           # Mock-LLM + lexikalische Embeddings + In-Memory-Qdrant
```

Eine Durchsicht jeder Datei und jeder Funktion des gesamten Codes steht in
[`docs/CODE_GUIDE.de.md`](docs/CODE_GUIDE.de.md). Geplante/mögliche Erweiterungen (z. B.
optionaler Chunk-Overlap, ein Evaluations-Benchmark) stehen in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

## Scope (MVP)

Kein Multi-User, keine Auth, kein Cloud-Deploy. Single-User-Demo und Basis für spätere
Domänen-Anwendungen. Provider-agnostisch (beliebiger OpenAI-kompatibler Endpunkt); kein
Fuzzy-Fallback bei Lücken; gestrichene Kandidaten immer sichtbar; die Stufe-2-Garantie
(„belegt") ehrlich gehalten — nie als Stufe 1 verkauft.

---

*Die dem Eltern-Forschungsprojekt zugeschriebenen Retrieval-Zahlen (semantischer Recall
0.375 flach → 0.167 tief; exaktes Keying 1.0/1.0; Cosine-Bänder 0.77–0.85 verschieden /
0.94–0.95 Paraphrase) stammen aus dessen Lauf-Artefakten, nicht aus diesem Repo gemessen.
Die Cosine-Werte des Wasserstand-Beispiels (≈ 0.82 / 0.74 / 0.85) wurden hier mit bge-m3 an
einer konstruierten Illustration gemessen. Einen End-to-End-Benchmark von GWA Brain gibt es
noch nicht.*

---

## Verwandte Arbeiten & Referenzen

GWA Brain ist eine technische **Synthese** von Ideen aus geerdetem / attributiertem
Question-Answering; es erhebt keinen Neuheitsanspruch darüber. Einstiegspunkte zur
Einordnung:

- **Retrieval-augmented generation.** Lewis et al., *Retrieval-Augmented Generation for
  Knowledge-Intensive NLP Tasks*, NeurIPS 2020. — Karpukhin et al., *Dense Passage
  Retrieval for Open-Domain QA*, EMNLP 2020.
- **Answers with citations / attribution.** Gao et al., *Enabling Large Language Models to
  Generate Text with Citations* (ALCE), EMNLP 2023. — Bohnet et al., *Attributed Question
  Answering*, 2022. — Gao et al., *RARR: Researching and Revising What Language Models
  Say*, ACL 2023.
- **Knowing when to abstain / declare a gap.** Kadavath et al., *Language Models (Mostly)
  Know What They Know*, 2022. — Yin et al., *Do Large Language Models Know What They Don't
  Know?*, ACL 2023 (Findings).
- **Self-checking / corrective retrieval.** Asai et al., *Self-RAG*, ICLR 2024. — Yan et
  al., *Corrective Retrieval-Augmented Generation (CRAG)*, 2024. — Jiang et al., *Active
  Retrieval-Augmented Generation (FLARE)*, EMNLP 2023.
- **Graph-structured verification & provenance.** Jin et al., *VeriGraph: Towards
  Verifiable Data-Analytic Agents*, arXiv:2606.16603, 2026 — a neuro-symbolic evidence DAG
  in which a conclusion is verifiable iff every claim traces back through the graph to raw
  data; the closest neighbour to GWA Brain's derivation provenance (see below).
- **Surfacing rejected evidence / decision-path interfaces.** *ContextGuard* (Open-Source
  `llm-contextguard`) — ein Admission-„Gate", das Chunks mit menschenlesbaren Reason-Codes
  verwirft und einen Trace-DAG exportiert; der nächste Verwandte zum *Wächter-Mechanismus*. —
  *PaperTrail*, CHI 2026 (arXiv:2602.21045) — eine Claim-Evidence-Oberfläche, die
  auch „aus der Antwort ausgelassene Claims" sichtbar macht. — Elicit *Strict Screening* —
  liefert verworfene Kandidaten mit Gründen im Literatur-Screening. — Hebbia *Matrix* — ein
  kommerzielles „System of Record for Reasoning", das Analyse-Schritte mit Zitaten nachvollzieht.
- **Numeric robustness.** *RAGShield: Detecting Numerical Claim Manipulation in Government RAG
  Systems*, arXiv:2604.00387, 2026 — zeigt, dass Embeddings das Thema kodieren,
  nicht numerische Präzision (eine Änderung um 50.000 $ ergibt weiterhin Cosine ≈ 0.9998) —
  genau deshalb ist der Stage-B-Filter **deterministisch** statt schwellwertbasiert.
- **LLM as a verifier / judge.** Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and
  Chatbot Arena*, NeurIPS 2023.
- **Hallucination, surveyed.** Ji et al., *Survey of Hallucination in Natural Language
  Generation*, ACM Computing Surveys 2023.
- **The name.** Baars, *A Cognitive Theory of Consciousness* (Global Workspace Theory),
  1988; Dehaene, *Consciousness and the Brain*, 2014.

### Wo sich GWA Brain abhebt

Das sind Unterschiede in **Erzwingung und Umfang**, keine durch Benchmarks belegte
Überlegenheit (das System liefert keine eigene Evaluation — siehe *Der Wächter, ehrlich*):

- **ggü. Vanilla-RAG** — der Formulier-Schritt bekommt *nur* die vom Wächter behaltenen
  Fakten (erzwungen) und wird *angewiesen*, sie zu zitieren und nichts anderes zu ergänzen
  (Best-Effort, nicht code-validiert).
- **ggü. Attributions-Arbeiten** (ALCE, RARR, Attributed QA), die Zitate meist
  *evaluieren* oder *nachträglich korrigieren* — hier sind die Nur-behaltene-Fakten-Eingabe,
  die Lücken-*Erkennung* je Teil-Anforderung und das Stage-B-Veto **im Code erzwungen** (der
  Zitat-Text selbst ist LLM-instruiert), und **gestrichene Kandidaten werden gezeigt**.
- **ggü. Self-/Corrective-RAG** (Self-RAG, CRAG, FLARE), die Retrieval/Kritik *in die
  Kontrolle des LLM* legen (Spezial-Tokens, ein gelernter Kritiker, das Modell entscheidet,
  wann es abruft/revidiert) — GWA Brain hält den Wächter als Stufe, die das Modell **nicht
  überspringen** kann („guarded, not trusted"), und ergänzt einen **deterministischen,
  LLM-freien Term-Spezifitäts-Filter** gezielt gegen **numerische Near-Neighbour-
  Substitution** — ein Fehlermodus, den allgemeine Kritiker nicht direkt adressieren und für
  den Embedding-Ähnlichkeit *blind* ist (RAGShield misst Cosine ≈ 0.9998 bei einer Änderung um
  50.000 $), weshalb die Absicherung deterministisch ist.
- **ggü. Abstention-Arbeiten** — Lücken werden **pro zerlegter Teil-Anforderung** aus der
  Deckung deklariert, nicht über eine einzelne globale Konfidenz-Schwelle.
- **ggü. graph-strukturierter Verifikation (VeriGraph)** — der nächste Verwandte zum
  *Ableitungsbaum*. VeriGraph baut einen **ausführbaren, neuro-symbolischen** Evidenz-DAG,
  in dem eine Schlussfolgerung genau dann verifizierbar ist, wenn sie bis zu den Rohdaten
  zurückverfolgbar ist — *bewiesene* Provenienz, faktisch **Stufe 1**. Die Ableitungs-
  Provenienz von GWA Brain ist bewusst leichter: die `depends_on`-Kanten sind **das, was der
  Dokumenttext behauptet**, keine ausführbaren Berechnungen — *belegte* (**Stufe 2**)
  Provenienz über **beliebige Dokumente**, ohne Code-Ausführung, ohne Orakel. Es tauscht
  VeriGraphs Verifizierbarkeit gegen Allgemeinheit und Einfachheit — und sagt das.
- **ggü. Rejected-Evidence-UIs & Decision-Path-Produkten** — auch das *Zeigen* verworfener
  Kandidaten ist nicht einzigartig. *ContextGuard* kombiniert Reject-mit-Grund + Trace-DAG, ist
  aber eine v0.1-Entwickler-Library (kein End-User-Antwort-UI, keine Lücken-Deklaration, keine
  Zitate); Elicit *Strict Screening* liefert verworfene-mit-Gründen, aber fürs Literatur-
  Screening, nicht allgemeines QA; *PaperTrail* vereint Grounding und eine Ausgelassene-Claims-
  Oberfläche in einem UI, zeigt aber ausgelassene *Quell*-Claims (nicht verworfene *Retrieval-
  Kandidaten* mit Streichungsgrund) und hat keinen Ableitungsbaum; Hebbia *Matrix* ist der
  nächste kommerzielle „Decision Path", traced aber ausgeführte Schritte, nicht verworfene
  Kandidaten, Lücken oder einen numerischen Ableitungs-DAG, und ist Closed Source.

Die wirklich unterscheidenden Teile sind also — unterscheidend **in der Kombination**, nicht
als Erfindungen: (1) ein **einsehbarer Entscheidungsweg** —
jeder behaltene/gestrichene Kandidat mit Grund gezeigt, Lücken deklariert, und (bei
Rechnungen) die Herleitung explizit gemacht; (2) **dokument-gestützte Ableitungs-Provenienz**
als tiefer Baum; (3) ein deterministischer **Term-Spezifitäts-Filter** als Absicherung gegen
numerische Near-Neighbour-Substitution; über (4) einem **akkumulierenden Co-Usage-Graphen**,
der künftiges Retrieval re-rankt. Nichts davon ist hier gebenchmarkt.

---

## Lizenz

Apache License 2.0 — © 2026 Carsten Frey. Siehe [LICENSE](LICENSE) und [NOTICE](NOTICE).
