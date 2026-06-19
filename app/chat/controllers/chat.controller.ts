import { Request, Response } from 'express';
import { retrieveDocuments } from '../../retrieval/retrieval.service';
import { generateCompletion } from '../../ollama/ollama.module';

/**
 * POST /chat handler.
 * Expects JSON body { message: string, conversationId?: string }
 * Tenant ID is expected in the header `x-tenant-id`.
 */
export const chatHandler = async (req: Request, res: Response) => {
  try {
    const tenantId = req.headers['x-tenant-id'] as string;
    if (!tenantId) {
      return res.status(400).json({ error: 'Missing tenant ID' });
    }
    const { message, conversationId } = req.body;
    if (!message) {
      return res.status(400).json({ error: 'Missing message' });
    }

    // Retrieve relevant documents
    const retrievalResult = await retrieveDocuments(tenantId, message, 5);
    const sources = retrievalResult?.ids?.map((id: string, idx: number) => ({
      title: id,
      datasetId: id,
      // In a real implementation, map ID to actual source metadata
    })) || [];

    // Simple context assembly: concatenate retrieved IDs (placeholder)
    const context = (sources as any[]).map(s => s.title).join('\n');
    const prompt = `Context:\n${context}\n\nUser: ${message}`;

    const answer = await generateCompletion(prompt);

    res.status(200).json({
      answer,
      sources,
      conversationId: conversationId || undefined
    });
  } catch (err) {
    console.error('Chat handler error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
};
