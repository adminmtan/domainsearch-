FROM node:20-alpine

WORKDIR /app

# 只复制 package.json + lockfile，用 npm ci（更快的生产安装；需 lockfile 一致）
COPY package.json package-lock.json ./

RUN npm ci --omit=dev

COPY src/ ./src/

EXPOSE 5002

CMD ["node", "src/server.js"]
