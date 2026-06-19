import { Request, Response } from 'express';

export const healthController = (req: Request, res: Response) => {
  res.status(200).json({
    status: 'UP',
    timestamp: new Date().toISOString(),
    services: {
      mongo: 'UNKNOWN',
      chroma: 'UNKNOWN',
      ollama: 'UNKNOWN'
    }
  });
};
