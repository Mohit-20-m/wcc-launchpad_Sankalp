# --- Stage 1: build the React frontend into static files ---
FROM node:20-alpine AS build

WORKDIR /app

# Install exactly the versions in the lockfile (React 19.2.8 etc.), so every
# build is identical to what was tested.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ .
RUN npm run build

# --- Stage 2: serve those static files + proxy /api and /ws to backend ---
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
