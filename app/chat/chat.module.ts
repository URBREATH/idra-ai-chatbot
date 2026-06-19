import { Express } from 'express';
import { chatHandler } from './controllers/chat.controller';

export const registerChatRoutes = (app: Express) => {
  app.post('/chat', chatHandler);
};
