FROM node:22-slim

# Set working directory
WORKDIR /app

# Copy dependency files
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm install

# Copy application code
COPY . .

# Expose port
EXPOSE 5173

# Default command
CMD ["npm", "run", "dev", "--", "--host"]
