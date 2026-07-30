# Database Schema

> **Nota**: questa sezione descrive lo schema realmente usato dal codice (verificato in
> `app/mongodb/repositories.py`), non uno schema custom del progetto: il database
> `orion` è la base dati MongoDB gestita da un **FIWARE Orion Context Broker** esterno
> all'applicativo. L'app si limita a **leggere** (nessuna scrittura/import) da questo
> database, che deve già esistere e contenere le entità NGSI-LD.

## MongoDB Database & Collections

Database (nome impostato tramite `MONGODB_URI`, es. `mongodb://mongo:27017/orion`):

```text
orion
```

Collezioni realmente interrogate dall'app (vedi `app/mongodb/repositories.py`):

```text
entities          # tutte le entità NGSI-LD (dataset, distribution, catalog, ...)
deleted_datasets  # id dei dataset cancellati, usati per la sincronizzazione incrementale
```

A differenza di un modello "una collection per tipo", Orion Context Broker
memorizza **tutte** le entità NGSI-LD in un'unica collection `entities`,
distinguendole tramite il campo `_id.type`. I tipi di entità attualmente
attesi dalla pipeline di ingestion sono:

| `_id.type` (valore atteso) | Significato        |
| -------------------------- | ------------------- |
| Dataset                    | Dataset             |
| DistributionDCAT-AP        | Distribuzione       |
| Catalog                    | Catalogo            |
| Organization                | Organizzazione      |
| DataService                | Servizio dati       |

---

# Common NGSI-LD Fields

## Entity Identifier

```python
interface EntityId {
  id: string;
  type: string;
  servicePath: string;
}
```

---

## Metadata Entity

```python
interface MetadataEntity {
  _id: EntityId;

  attrNames: string[];

  attrs: Record<string, Property>;

  creDate: number;

  modDate: number;

  lastCorrelator?: string;
}
```

---

## Property

```python
interface Property {
  type: "Property";

  value: unknown;

  creDate: number;

  modDate: number;

  mdNames: string[];
}
```

---

# Internal Ingestion Tracking

> **Nota (reale)**: l'app NON scrive alcun campo di tracking sulle entità Mongo
> (nessun `_ingested`, `_ingestionDate`, `_deleted`, `_lastEmbeddingVersion` viene
> persistito su Orion). Lo stato di ingestion è tenuto **solo in memoria** nel
> processo FastAPI (`IngestionStatus` in `app/ingestion/service.py`: `running`,
> `processed`, `remaining`, `last_ingestion`) e viene perso al riavvio del container.
> Esposto in sola lettura tramite `GET /admin/ingestion/status`.

---

# ChromaDB Schema

Collection naming convention (vedi `app/chroma/client.py` e
`app/common/guards/tenant_guard.py`, isolamento **per tenant**, non per utente):

```text
rag_tenant_<tenantId>
```

Example:

```text
rag_tenant_default-tenant
rag_tenant_acme
```

---

## Vector Document

Metadata realmente scritta durante l'ingestion (vedi `app/ingestion/service.py`,
funzione `_process_dataset`). Il testo del chunk (titolo, descrizione, attributi
tecnici) è salvato come `document` di Chroma, non come metadata:

```python
interface VectorDocumentMetadata {
  tenant_id: string;

  dataset_id: string;

  chunk_id: string;

  title?: string;

  url?: string;

  publisher?: string;
}
```

> I campi con valore `None` vengono rimossi prima dell'upsert (Chroma non accetta
> valori nulli nei metadata). Non sono presenti i campi `entityType`, `language`,
> `keywords`, `sourceUrl`, `metadataType`, `originalEntityId` talvolta citati in
> documenti di progettazione precedenti: non sono implementati.

---

# Feedback Collection

> **Nota (reale)**: il feedback **non viene persistito su MongoDB**. L'endpoint
> `POST /chat/feedback` (vedi `app/main.py`) si limita a incrementare due contatori
> in memoria (`feedback_positive` / `feedback_negative`), esposti tramite
> `GET /metrics`, e a loggare l'evento. Non esiste alcuna collection `chat_feedback`
> n\u00e9 uno storico persistente delle valutazioni: viene perso al riavvio del container.
> Lo schema sotto descrive un possibile sviluppo futuro, non lo stato attuale.

MongoDB collection (non implementata):

```text
chat_feedback
```

Schema proposto (non ancora implementato):

```python
interface Feedback {
  id: string;

  tenantId: string;

  question: string;

  answer: string;

  sources: SourceReference[];

  rating: "positive" | "negative";

  createdAt: Date;
}
```
