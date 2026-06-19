import axios from 'axios';
import dotenv from 'dotenv';

dotenv.config();

const OLLAMA_HOST = process.env.OLLAMA_HOST || 'localhost';
const OLLAMA_PORT = process.env.OLLAMA_PORT || '11434';
const BASE_URL = `http://${OLLAMA_HOST}:${OLLAMA_PORT}`;

/**
 * Generate embeddings using the configured Ollama embedding model.
 */
export const generateEmbedding = async (text: string): Promise<number[]> => {
  const response: any = await axios.post(`${BASE_URL}/api/embeddings`, {
    model: process.env.OLLAMA_EMBEDDING_MODEL,
    prompt: text,
    // Ollama may require specific fields; adjust as needed.
  });
  // Assuming response.data.embedding is an array of numbers
  return response.data.embedding as number[];
};

/**
 * Generate a completion from the LLM model.
 */
export const generateCompletion = async (prompt: string): Promise<string> => {
  const response: any = await axios.post(`${BASE_URL}/api/chat`, {
    model: process.env.OLLAMA_LLM_MODEL,
    messages: [{ role: 'user', content: prompt }]
  });
  // Adjust according to actual Ollama API response shape
  return response.data.message?.content || '';
};
