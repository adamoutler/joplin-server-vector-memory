FROM node:20-slim

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Ensure we have build tools for sqlite-vec if needed
RUN apt-get update && apt-get install -y build-essential python3 && rm -rf /var/lib/apt/lists/*

CMD ["npm", "start"]
