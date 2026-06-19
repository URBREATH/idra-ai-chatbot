import { generateEmbedding } from '../ollama/ollama.module';
import { queryVectors } from '../chroma/chroma.module';

/**
 * Simple retrieval service that takes a user query, generates an embedding,
 * searches the tenant's Chroma collection, and returns the matching vectors.
 */
export const retrieveDocuments = async (
  tenantId: string,
  query: string,
  nResults: number = 10
) => {
  // 1️⃣ Generate embedding for the query
  const queryEmbedding = await generateEmbedding(query);

  // 2️⃣ Query Chroma for nearest neighbors
  const results = await queryVectors(tenantId, queryEmbedding, nResults);

  // 3️⃣ Return raw results (IDs, embeddings, metadatas)
  return results;
};
