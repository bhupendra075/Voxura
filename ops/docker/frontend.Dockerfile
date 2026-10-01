FROM node:22.9.0-alpine3.20 AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ARG VITE_API_BASE_URL=/api
ARG VITE_CLINICAL_DEV_SESSION=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_CLINICAL_DEV_SESSION=${VITE_CLINICAL_DEV_SESSION}
RUN npm run typecheck && npm run build

FROM nginx:1.27.2-alpine3.20
COPY ops/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
