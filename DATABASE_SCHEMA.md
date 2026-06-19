# Database Schema

## MongoDB Collections

The system reads metadata from the following collections:

```text
datasets
distributions
catalogs
organizations
services
```

Each collection contains NGSI-LD flattened entities.

---

# Entity Types

| Collection    | Entity Type         |
| ------------- | ------------------- |
| datasets      | Dataset             |
| distributions | DistributionDCAT-AP |
| catalogs      | Catalog             |
| organizations | Organization        |
| services      | DataService         |

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

Additional fields managed by the platform:

```python
interface IngestionMetadata {
  _ingested?: boolean;

  _ingestionDate?: Date;

  _deleted?: boolean;

  _lastEmbeddingVersion?: string;
}
```

---

# ChromaDB Schema

Collection naming convention:

```text
rag_user_<userId>
```

Example:

```text
rag_user_6f2d87a1
```

---

## Vector Document

```python
interface VectorDocument {
  id: string;

  datasetId: string;

  chunkId?: string;

  tenantId: string;

  entityType:
    | "Dataset"
    | "DistributionDCAT-AP"
    | "Catalog"
    | "Organization"
    | "DataService";

  title: string;

  description?: string;

  publisher?: string;

  language?: string[];

  keywords?: string[];

  sourceUrl?: string;

  metadataType: string;

  originalEntityId: string;
}
```

---

# Feedback Collection

MongoDB collection:

```text
chat_feedback
```

Schema:

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
