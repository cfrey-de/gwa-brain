# GWA Brain — Code-Guide

*🌐 Sprache: [English](CODE_GUIDE.md) · **Deutsch***

Eine Durchsicht jeder Datei und jeder Funktion des Codes. (← zurück zum [README](../README.de.md))

Dieser Guide erklärt **jede Quelldatei und die darin enthaltenen Funktionen/Klassen**, nach Subsystem gruppiert, entlang des Anfrage-Flusses: Konfiguration → HTTP/LLM-Stack → Datenmodell → Ingestion → das Gehirn → Retrieval → die Q&A-Pipeline → die Web-App → die UI → Docker.

Für das *Warum* (Design, Term-Spezifitäts-Filter, Heading-Scope, Ableitungs-Provenienz) siehe das [README](../README.de.md). Dieses Dokument ist das *Was/Wo*.

## Inhalt

- **Konfiguration & Einstiegspunkt** — `gwa/config.py`, `gwa/deps.py`, `run.py`
- **HTTP- / LLM- / Embedding-Stack** — `gwa/transport.py`, `gwa/llm.py`, `gwa/embedder.py`
- **Datenmodell** — `gwa/__init__.py`, `gwa/models.py`
- **Ingestion (Einlesen)** — `gwa/ingestion/extractor.py`, `gwa/ingestion/fact_parser.py`, `gwa/ingestion/ingest.py`
- **Das Gehirn (Qdrant + Graphen + Persistenz)** — `gwa/graph/brain.py`
- **Retrieval & Term-Spezifitäts-Filter** — `gwa/qa/term_filter.py`, `gwa/qa/retriever.py`
- **Q&A-Pipeline, Wächter & Prompts** — `gwa/qa/guard.py`, `gwa/qa/pipeline.py`, `gwa/qa/prompts.py`
- **FastAPI-App & SSE** — `gwa/ui/app.py`
- **Web-UI (Vanilla-HTML/CSS/SVG)** — `gwa/ui/static/tree.js`, `gwa/ui/static/index.html`, `gwa/ui/static/style.css`
- **Docker & Abhängigkeiten** — `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`

---

## Konfiguration & Einstiegspunkt

### `gwa/config.py`

Zentrale Konfigurationsverwaltung, die Umgebungsvariablen ausliest und Einstellungen für den Chat-LLM, Embeddings, die Qdrant-Vektordatenbank und optionale Guard bereitstellt. Unterstützt OpenAI-kompatible Endpunkte (gehostete APIs oder lokale Server wie vLLM/Ollama) mit vernünftigen Standardwerten und Validierung.

- `_env(name, default=None)` — Hilfsfunktion zum Auslesen einer Umgebungsvariablen und deren Rückgabe oder des Standards, falls leer/None.
- `_env_bool(name, default=False)` — Hilfsfunktion zum Auslesen einer Umgebungsvariablen als boolescher Wert und Interpretation von „1", „true", „yes", „on" (Groß-/Kleinschreibung wird nicht beachtet).
- `_env_int(name, default)` — Hilfsfunktion zum Auslesen einer Umgebungsvariablen als Ganzzahl und Rückgabe des Standards bei Parse-Fehler.
- `_env_float(name, default)` — Hilfsfunktion zum Auslesen einer Umgebungsvariablen als Fließkommazahl und Rückgabe des Standards bei Parse-Fehler.
- `Settings` — Dataclass mit allen Konfigurationsfeldern (LLM, Embeddings, Qdrant, Speicher, Abruf-Parameter, Guard-Einstellungen, Mock-Modus).
- `Settings.__post_init__(self)` — Stellt sicher, dass Embeddings auf den Chat-Endpunkt und API-Schlüssel standardmäßig gesetzt werden, wenn nicht explizit überschrieben.
- `Settings.llm_api_key` (property) — Gibt den Chat-API-Schlüssel zurück, indem die Umgebungsvariable mit dem Namen in `llm_api_key_env` gelesen wird.
- `Settings.embed_api_key` (property) — Gibt den Embedding-API-Schlüssel zurück, indem die Umgebungsvariable mit dem Namen in `embed_api_key_env` gelesen wird.
- `Settings.missing(self)` — Gibt eine Liste erforderlicher Konfigurationsfelder zurück, die fehlen (leere Liste im Mock-Modus); wird für die Validierung beim Starten verwendet.
- `Settings.llm_cfg(self)` — Gibt ein Konfigurationswörterbuch für `gwa.llm.make_llm` zurück, einschließlich Provider („mock" oder „openai-compatible"), Modell, maximale Token und Endpunkt-Einstellungen.
- `Settings.embed_cfg(self)` — Gibt ein Konfigurationswörterbuch für das Embeddings-System zurück, einschließlich Embeddings-Typ („lexical" oder „api"), Modell, Batch-Größe und Endpunkt.
- `Settings.guard_cross_cfg(self)` — Gibt das Konfigurationswörterbuch für die optionale Cross-Model-Guard zurück (None, falls deaktiviert), das ein anderes Modell/einen anderen Endpunkt für Sicherheitsprüfungen ermöglicht.
- `get_settings()` — Factory-Funktion, die eine neue Settings-Instanz zurückgibt, die aus Umgebungsvariablen initialisiert wird.

### `gwa/deps.py`

Dependency-Injection-Schicht, die Settings in konkrete Client-Instanzen verdrahtet (LLM, Embedder, Qdrant, optionale Guard). Verwendet einen gemeinsam genutzten RateLimiter, um sowohl Chat- als auch Embedding-API-Aufrufe zusammen zu kontrollieren.

- `build_limiter(settings: Settings) -> RateLimiter` — Erstellt einen Rate Limiter aus der konfigurierten Requests-pro-Sekunde-Einstellung.
- `build_llm(settings: Settings, limiter=None)` — Erstellt den Chat-LLM-Client mit der LLM-Konfiguration aus den Einstellungen und nutzt optional einen gemeinsamen Rate Limiter.
- `build_embedder(settings: Settings, limiter=None)` — Erstellt den Embeddings-Client mit der Embed-Konfiguration und dem API-Schlüssel aus den Einstellungen und nutzt optional einen gemeinsamen Rate Limiter.
- `build_guard_cross(settings: Settings, limiter=None)` — Erstellt einen optionalen zweiten LLM-Client für die Cross-Model-Guard; gibt None zurück, falls deaktiviert.
- `build_qdrant(settings: Settings)` — Erstellt einen QdrantClient mit In-Memory-Standort für Tests oder einem Remote-Host:Port für die Produktion.
- `wait_for_qdrant(client, attempts=60, delay=1.0)` — Blockierender Bereitschaftscheck, der `get_collections()` von Qdrant abfragt, bis er erfolgreich ist oder nach 60 Versuchen fehlschlägt; wird zur Startup-Synchronisierung in Compose-Umgebungen verwendet.

### `run.py`

Lokaler Entwicklungs-Einstiegspunkt, der die FastAPI-App über Uvicorn startet. Konfigurierbarer Host (standardmäßig localhost) und Port (standardmäßig 8000), und unterstützt den Offline-Mock-Modus mit In-Memory-Speicher zum Testen ohne externe Dienste.

---

## HTTP- / LLM- / Embedding-Stack

### `gwa/transport.py`

Bietet gemeinsamen HTTP-Transport für OpenAI-kompatible Endpunkte mit clientseitiger Ratenbegrenzung und automatischer Wiederholungslogik, die Retry-After-Header berücksichtigt. Eine einzelne RateLimiter-Instanz wird zwischen dem LLM und dem Embedder geteilt, um Anbieterratenbeschränkungen für kombinierten Traffic durchzusetzen.

- `class RateLimiter` — Erzwingt ein minimales Pro-Request-Intervall, um ausgehende Anfragen auf eine konfigurierte Rate (Anfragen pro Sekunde) zu begrenzen.
- `RateLimiter.wait()` — Blockiert (über time.sleep) bis die nächste Anfrage unter der Ratenbegrenzung zulässig ist.
- `_retry_delay(headers, attempt, base=1.0, cap=60.0)` — Berechnet exponentielles Backoff mit Jitter, extrahiert Retry-After aus Antwortheadern, falls vorhanden, und begrenzt dies auf 60 Sekunden.
- `post_json(url, payload, api_key=None, limiter=None, max_retries=5, timeout=180)` — POSTet JSON an eine URL, wiederholt automatisch vorübergehende Fehler (429, 5xx, Verbindungsfehler) mit Backoff; wendet Ratenbegrenzung an, falls ein Limiter bereitgestellt wird; gibt das analysierte Antwortwörterbuch zurück.

### `gwa/llm.py`

Bietet einheitlichen LLM-Zugriff über OpenAI-kompatible Chat-/Completions-Endpunkte, mit sowohl einem Live-API-Client als auch einem deterministischen Mock für Tests, der echte Texttransformationen durchführt (Satzaufteilung, Token-Überlap-Filterung, Fakt-Formatierung).

- `extract_json(text: str) -> dict` — Tolerant analysiert JSON aus Modellausgabe, entfernt Markdown-Code-Fences und fällt auf das Extrahieren der ersten {...}-Spanne zurück, falls direktes Parsen fehlschlägt.
- `_content_tokens(text)` — Extrahiert Content-Tokens (Nicht-Stoppwörter, Länge > 1) aus Text, verwendet vom MockLLM für Relevanzfilterung.
- `class OpenAICompatLLM` — Client für einen beliebigen OpenAI-kompatiblen Chat-/Completions-Endpunkt, konfiguriert mit Modell, max_tokens und optionalem Ratenlimiter.
- `OpenAICompatLLM.complete(role, system, user, temperature=None) -> str` — Ruft /chat/completions mit den angegebenen System-/Benutzer-Nachrichten und optionaler Temperaturübersteuerung auf; gibt den Inhalt des Assistenten als String zurück.
- `class MockLLM` — Deterministischer Test-Stub, der auf Basis der Rolle antwortet: 'extract' spaltet Sätze in Fakten auf, 'decompose' spaltet Fragen nach Trennzeichen auf, 'guard' filtert Kandidaten nach Token-Überlap, 'formulate' erstellt zitierte Prosa aus Fakten.
- `MockLLM.complete(role, system, user, temperature=None) -> str` — Gibt rollenspezifische deterministische Ausgabe als JSON-String zurück und führt echte Transformationen durch, damit Tests die vollständige Pipeline üben.
- `make_llm(cfg, limiter=None)` — Fabrik, die entweder MockLLM oder OpenAICompatLLM basierend auf dem Provider-Config-Schlüssel instanziiert; liest API-Schlüssel bei Bedarf aus der Umgebung.

### `gwa/embedder.py`

Bietet Einbettungen als L2-normalisierte Vektoren über OpenAI-kompatible Endpunkte (mit automatischer Batch-Verarbeitung) oder einen deterministischen lexikalischen Hash-basierten Embedder zum Testen ohne externe Abhängigkeiten.

- `tokenize(text)` — Konvertiert Text in Kleinbuchstaben und extrahiert Token mit einem Regex, der Alphanumerika und bestimmte akzentuierte Zeichen erfasst (für deutsche Unterstützung).
- `_l2(v)` — L2-normalisiert einen Vektor so, dass das Skalarprodukt der Kosinus-Ähnlichkeit entspricht.
- `class LexicalEmbedder` — Deterministischer, abhängigkeitsfreier Embedder, der Tokens in einen festen Dimensions-Bag-of-Words-Vektor hasht; wird zum Testen verwendet.
- `LexicalEmbedder.__init__(dim=256)` — Initialisiert mit einer konfigurierbaren Vektordimension (Standardwert 256).
- `LexicalEmbedder.embed(texts)` — Gibt L2-normalisierte Vektoren für eine Liste von Texten zurück, indem jedes Token in eine feste Dimension gehasht wird.
- `LexicalEmbedder._vec(text)` — Interne Methode, die einen Rohvektor erstellt, indem Token-Hashes akkumuliert und normalisiert werden.
- `class OpenAICompatEmbedder` — Ruft einen OpenAI-kompatiblen /embeddings-Endpunkt mit automatischer Batch-Verarbeitung auf, um Anbietergrenzwerte zu beachten; normalisiert alle zurückgegebenen Vektoren auf L2.
- `OpenAICompatEmbedder.__init__(model, base_url, api_key=None, limiter=None, max_retries=5, batch=64)` — Konfiguriert den API-Endpunkt, das Modell und die Batch-Größe (Standard 64 Texte pro Anfrage).
- `OpenAICompatEmbedder.embed(texts)` — Sendet Texte in Batches an die API, sortiert Ergebnisse zur Beibehaltung der Eingabereihenfolge und gibt L2-normalisierte Einbettungsvektoren zurück.
- `make_embedder(cfg, limiter=None, api_key=None)` — Fabrik, die einen LexicalEmbedder (wenn Config „lexical" angibt) oder einen OpenAICompatEmbedder zurückgibt; liest Batch-Größe und Wiederholungsgrenzen aus Config aus.

---

## Datenmodell

### `gwa/__init__.py`

Paketinitialisierung für GWA Brain, ein dokumentgestütztes Q&A-System, das jede Antwort bis zu benannten Quellen mit vollständiger Nachverfolgung der Herkunft zurückverfolgt. Definiert Paketmetadaten und Grounding-Garantien.

- `__version__ = "0.1.0"` — Versionskennung für semantische Versionierung des Pakets.
- `__author__ = "Carsten Frey"` — Autorenangabe des Pakets.
- `__license__ = "Apache-2.0"` — Lizenzkennung.

### `gwa/models.py`

Kernfunktionen für die Faktenextraktion und die Pipeline der Antwortgenerierung: `Fact` (eine quellengebundene Aussage mit Deduplizierung über deterministisches UUID), `Candidate` (ein Fakt unter Bewertung und Filterung) und `QAResult` (das strukturierte Antwortenpaket mit Herkunftsverfolgung).

- `_now()` — Gibt die aktuelle UTC-Zeit im ISO-Format als String zurück; wird als Standard-Factory für Zeitstempelfelder verwendet.
- `fact_id(source_doc: str, text: str) -> str` — Generiert eine deterministische UUID v5 aus einem Dokument- und Textpaar, um inhaltsbasierte Deduplizierung bei der Neuaufnahme von Dokumenten und als Qdrant-Vector-DB-Punkt-ID zu ermöglichen.
- `Fact.__post_init__(self)` — Berechnet automatisch die Fakt-ID, wenn sie nicht bei der Initialisierung angegeben wurde, und stellt sicher, dass jedes Fakt eine stabile, reproduzierbare Kennung hat.
- `Fact.searchable` — Eigenschaft, die den Faktentext mit Dokumentbereich/Überschrift für Embedding und Matching zurückgibt, um den Recall bei Entitätsfragen zu verbessern, während der Text für Antworten sauber bleibt.
- `Fact.source_label` — Eigenschaft, die die Zitierzeichenfolge mit Dokumentname, Seitennummer oder Absatznummer formatiert, je nach verfügbaren Metadaten.
- `Fact.to_dict(self) -> dict` — Konvertiert eine Fakt-Instanz über das Dienstprogramm „dataclass asdict" in ein einfaches Dictionary.
- `Fact.from_dict(cls, d: dict) -> Fact` — Klassenmethode, die ein Fakt aus einem Dictionary rekonstruiert und zur Robustheit nur auf bekannte Dataclass-Felder filtert.
- `Candidate.to_dict(self) -> dict` — Serialisiert Candidate in ein flaches Dictionary, das Faktmetadaten mit Bewertungs- und Filterungsmetadaten kombiniert (score, term_score, final_score, status, reason), wird für Pipeline-Logging und Ergebnisanzeige verwendet.
- `QAResult.to_dict(self) -> dict` — Konvertiert das vollständige Q&A-Ergebnis (Frage, Antwort, Unterbedingungen, Fakten, Lücken, Quellen, Abhängigkeitsgraph) in ein Dictionary.

---

## Ingestion (Einlesen)

### `gwa/ingestion/extractor.py`

Konvertiert Dokumente (PDF, Word, Text/Markdown) in logische Textabschnitte (~300 Token) mit stabilen Zitaten (Seitennummer für PDFs, ansonsten Absatzindex). Abschnitte respektieren Absatz- und Überschriftengrenzen, um kohärente Einheiten zu bewahren.

- `Chunk` — Dataclass, der einen einzelnen extrahierten Textabschnitt mit Quelldokumentreferenz, Index, optionalen Seiten-/Absatzmetadaten und optionalem Dokumentkontext (Überschrift/Titel) zur Auflösung impliziter Faktsubjekte darstellt.
- `_ntok(text: str) -> int` — Zählt Wort-Token durch Aufteilung auf Leerzeichen; wird verwendet, um Abschnittgrößen gegen den Ziel-Token-Grenzwert zu messen.
- `_doc_heading(units)` — Extrahiert den Titel/die Überschrift des Dokuments aus der ersten Einheit, falls sie so aussieht (kurz, keine Endsetzung); wird als Kontext verwendet, um implizite Faktenverweise aufzulösen.
- `_pack(units, source_doc, target=TARGET_TOKENS, context=None)` — Gruppiert Absätze in Abschnitte von ~300 Token; gibt eine Liste von Chunk-Objekten mit stabilen Abschnitts-IDs und Zitiermetadaten zurück.
- `_pdf_units(path)` — Extrahiert Absätze aus einer PDF-Datei über pdfplumber und ordnet jeden Absatz seiner Seitennummer zu; gibt (units_list, page_count) zurück.
- `_docx_units(path)` — Extrahiert Absatztexte aus einem Word-Dokument über python-docx; gibt (units_list, None) zurück.
- `_text_units(path)` — Extrahiert durch Doppelzeilenumbrüche getrennte Absätze aus Text- oder Markdown-Dateien; gibt (units_list, None) zurück.
- `extract(path, filename)` — Haupteinstiegspunkt; leitet zur entsprechenden Extraktionsfunktion nach Dateiendung (.pdf, .docx, .txt, .md, .markdown, .text) weiter und gibt (chunks, page_count) zurück oder raises ValueError für nicht unterstützte Typen.

### `gwa/ingestion/fact_parser.py`

Extrahiert atomare Fakten aus Chunk-Text über ein LLM mit drei Parsing-Modi: "factual" (konkrete Zahlen/Einheiten/Bedingungen), "prose" (erzählende Aussagen), und "auto" (versucht zuerst factual, fällt auf prose zurück, falls leer). Konservatives Design: Parsing-Fehler ergeben keine Fakten, niemals Halluzinationen.

- `_extract(chunk_text: str, llm, system: str) -> list` — Ruft das LLM auf, um Fakten mithilfe einer System-Eingabe zu extrahieren, analysiert die JSON-Antwort und dedupliziert Faktenzeichenfolgen; gibt bei Fehlern oder fehlgeformter Antwort stillschweigend eine leere Liste zurück.
- `parse_facts(chunk_text: str, llm, mode: str = "auto") -> list` — Extrahiert und gibt eine deduplizierte Liste von Faktenzeichenfolgen aus einem Abschnitt zurück, mit Fallback-Logik: im "auto"-Modus wird die Prose-Eingabe erneut versucht, falls keine Fakten mit der factual-Eingabe gefunden werden.
- `parse_steps(text: str, llm) -> list` — Derivation-Modus: Extrahiert geordnete Schritte mit ids, Text und Abhängigkeiten aus einem vollständigen Dokument; beschränkt Abhängigkeiten auf frühere, zuvor gesehene Schritt-IDs; gibt bei Parsing-Fehler oder fehlgeformter Antwort eine leere Liste zurück.

### `gwa/ingestion/ingest.py`

Orchestriert die vollständige Ingestion-Pipeline (Dokument → Abschnitte → Fakten → Gehirn-Mutation) als Generator, der Progress-Events (start, chunk, done) für das Streaming zu SSE-Clients und Testverbrauch liefert.

- `_now()` — Gibt die aktuelle UTC-Zeit als ISO 8601-Zeichenfolge für Event-Zeitstempel zurück.
- `ingest_document(path, filename, brain, llm, extract_mode="auto")` — Generator, der ein Dokument in Abschnitte extrahiert, Fakten aus jedem Abschnitt analysiert (oder Schritte im Derivation-Modus), sie zum Gehirn hinzufügt und Progress-Events (start, chunk*, done) liefert; mutiert das Gehirn-Objekt und speichert es.
- `_ingest_derivation(chunks, filename, brain, llm)` — Handler für Spezial-Modus, der das gesamte Dokument als eine Derivation behandelt, voneinander abhängige Schritte analysiert, Fakten mit aufgelösten Abhängigkeiten erstellt und ein einzelnes Chunk-Event liefert; gibt die Anzahl neu hinzugefügter Fakten zurück.
- `ingest_collect(path, filename, brain, llm, extract_mode="auto") -> dict` — Synchroner Wrapper, der den ingest_document-Generator leert und das finale `done`-Event zurückgibt; wird von Tests und nicht-Streaming-Kontexten verwendet.

---

## Das Gehirn (Qdrant + Graphen + Persistenz)

### `gwa/graph/brain.py`

Persistentes Speichersystem zur Ansammlung von Fakten und ihren Co-Usage-Mustern. Verwaltet eine Dual-Store-Architektur: Qdrant für die Vektorähnlichkeitssuche und NetworkX für einen Co-Usage-Graphen, bei dem Kantenwichte widerspiegeln, wie oft Fakten gemeinsam zitiert werden; der Graph wird für das Abrufen als Umranking-Signal zurückgeführt.

- `class KnowledgeBrain` — Der zentrale im Speicher+persistent gespeicherte Wissensspeicher. Verwaltet Fakten-Metadaten, Einbettungen in Qdrant, einen Co-Usage-Graphen, Ableitungsabhängigkeiten und eine Dokumentregistrierung; ist thread-sicher durch RLock für Datenstrukturen und einen separaten Sperr-Lock für atomare Dateischreibvorgänge.

- `__init__(self, qdrant, embedder, data_dir, collection="gwa_facts")` — Initialisiert das Gehirn durch Einrichtung von Client-Referenzen, Datenverzeichnis und speicherinternen Strukturen (facts dict, graph, deps, docs), dann lädt aus persistiertem `brain.json` falls vorhanden.

- `_ensure_collection(self, dim)` — Erstellt eine Qdrant-Sammlung, falls sie nicht vorhanden ist, dimensioniert für die angegebene Einbettungsdimension.

- `add_facts(self, facts: list) -> int` — Bettet eine Liste neuer Fakten ein und speichert sie (dedupliziert nach id) sowohl in Qdrant als auch im speicherinternen Graphen; gibt die Anzahl neu hinzugefügter Fakten zurück. Die Einbettung erfolgt außerhalb der Sperre für bessere Performance.

- `add_dependencies(self, fact_id, dep_ids)` — Zeichnet gerichtete Ableitungskanten von `fact_id` zu Voraussetzungsfakten auf, konstruiert einen Fakten-zu-Fakten-Abhängigkeits-DAG, der von `dependency_subtree()` verwendet wird.

- `dependency_subtree(self, root_ids) -> dict` — BFS den Ableitungs-DAG ab gegebenen Root-Fakten, um alle Voraussetzungsfakten und die „derives"-Kanten zu sammeln; gibt eine Knoten-/Link-Struktur zur Visualisierung zurück.

- `register_doc(self, name, n_facts, ts)` — Registriert oder aktualisiert einen Dokumentdatensatz mit Faktenanzahl und Upload-Zeitstempel; wird verwendet, um die Quelldokumente zu verfolgen.

- `search(self, query_text: str, top_k: int)` — Bettet die Abfrage ein und gibt die top_k Fakten nach Cosinus-Ähnlichkeit von Qdrant mit Scores zurück.

- `record_usage(self, kept_facts: list, question: str)` — Erhöht das Gewicht und die Verwendungsanzahl auf zitierten Fakten; fügt hinzu oder verstärkt Kanten im Co-Usage-Graphen zwischen allen Paaren zitierter Fakten; gibt Liste der aktualisierten Fakten-Ids zurück (die Akkumulationsfunktion).

- `_node_view(self, fid)` — Wandelt eine Fakten-ID in ein Ansicht-Dict mit label, text, source, weight für Graphen-Export um.

- `whole_graph(self) -> dict` — Exportiert den vollständigen Co-Usage-Graphen (alle Knoten und Kanten) mit Metadaten (Faktenanzahl, Dokumentanzahl).

- `co_usage_subgraph(self, fact_ids) -> dict` — Extrahiert und exportiert den induzierten Teilgraphen über eine Liste von Fakten-IDs, wobei Kantenwichte erhalten bleiben.

- `status(self) -> dict` — Gibt eine Zusammenfassung der Faktenanzahl, Dokumentanzahl und Liste aller Dokumente zurück.

- `save(self)` — Serialisiert Fakten, Graphen, Abhängigkeiten und Dokumentregistrierung atomar in `brain.json` unter Verwendung einer temporären Datei + fsync + atomarer Umbennung, was Dauerhaftigkeit auch bei Absturz gewährleistet.

- `load(self)` — Deserialisiert `brain.json` in den Speicher und stellt den Co-Usage-Graphen wieder her; bei Parse-Fehler sichert die beschädigte Datei nach `.corrupt` und startet neu; ruft dann `_reconcile_qdrant()` auf, um Qdrant zu synchronisieren.

- `_reconcile_qdrant(self)` — Überprüft, ob die Qdrant-Sammlung vorhanden ist und die korrekte Dimension hat; wenn sich der Embedder geändert hat, erstellt die Sammlung neu; wenn Vektoren fehlen oder unvollständig sind, bettet alle Fakten erneut ein und upserted sie (Selbstheilung nach Qdrant-Volumenverlust).

- `reset(self)` — Löscht alle speicherinternen Daten (facts, graph, deps, docs), löscht die Qdrant-Sammlung und entfernt `brain.json`.

---

## Retrieval & Term-Spezifitäts-Filter

### `gwa/qa/term_filter.py`

Implementiert einen deterministischen Term-Spezifitäts-Filter (Stufe B), der verhindert, dass semantische Ähnlichkeit ähnliche Fakten verwechselt, indem numerische Größen und ihre Qualifizierer verglichen werden. Der Filter bewertet Kandidaten basierend auf Inhaltsüberlappung und markiert numerische Nachbarn (gleicher Qualifizierer, unterschiedliche Zahl), um eine Verwechslung unterschiedlicher Fakten zu verhindern.

- `content_tokens(text)` — Extrahiert Nicht-Stoppwort-Token (>1 Zeichen) aus Text in Kleinbuchstaben; wird als Grundlage für die Inhaltsüberlappungsbewertung zwischen Anforderungen und Kandidaten verwendet.

- `numbers(text)` — Extrahiert alle numerischen Werte aus dem Text und normalisiert Komma- und Periodenseparatoren auf Punkte zum Vergleich.

- `quantity_terms(text)` — Gibt (Zahl, Qualifizierer)-Paare zurück, wobei ein Qualifiziererwort (Einheit oder Messgröße) unmittelbar vor oder nach einer Zahl steht; erfasst die tragenden numerischen Bedingungen in einem Fakt.

- `_score_one(req: str, cand: str)` — Bewertet ein einzelnes Anforderungs-Kandidaten-Paar und gibt (term_score, on_target, covers, conflict) zurück: on_target zeigt strikten Filterdurchsatz an (hohe Abdeckung oder übereinstimmende Zahlen), covers zeigt nachsichtige Abdeckung für Lückenattribution an, und conflict markiert numerische Nachbarn (gleicher Qualifizierer, unterschiedliche Zahl).

- `term_specificity_filter(candidates, sub_requirements)` — Mutiert jeden Kandidaten durch Berechnung von term_score (beste Übereinstimmung über alle Teil-Anforderungen), covers (Liste von übereinstimmenden Teil-Anforderungsindizes), on_target (strikter Filterdurchsatz) und quantity_conflict (abgelehnter Nachbar ohne Abdeckung).

### `gwa/qa/retriever.py`

Orchestriert zweiteilige Abrufung: breite semantische Suche (Stufe A) über Qdrant-Vektoren, Term-Spezifitäts-Filterung (Stufe B) zur Bewertung der Inhaltsausrichtung und Akkumulationsgewichts-Neuranking, das semantische und Term-Scores mit Graphzitiergewicht verbindet, um sowohl hochähnliche als auch häufig gemeinsam zitierte Fakten hervorzuheben.

- `_broad_search(brain, sub_requirements, top_k)` — Führt die Vereinigung von Per-Teilanforderungs-Semantiksuchen gegen das Gehirn (Qdrant) durch, dedupliziert nach Fakt-ID und behält den höchsten Kosinus-Score pro Fakt.

- `_apply_accumulation(candidates, weight)` — Wendet die endgültige Bewertungsformel an: base_score = 0.6×cosine + 0.4×term_score, dann mischt mit normalisiertem Graphgewicht über weight-Parameter, um semantische Relevanz gegen Zitationshäufigkeit auszugleichen.

- `retrieve(brain, sub_requirements, settings)` — Haupt-Abrufungseingangspunkt, der broad_search aufruft, Term-Spezifitäts-Filterung anwendet, Akkumulationsscores berechnet, nach on_target-Strenge dann final_score (beste zuerst) sortiert und top_k-Kandidaten zurückgibt; stellt sicher, dass abdeckende Fakten nicht durch höherwertige Kosinus-Off-Target-Nachbarn gekürzt werden.

---

## Q&A-Pipeline, Wächter & Prompts

### `gwa/qa/guard.py`

Implementiert Stufe C — die semantische Wache, die Kandidaten durch Erkennung von Nicht-Entailment und Topic-Drift in beibehaltene/verworfene aufteilt. Lehnt numerische Nachbarn hart ab (quantity_conflict), während andere semantische Entscheidungen an das LLM mit optionaler Cross-Modell-Verifikation delegiert werden.

- `_verdicts(llm, sub_requirements, candidates)` — Sendet Kandidaten an das LLM mit einem Guard-Prompt und extrahiert JSON-Verdikt, das kurze Ganzzahl-Indizes auf {keep, reason} Paare abbildet; gibt ein leeres dict bei Parsing-Fehlern zurück (konservativer Standard ist Ablehnung).

- `guard(candidates, sub_requirements, llm, guard_cross=None)` — Teilt Kandidaten in (kept, struck) Listen auf, indem zuerst quantity_conflict überprüft wird (hard veto), dann das LLM für semantische Abdeckungs-Verdikt abgefragt wird, und optional sekundäre Cross-Modell-Bestätigung erforderlich ist; verändert status und reason Felder bei jedem Kandidaten.

### `gwa/qa/pipeline.py`

Die Haupt-Q&A-Pipeline orchestriert sechs Stufen: Frage zerlegen → Kandidaten abrufen → Guard-Filter → Lücken erkennen → Antwort formulieren → Nutzung akkumulieren. Gibt Events bei jeder Stufe für Live-SSE-Streaming aus und gibt ein komplettes QAResult mit Antwort, Quellen, Abhängigkeitsbaum und Herkunftsangaben zurück.

- `decompose(question, llm)` — Teilt eine Frage über LLM in konkrete Unterforderungen auf; gibt die ursprüngliche Frage zurück, wenn die Zerlegung fehlschlägt oder keine gültigen Teile erzeugt.

- `gap_check(sub_requirements, kept)` — Gibt die Liste der Unterforderungen zurück, die von keinem beibehaltenen Kandidaten's `covers` Metadaten abgedeckt sind.

- `formulate(question, kept, gaps, llm)` — Generiert die endgültige Antwort, indem das LLM aufgefordert wird, nur die beibehaltenen Fakten mit Zitaten zu synthetisieren und unabgedeckte Lücken zu deklarieren; fällt auf ein reines Quellen-Format zurück, wenn die Formulierung fehlschlägt.

- `_node(c, status)` — Erstellt ein Knoten-Dict für den Abhängigkeitsbaum aus einem Kandidaten und Status-String, wobei die Beschriftung auf 48 Zeichen gekürzt wird.

- `build_tree(answer, kept, struck, gaps, brain)` — Erstellt einen vollständigen Herkunftsbaum mit Antwortknoten, beibehaltenen/verworfenen/Lücken-Knoten, Abhängigkeitslinks aus dem Brain und Co-Nutzungs-Kanten; dedupliziert Knoten, sodass ein verworfener Fakt, der als Abhängigkeitsvoraussetzung angezeigt wird, nicht wiederholt wird.

- `run(question, brain, llm, settings, guard_cross=None, emit=None)` — Orchestriert alle sechs Pipeline-Stufen, gibt Events nach jeder aus, zeichnet Nutzungsstatistiken über `brain.record_usage()` auf und gibt das QAResult mit vollständigem Baum und Quellenverfolgung zurück.

- `ask(question, brain, llm, settings, guard_cross=None)` — Praktischer synchroner Wrapper um `run()` für Tests und einfache Aufrufer.

### `gwa/qa/prompts.py`

Zentralisiert alle LLM-Prompts und ihre Builder-Funktionen; Prompts sind englischsprachige Anweisungen, die das Modell anweisen, in der gleichen Sprache wie die Eingabe auszugeben (Deutsche Dokumente → Deutsche Fakten, englische Dokumente → englische Fakten).

- `EXTRACT_SYSTEM` — Systemprompt für Factual-Modus: extrahiert eigenständige Fakten aus Textabschnitten mit strikten Regeln (ein Satz pro Fakt, genaue Zahlen/Einheiten, keine Interpretation).

- `PROSE_EXTRACT_SYSTEM` — Systemprompt für Prosa-/Erzählmodus: extrahiert Schlüsselaussagen und dargestellte Handlungen ohne Interpretation oder moralisches Urteil.

- `DERIVATION_EXTRACT_SYSTEM` — Systemprompt für Ableitungs-/Berechnungsmodus: extrahiert geordnete Schritte mit expliziten Abhängigkeitsdeklarationen (id, text, depends_on).

- `DECOMPOSE_SYSTEM` — Systemprompt für Frage-Zerlegung: zerlegt eine Frage in minimale Unterforderungen, bleibt der Formulierung treu, lehnt Lehrbuchkenntnisse und nicht geforderte Formeln ab.

- `GUARD_SYSTEM` — Systemprompt für die semantische Wache: bewertet, ob jeder Kandidat einen Unterforderung inhaltlich abdeckt (nicht nur thematische Ähnlichkeit), mit Standardwert false im Zweifelsfall.

- `build_guard_user(requirements, candidates)` — Serialisiert Anforderungen und Kandidaten (mit kurzen Indizes) in eine JSON-Benutzernachricht für das Guard-LLM.

- `FORMULATE_SYSTEM` — Systemprompt für Antwort-Formulierung: weist das Modell an, nur die verifizierten Fakten mit Zitaten in eckigen Klammern zu synthetisieren, Lücken ehrlich zu deklarieren und die Eingabesprache zu verwenden.

- `build_formulate_user(question, facts, gaps)` — Serialisiert Frage, Fakten (mit Text/Quellen-Tupeln) und Lücken in eine JSON-Benutzernachricht für das Formulierungs-LLM.

---

## FastAPI-App & SSE

### `gwa/ui/app.py`

Dieses Modul implementiert eine FastAPI-REST-API mit Server-Sent-Events (SSE)-Streaming für Dokument-Uploads und Q&A-Operationen. Es verwendet eine Threading-Architektur, bei der blockierende Modellaufrufe in einem separaten Thread-Pool ausgeführt werden und Ereignisse in eine asyncio-Queue ausgeben, die die SSE-Antwort ablässt und blockierende Operationen vom Stilllegen der Event-Schleife abhält.

- `lifespan(app: FastAPI)` — Async-Kontext-Manager, der den Lebenszyklus der FastAPI-App initialisiert: validiert die Konfiguration, erstellt das LLM, den Embedder, die Vektordatenbank (Qdrant) und das Wissensnetzwerk, richtet das Upload-Verzeichnis ein, erstellt eine Schreibsperre zum Serialisieren von Gehirnmutationen und erzeugt einen dedizierten ThreadPoolExecutor für blockierende Stream-Worker; stellt die Qdrant-Bereitschaft vor dem Serving sicher.

- `_sse_payload(ev) -> str` — Formatiert ein Ereigniswörterbuch als SSE-Datenzeile (JSON-serialisiert mit `data:` Präfix und doppeltem Zeilenumbruch).

- `_client_error(e: Exception) -> str` — Konvertiert Ausnahmen in benutzerfreundlichen Fehlertext; gibt die Ausnahmemeldung für ValueError (sichere/hilfreiche Fehler) zurück und protokolliert andere Ausnahmen serverseitig, bevor eine allgemeine Meldung zurückgegeben wird, um das Durchsickern interner Details zu vermeiden.

- `async def _guarded_sse(app: FastAPI, produce)` — Core-Async-Generator, der eine blockierende Producer-Funktion zu SSE-Ausgabe überbrückt; führt den Producer in einer separaten Aufgabe aus, die die Schreibsperre für die gesamte Operation hält, um sicherzustellen, dass das Gehirn niemals gleichzeitig mutiert wird; verwirft SSE-Ereignisse, wenn der Consumer zu langsam ist (voller Puffer), anstatt den Worker-Thread zu blockieren und einen Deadlock zu riskieren.

- `async def index()` — Bedient die statische Datei index.html als Root-Endpunkt.

- `async def healthz()` — Einfacher Health-Check-Endpunkt, der `{"ok": True}` zurückgibt.

- `async def brain_status(request: Request)` — Gibt den aktuellen Status des Wissensnetzwerks (Faktenzahl, Sammlungsinformationen usw.) zurück, indem `brain.status()` in einem Thread aufgerufen wird.

- `async def graph(request: Request)` — Gibt das gesamte Wissensgraph als JSON-serialisierbare Struktur über `brain.whole_graph()` zurück.

- `async def brain_reset(request: Request)` — Löscht alle Fakten und Einbettungen aus dem Wissensnetzwerk; akquiriert die Schreibsperre während der Operation, um gleichzeitige Mutationen zu verhindern.

- `_safe_name(raw) -> str` — Bereinigt hochgeladene Dateinamen, indem der Basisname extrahiert und Null-Bytes entfernt werden; gibt "upload.txt" für leere oder ungültige Namen zurück.

- `async def upload_stream(request: Request, file: UploadFile, mode: str)` — Akzeptiert einen Datei-Upload und streamt den Erfassungsfortschritt als SSE-Ereignisse zurück; validiert die Dateigröße gegen `max_upload_bytes`, schreibt die Datei in begrenzte 1-MB-Blöcke auf die Festplatte, um OOM zu verhindern, und führt dann die Dokumenterfassung (Faktextraktion, Einbettung, Vektor-Speicherung) über `ingest_document()` mit dem angegebenen Extraktionsmodus (auto, factual, prose, derivation) durch.

- `AskBody` — Pydantic-Modell für den `/ask/stream`-Request-Body mit einem `question`-String.

- `async def ask_stream(request: Request, body: AskBody)` — Akzeptiert eine Frage und streamt Q&A-Pipeline-Ergebnisse als SSE-Ereignisse zurück; führt die vollständige Antwort-Pipeline (Abruf, Ranking, Cross-Guard-Validierung, LLM-Synthese) über `run_pipeline()` aus und gibt Fortschrittsereignisse aus.

- `main()` — Einstiegspunkt für `python -m gwa.ui.app`; startet den Uvicorn-ASGI-Server auf dem Host und Port, die von den Umgebungsvariablen `BRAIN_HOST` (Standard 127.0.0.1) und `PORT` (Standard 8000) angegeben werden.

---

## Web-UI (Vanilla-HTML/CSS/SVG)

### `gwa/ui/static/tree.js`

Rendert eine interaktive SVG-basierte Knoten-Link-Visualisierung eines Abhängigkeitsbaums (hierarchisch, beantwortet eine Frage) oder eines Co-Usage-Graph-Überblicks (kreisförmiges Layout). Unterstützt Verschiebung, Zoom (Mausrad + Desktop-Ziehen, Zwei-Finger-Pinch auf Touch) und Tooltips beim Klick/Tippen auf Knoten. Verwendet einfache SVG ohne externe Bibliotheken.

**Public API:**
- `GWATree(hostElement)` — Factory-Funktion, die den Tree-Controller zurückgibt; initialisiert SVG-, Viewport-, Platzhalter- und Tooltip-Elemente im Host.
- `tree.render(treeData)` — rendert Knoten und Links aus `{nodes: [...], links: [...]}` Daten; null/leer zeigt Platzhalter; wählt automatisch hierarchisches oder kreisförmiges Layout basierend auf Link-Typen.
- `tree.reset()` — zentriert neu und setzt die Zoomstufe zurück, um alle Knoten in der Ansicht zu passen.
- `tree.clear()` — leert den Baum und zeigt die Standard-Platzhalternachricht.

**Internal layout & rendering helpers:**
- `layout(data)` — kreisförmiges/radiales Layout für Co-Usage-Graphen: Antwort im Zentrum, behaltene Fakten links, durchgestrichene Fakten rechts, Lücken weit rechts; für Überblick (kein Antwort-Knoten) ordnet nur verbundene Fakten in einem Kreis an.
- `layoutHier(data)` — hierarchisches Top-Down-Baum-Layout mit Wurzel am Antwort-Knoten; verwendet längsten-Pfad-Tiefentraversal zur Positionierung gemeinsamer Voraussetzungen, hält durchgestrichene Fakten und Lücken in Seitenspalten; gibt beide Knoten und Kanten mit Parent-Child-Direktiven zurück.
- `draw(nodes, links)` — rendert flachen Co-Usage-Graphen mit einfachen Linien; keine Pfeilspitzen oder Hierarchie.
- `drawHier(nodes, edges, links)` — rendert hierarchischen Baum; gestrichelte Linien für durchgestrichene/Lücken-Links, durchgehende Linien mit Pfeilspitzen für Support/Ableitungs-Kanten; lässt Co-Usage-Kanten zur Klarheit weg.
- `fit(nodes)` — zoomt und verschiebt, um alle Knoten mit Abstand in der Ansicht zu passen, clampt die Skala zwischen 0.05–1.4.
- `appendNode(n)` — erstellt eine SVG-Gruppe mit abgerundeter Rechteck und Textbeschriftung, wendet CSS-Klasse für Node-Typ an und fügt zum Knoten-Container hinzu.
- `nodeClass(n)` — gibt CSS-Klasse (`tnode-answer`, `tnode-kept`, `tnode-struck`, `tnode-gap`, `tnode-derived`, oder `tnode-fact`) basierend auf Node-Typ und Status zurück.
- `linkClass(l)` — gibt CSS-Klasse (`tlink-support`, `tlink-derives`, `tlink-struck`, `tlink-gap`, `tlink-cousage`) basierend auf Link-Art zurück.

**Transform & viewport:**
- `apply()` — wendet die aktuelle Transformation (translate + scale) auf den Viewport an und repositioniert den Tooltip, wenn offen.
- `zoomAround(px, py, factor)` — zoomt um einen Punkt (z.B. Mauszeiger) durch Anpassung der Skala und Verschiebung; clampt die Skala auf 0.15–4.
- `size()` — gibt die Client-Breite/Höhe des Containers zurück (oder Fallback 600x400).

**Tooltip:**
- `showTip(id)` — zeigt Tooltip für einen Knoten mit Quelle, Text, Grund (falls durchgestrichen), Gewicht/Verwendungs-Metadaten.
- `positionTip(id)` — positioniert Tooltip neben Knoten, klappt nach oben, wenn es unten überläuft.
- `hideTip()` — verbirgt Tooltip und löscht die offene Node-ID.
- `tipHtml(n)` — generiert HTML für Tooltip-Inhalte mit HTML-escapten Node-Daten.

**Pan & zoom interaction (Pointer Events):**
- `pointerdown` — erfasst Zeiger, verfolgt Ein-Finger-Ziehen (Verschiebung) oder Zwei-Finger-Pinch (Zoom); speichert Ausgangsposition, um Verschiebung von Tippen zu unterscheiden.
- `pointermove` — bearbeitet Ziehen (Verschiebung bei einem Zeiger) oder Pinch (Zoom bei zwei Zeigern); aktualisiert Position und wendet Transformation an.
- `endPointer(e)` — gibt Zeiger frei; wenn nicht verschoben und Ziel ist ein Knoten, zeigt Tooltip; andernfalls verbirgt es ihn.
- `wheel` — Mausrad-Zoom zentriert beim Cursor; verhindert Standard und wendet glatten Zoom-Faktor an.

**Utility helpers:**
- `el(tag, attrs)` — erstellt ein SVG-Element mit optionalen Attributen.
- `clamp(v, lo, hi)` — clampt Wert zwischen Grenzen.
- `dist(a, b)` — Euklidischer Abstand zwischen zwei Punkten.
- `esc(s)` — HTML-escaped einen String, um Injection zu verhindern.
- `trunc(s, n)` — kürzt String auf n Zeichen, ersetzt Überfluss mit "…".
- `stackCol(arr, x, rowY)`, `stackRow(arr, y, colX)`, `stackColAt(arr, x, midY, rowGap)` — Positions-Hilfsfunktionen, die Gruppen von Knoten gleichmäßig verteilen und entlang einer Achse zentrieren.

---

### `gwa/ui/static/index.html`

HTML-Struktur für die GWA-Brain-Schnittstelle mit einer Seite. Drei-Spalten-Layout auf Desktop (Antwort- + Log-Panen links, Baum rechts); Mobile-Tabs wechseln zwischen Antwort, Baum und Live-Log. Enthält Kopfzeile mit Upload-/Mode-/Menu-Steuerelementen, Ask-Fußzeile und Inline-Skript für Status, E/A und Event-Streaming.

**Key sections:**

- **Header** — Brand-Logo, Upload-Schaltfläche (Dateieingabe für .pdf/.txt/.md/.docx), Mode-Dropdown (Auto/Factual/Prose/Derivation), Status-Kapsel (Fakt-/Dokument-Anzahl) und Dokument-Menu-Schaltfläche.
- **Tabs (mobile)** — schaltet zwischen aktiven Panen um; Status bleibt über localStorage erhalten.
- **Workspace** — Flex-Layout mit:
  - **Answer pane** — zeigt begründete Antwort-Prosa mit Zitaten, Quellen (Dokumente) und Lücken (unabgedeckte Teilanforderungen).
  - **Log pane** — scrollbares Ereignisprotokoll mit Auto-Scroll-Abzeichen; zeigt Upload-Fortschritt, Fakt-Bewertungen (behalten/durchgestrichen) und Fehler.
  - **Tree pane** — SVG-Baum-Host mit Überblicks-/Reset-Schaltflächen in der Kopfzeile.
- **Ask row** — Frage-Eingabefeld und Senden-Schaltfläche (mit Spinner bei Beschäftigung).
- **Drag-drop overlay** — Visuelles Feedback im vollständigen Fenster auf Desktop beim Ziehen von Dateien (auf Mobilgeräten verborgen).
- **Inline script** — bearbeitet Status (beschäftigt, Auto-Scroll), Tab-Wechsel, Upload-/Ask-Flüsse über SSE-Streams, Log-Rendering, Baum-Rendering und Brain-Reset.

**Inline script main sections:**

- `esc(s)`, `withCites(s)` — HTML-Escape- und Zitat-Highlight-Hilfsfunktionen.
- `setTab(tab)` — schaltet zwischen aktiver Pane und localStorage-Tab-Schlüssel um; setzt Baum-Ansicht zurück, wenn zum Baum gewechselt wird.
- `refreshStatus()`, `renderDocs(docs)` — ruft Brain-Status ab und füllt Dokumentenliste im Menu auf.
- `setBusy(on)` — deaktiviert Eingaben und zeigt Spinner während Upload-/Ask-Vorgang läuft.
- `streamSSE(resp, onEvent)` — parst ReadableStream + TextDecoder für mehrzeilige SSE-Events (bearbeitet Teilchunks).
- `uploadFile(file)` — POSTet Datei zu `/upload/stream` mit Extraktionsmodus; streamt SSE-Events (start, chunk, done, error).
- `onUploadEvent(ev)` — verarbeitet Upload-Events: protokolliert Datei-/Seiten-Informationen, extrahierte Fakten pro Chunk, neue Fakt-Anzahl.
- `ask()` — POSTet Frage zu `/ask/stream`; streamt SSE-Events (decompose, retrieve, guard_keep, guard_strike, gap, answer, error).
- `onAskEvent(ev)` — verarbeitet Ask-Events: protokolliert Teilanforderungen, Kandidaten, Fakt-Bewertungen, Lücken, endgültige Antwort mit Baum-Rendering.
- `renderAnswer(result, fallbackText)` — zeigt Antwort-Prosa mit Quellen und Lücken.
- Menu-Umschaltung und Dokumentenlisten-Klick-Handling.
- Drag-Drop-Event-Listener für Desktop-Datei-Upload.
- Upload-Eingabedatei-Änderungs-Listener.
- Scroll-Abzeichen und Log-Auto-Scroll-Verhalten.
- Viewport-Größenänderungs-Debouncer zum Anpassen des Baums.
- Boot: Status beim Laden der Seite abrufen.

---

### `gwa/ui/static/style.css`

Einfaches CSS (kein Framework), Mobile-First, responsiver Breakpoint bei 768px. Definiert Komponenten-Stile, Grid/Flex-Layout, Farbschema (teal/amber/rot/grau) und Baum-Knoten/Link-Visualisierung.

**Key sections:**

- **CSS variables** — definiert Farbpalette (teal für behaltene Fakten, amber für Antwort, rot für Lücken, grau für durchgestrichene), weiche Hintergründe und Layout-Konstanten (Kopfzeilenhöhe 56px, Ask-Reihe-Höhe 60px).
- **Global** — System-Font-Stack, Vollhöhen-Flex-Layout, kantenglättete Textdarstellung.
- **Header** — feste Navigationsleiste mit Brand, Symbol-Schaltflächen (Upload, Menu), Mode-Dropdown, Status-Kapsel (teal-soft-Hintergrund mit Fakt-/Doc-Anzahl) und Flexbox-Abstand.
- **Mode field & dropdown** — kompakter Mode-Selektor, der mit Header-Schaltflächen übereinstimmt.
- **Menu panel** — absolut positioniertes Dropdown für Dokumentenliste mit Hover-Status und Gefahr-gefärbter Reset-Schaltfläche.
- **Tabs (mobile)** — Tab-Leiste unter der Kopfzeile mit teal-Unterstrich für aktiven Tab; auf Desktop verborgen (>768px).
- **Workspace panes** — Flex/Grid-Layout; `.pane` Stapeln auf Mobilgeräten (Tab-gewechselt), `.col-left` / `.col-right` Grid-Spalten auf Desktop; scrollbarer Überlauf.
- **Answer pane** — Prosa-Text, Zitate (gestaltete Abzeichen mit amber-soft-Hintergrund), Abschnitte (Quellen/Lücken mit Chips und Lücken-Linien-Warnungen).
- **Log pane** — Artikel-Karten mit Symbolen, farbige linke Ränder (teal für behalten, grau für durchgestrichen, rot für Lücken/Fehler), verschachtelte Listen, Grund-Erklärungen und Auto-Scroll-Abzeichen.
- **Tree pane** — SVG-Host mit Punkt-Grid-Hintergrund, Grab-Cursor, Knoten/Link-Styling (farbige Rechtecke mit Text, Strich-Konturen, Pfeilspitze-Marker), Tooltip (dunkle Überlagerung mit teal-Quelle, weißer Text).
- **Ask row** — untere Eingabezeile mit Frage-Textfeld (teal-Fokuskontur auf Weiß), primäre Schaltfläche (durchgehend teal-Hintergrund, Spinner-Animation), Flex-Abstand.
- **Spinner animation** — CSS-Keyframes rotierende Grenze; ausgelöst über `.busy` Klasse auf Schaltflächen.
- **Drag-drop overlay** — Vollständiger Viewport-Blur + halbdurchsichtiger teal-Hintergrund mit gestrichelter Karte beim Ziehen von Dateien (auf Mobilgeräten verborgen).
- **Desktop layout (>=768px)** — Workspace wird 2-Spalten-Grid; linke Spalte (Antwort + Log, 50/50-Teilung) und rechte Spalte (Baum Vollhöhe); alle Panen sichtbar unabhängig von Tab.

---

## Docker & Abhängigkeiten

### `Dockerfile`

Containerisiert die GWA-Anwendung mit einem schlanken Python 3.13-Basis-Image mit optimierten Docker-Ebenen. Erstellt ein Image, das die Uvicorn-basierte FastAPI-App auf Port 8000 bereitstellt und als Nicht-Root-Benutzer ausgeführt wird, um die Eigentümerschaft von Host-bereitgestellten Daten sauber zu halten.

**Build-Abschnitte:**
- **Basis-Image & Umgebung (Zeilen 1–5)**: Setzt Python 3.13 slim mit deaktiviertem Buffering und Cache für schlankes, effizientes Logging.
- **Dependencies-Ebene (Zeilen 9–11)**: Installiert requirements.txt in einer gecachten Docker-Ebene; pins pip und deaktiviert Cache für Reproduzierbarkeit.
- **Anwendungs-Kopie (Zeilen 13–15)**: Kopiert das `gwa/`-Paket und `run.py` in `/app`.
- **Nicht-Root-Benutzer-Setup (Zeilen 17–20)**: Erstellt unprivilegiert `app`-Benutzer (uid 10001) und bereitet `/app/data`-Volume-Verzeichnis mit korrekter Eigentümerschaft vor.
- **Service-Start (Zeilen 22–26)**: Exponiert Port 8000 und startet Uvicorn mit `0.0.0.0`-Bindung (erforderlich für Docker-Port-Veröffentlichung).

---

### `docker-compose.yml`

Orchestriert einen Zwei-Container-Stack: den GWA Brain-Service und eine Qdrant-Vektordatenbank, mit persistentem Speicher und Host-Netzwerk-Bindung, konfiguriert über Umgebungsvariablen für ein Single-User-Entwicklungssetup.

**Services:**
- **`brain` (Zeilen 2–26)**: Erstellt und führt die GWA-App aus dem Dockerfile aus; läuft als Host-Benutzer (uid 1000/gid 1000 standardmäßig, überschreibbar via `BRAIN_UID`/`BRAIN_GID`) damit Datendateien Host-eigentum bleiben; veröffentlicht Port 8000 nur zu localhost (oder `0.0.0.0` wenn `BRAIN_BIND` gesetzt ist); bindet `./data` für persistenten Status ein; lädt `.env` für App-Konfiguration; überschreibt `QDRANT_HOST` und `QDRANT_PORT` im Compose, sodass die App immer die lokale Qdrant-Instanz erreicht; hängt von Qdrant ab und startet neu, es sei denn, es wird explizit gestoppt.
- **`qdrant` (Zeilen 28–36)**: Führt Qdrant v1.12.0 aus (fixiert für Query API-Kompatibilität); exponiert Port 6333 intern und auf Host; persistiert Embeddings in einem benannten Volume `qdrant_data` über Neustarts hinweg.

**Volumes:**
- **`qdrant_data`**: Benanntes Volume, das Qdrant-Embeddings und Metadaten speichert.

---

### `.env.example`

Vorlage-Konfigurationsdatei, die alle erforderlichen Umgebungsvariablen zum Ausführen von GWA dokumentiert, mit sinnvollen Standards, auskommentierten optionalen Tuning-Knöpfen und Beispielen für verschiedene LLM-Anbieter (Mistral, lokale Server usw.).

**Konfigurationsabschnitte:**
- **Chat LLM (Zeilen 1–10)**: `LLM_BASE_URL`, `GWA_MODEL`, `GWA_MAX_TOKENS`, `LLM_API_KEY_ENV` (Name der Umgebungsvariablen, die den Schlüssel enthält), und optionale Rate-Limiting/Wiederholungsparameter.
- **Embeddings (Zeilen 12–17)**: `GWA_EMBED_MODEL`, mit optionalen Überschreibungen für nicht standardmäßigen Embedding-Endpunkt/Schlüssel; Batch-Größen-Tuning.
- **Anbieter-Beispiele (Zeilen 19–28)**: Schnelle Copy-Paste-Konfigurationen für gehostete Anbieter, Mistral und lokale Server (Ollama/vLLM/TGI).
- **Qdrant (Zeilen 30–32)**: `QDRANT_HOST`, `QDRANT_PORT`, optionale Collection-Name-Überschreibung.
- **Speicher/Ingestion (Zeilen 35–38)**: `BRAIN_DATA_DIR`, maximale Upload-Größe, Extraktionsmodus (factual/prose/auto/derivation).
- **Abruf/Akkumulation (Zeilen 40–43)**: `GWA_TOP_K`, Ähnlichkeitsschwelle, Akkumulationsgewichtung (nach dem Setzen fixiert).
- **Cross-Model-Guard (Zeilen 45–49)**: Optionale separate Guard LLM-Konfiguration (standardmäßig deaktiviert).
- **Nur Docker Compose (Zeilen 51–55)**: `BRAIN_PORT`, `BRAIN_BIND`, `BRAIN_UID`, `BRAIN_GID` für Compose-Orchestrierung.
- **Offline-/Mock-Modus (Zeilen 57–59)**: `GWA_MOCK=1` und speicherinterne Qdrant-Position zum Testen ohne Netzwerk/Schlüssel.

---

### `requirements.txt`

Python-Paket-Abhängigkeiten, auf spezifische Versionen fixiert, für die GWA-FastAPI-Anwendung, ihren Webserver, ORM/Validierung, Vektordatenbank-Client und Dokumentverarbeitungsbibliotheken.

- **`fastapi==0.138.1`**: Web-Framework zum Erstellen der REST/WebSocket-API.
- **`uvicorn[standard]==0.49.0`**: ASGI-Server zum Ausführen von FastAPI mit Standard-Extras (HTTP/2, WebSocket usw.).
- **`python-multipart==0.0.32`**: Multipart-Formulardaten-Parsing für Datei-Uploads.
- **`pydantic==2.13.4`**: Datenvalidierung und Serialisierung für Request/Response-Modelle.
- **`qdrant-client==1.18.0`**: Python-Client für Qdrant-Vektordatenbank (fixiert zur Unterstützung von v1.10+ Query API).
- **`networkx==3.6.1`**: Graph-Algorithmen-Bibliothek (intern von GWA für Reasoning/Traversal verwendet).
- **`pdfplumber==0.11.10`**: PDF-Extraktion und -Analyse für Dokument-Ingestion.
- **`python-docx==1.2.0`**: Microsoft Word-Dokumenten-Parsing für `.docx`-Datei-Ingestion.

---
