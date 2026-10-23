FROM node:22-alpine
WORKDIR /app
COPY package.json tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm install && npm run build
FROM nginx:alpine
COPY --from=0 /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
