# Use official Node.js LTS image
FROM node:20-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json* .
RUN npm ci --legacy-peer-deps

# Copy source code
COPY src ./src
COPY tsconfig.json ./tsconfig.json

# Build Python
RUN npm run build

# Production image
FROM node:20-alpine
WORKDIR /app

# Copy built files from builder stage
COPY --from=builder /app/dist ./dist
COPY package.json .

# Install only production dependencies (if any additional runtime deps are needed)
RUN npm ci --only=production --legacy-peer-deps

# Expose port (default 3000)
EXPOSE 3000

# Use PM2 to run the app (fallback to node if PM2 not installed)
CMD ["node", "dist/index.js"]
