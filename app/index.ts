import { startServer } from './app.module';

// Start the server when this file is executed directly
if (require.main === module) {
  startServer();
}
