FROM node:22-bookworm-slim

WORKDIR /app
ENV NODE_ENV=production

COPY web/package.json web/package-lock.json ./
RUN npm ci --include=dev --ignore-scripts
COPY web/ .
RUN npm run build

EXPOSE 3000
CMD ["sh", "-c", "npm run start -- -p ${PORT:-3000}"]
