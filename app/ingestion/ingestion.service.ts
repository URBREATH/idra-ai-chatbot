import { generateEmbedding } from '../ollama/ollama.module';
import { upsertVectors } from '../chroma/chroma.module';

/**
 * Simple ingestion service that takes a plain text payload, generates an embedding
 * using the configured Ollama embedding model, and stores it in the tenant's
 * Chroma collection.
 */
export const ingestDocument = async (
  tenantId: string,
  docId: string,
  text: string,
  metadata: Record<string, any> = {}
): Promise<void> => {
  // 1️⃣ Generate embedding via Ollama
  const embedding = await generateEmbedding(text);

  // 2️⃣ Prepare Chroma payload
  const ids = [docId];
  const embeddings = [embedding];
  const metadatas = [{ ...metadata }];

  // 3️⃣ Upsert into tenant collection
  await upsertVectors(tenantId, ids, embeddings, metadatas);
};
