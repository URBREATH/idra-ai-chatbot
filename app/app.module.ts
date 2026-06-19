import express, { Express, Request, Response } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import dotenv from 'dotenv';
import { connectMongo } from './mongodb/mongodb.module';
import { registerMonitoringRoutes } from './monitoring/monitoring.module';
import { registerChatRoutes } from './chat/chat.module';

// Load environment variables
dotenv.config();

const app: Express = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

registerMonitoringRoutes(app);
registerChatRoutes(app);

// Root endpoint
app.get('/', (req: Request, res: Response) => {
  res.status(200).json({
    message: 'Idra AI Chatbot API',
    version: '1.0.0',
    documentation: '/api-docs'
  });
});

// Start server
const startServer = async () => {
  // Connect to MongoDB before listening
  await connectMongo();
  try {
    app.listen(PORT, () => {
      console.log(`Server is running on port ${PORT}`);
      console.log(`Health check available at http://localhost:${PORT}/health`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
};

// Start the server if this file is run directly
if (require.main === module) {
  startServer();
};

export { app, startServer };