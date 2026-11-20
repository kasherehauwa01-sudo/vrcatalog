FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_BASE_PATH=/vr/catalog/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
COPY package*.json ./
COPY types ./types
RUN npm ci && npm install --no-save @rollup/rollup-linux-x64-musl@4.62.2
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/vr/catalog
