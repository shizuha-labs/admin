# Development Dockerfile for Shizuha Admin Frontend
FROM node:20-alpine

WORKDIR /app

# Install the reviewed local UI package and public locked dependencies.
COPY package*.json ./
COPY vendor/ ./vendor/
RUN npm ci --no-audit --no-fund

# Copy source
COPY . .

# Expose port
EXPOSE 80

# Start development server
CMD ["npm", "run", "dev"]
