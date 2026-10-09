# Piano d'Azione — Gestione Licenze

Contesto: **Idra AI Chatbot** è a **uso interno aziendale**, distribuito come
**SaaS self-hosted** (nessuna distribuzione a clienti esterni). Questo riduce
il rischio legale rispetto a un prodotto commercializzato, ma non lo azzera:
restano da gestire (1) le licenze delle dipendenze software e (2) le licenze/
termini d'uso dei modelli AI eseguiti via Ollama.

Vedi [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) per l'inventario completo
delle licenze attualmente in uso.

---

## Sintesi rischio attuale

- Nessuna dipendenza copyleft (GPL/LGPL/AGPL/SSPL) nel codice applicativo.
- Nessun modello AI attualmente in uso ha licenza restrittiva incompatibile con l'uso interno.
- Rischio residuo: **governance debole** — modello LLM configurabile liberamente via env var, riferimenti a modelli diversi tra codice/documentazione, nessun controllo automatico sulle licenze delle nuove dipendenze.

---

## Azioni raccomandate

### 1. Allineare il modello LLM di riferimento
- [ ] Scegliere un unico modello di generazione per produzione (oggi risultano 3 default diversi: `mistral-nemo` in [app/ollama/client.py](app/ollama/client.py#L26), `qwen2.5:7b` in [.env.example](.env.example#L25) e [app/ingestion/semantic_enricher.py](app/ingestion/semantic_enricher.py#L10), `mixtral` in [README_PRODUZIONE.md](README_PRODUZIONE.md#L67)).
- [ ] Documentare la taglia esatta del modello scelto (es. se si resta su Qwen2.5, evitare le taglie 3B/72B che hanno licenza "Qwen" restrittiva invece di Apache-2.0).

### 2. Introdurre una allowlist dei modelli Ollama ammessi
- [ ] Validare `OLLAMA_LLM_MODEL` e `OLLAMA_EMBEDDING_MODEL` contro un elenco di tag pre-approvati (con licenza già verificata), rifiutando l'avvio o loggando un warning se viene impostato un tag non in whitelist.
- [ ] Evitare che in futuro qualcuno introduca in produzione un modello con licenza "research-only"/non-commercial o con Acceptable Use Policy non verificata (es. famiglia Llama), senza controllo.

### 3. Adottare una policy interna sulle licenze delle dipendenze
- [ ] Vietare l'introduzione di nuove dipendenze con licenza GPL/AGPL/SSPL senza deroga esplicita approvata, anche per il solo uso interno — utile a non complicare eventuali futuri cambi del modello di distribuzione (es. se in futuro il prodotto venisse offerto anche a comuni/clienti esterni).
- [ ] Integrare un license-check automatico in CI (es. `pip-licenses` o `pip-audit --licenses`) che fallisca la build su licenze non ammesse.

### 4. Chiarire la licenza del progetto stesso
- [ ] Sostituire il placeholder in [README.md](README.md#L215-L217) ("Add the project's license here...") con una dicitura esplicita, ad es. "Proprietary — Internal Use Only", coerente con il fatto che il software non viene distribuito esternamente e non richiede quindi una licenza open source.

### 5. Risolvere la dipendenza `sentence-transformers` non dichiarata
- [ ] Decidere se il reranking cross-encoder ([app/common/utils/reranker_encoder.py](app/common/utils/reranker_encoder.py)) è una funzionalità voluta:
  - Se sì: aggiungere `sentence-transformers` (Apache-2.0) a `requirements.txt`.
  - Se no: rimuovere il codice morto che lo referenzia.

### 6. Mantenere l'inventario licenze aggiornato
- [ ] Aggiornare [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) ad ogni modifica di `requirements.txt` o dei modelli Ollama di default.
- [ ] Assegnare la responsabilità di revisione periodica (es. ad ogni release o trimestralmente) a un owner del team.

### 7. Verificare i termini dei servizi infrastrutturali di terze parti
- [ ] MongoDB Community Server è distribuito sotto **SSPL**: non è incorporato nel codice applicativo (è un servizio esterno), quindi oggi non pone problemi per uso interno. Da rivalutare solo se in futuro il prodotto venisse offerto come servizio a terzi.
- [ ] Ollama e ChromaDB sono eseguiti come servizi containerizzati non modificati (MIT e Apache-2.0): nessun obbligo aggiuntivo.

---

## Priorità consigliata

| Priorità | Azione |
|---|---|
| Alta | #1 Allineare modello LLM di default tra codice e documentazione |
| Alta | #2 Allowlist modelli Ollama ammessi |
| Media | #3 Policy + check automatico licenze dipendenze in CI |
| Media | #4 Chiarire licenza del progetto in README |
| Bassa | #5 Sistemare dipendenza `sentence-transformers` |
| Bassa | #6 Processo di manutenzione inventario licenze |
| Bassa | #7 Rivalutazione licenze infrastrutturali (solo se cambia il modello di distribuzione) |
