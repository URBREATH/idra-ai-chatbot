import { Client, Collection as ChromaCollection } from 'chromadb';
import dotenv from 'dotenv';

dotenv.config();

const CHROMA_HOST = process.env.CHROMA_HOST || 'localhost';
const CHROMA_PORT = process.env.CHROMA_PORT || '8000';
const CHROMA_URL = `http://${CHROMA_HOST}:${CHROMA_PORT}`;

let clientInstance: Client | null = null;

/**
 * Get a singleton Chroma client.
 */
export const getChromaClient = (): Client => {
  if (!clientInstance) {
    clientInstance = new Client({ url: CHROMA_URL });
  }
  return clientInstance;
};

/**
 * Retrieve or create a collection for a given tenant.
 */
export const getTenantCollection = async (tenantId: string): Promise<ChromaCollection> => {
  const client = getChromaClient();
  // Collection name convention: rag_tenant_<tenantId>
  const collectionName = `rag_tenant_${tenantId}`;
  // The Chroma client API may have a method `getOrCreateCollection`
  const collection = await client.getOrCreateCollection({ name: collectionName });
  return collection;
};

/**
 * Upsert vectors into a tenant's collection.
 */
export const upsertVectors = async (
  tenantId: string,
  ids: string[],
  embeddings: number[][],
  metadatas: Record<string, any>[]
): Promise<void> => {
  const collection = await getTenantCollection(tenantId);
  await collection.add({ ids, embeddings, metadatas });
};

/**
 * Query vectors from a tenant's collection.
 */
export const queryVectors = async (
  tenantId: string,
  embedding: number[],
  nResults: number = 10
): Promise<any> => {
  const collection = await getTenantCollection(tenantId);
  const results = await collection.query({ queryEmbeddings: [embedding], nResults });
  return results;
};
