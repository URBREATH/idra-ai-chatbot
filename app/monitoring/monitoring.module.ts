import { Express } from 'express';
import { healthController } from './controllers/health.controller';

export const registerMonitoringRoutes = (app: Express) => {
  app.get('/health', healthController);
};
