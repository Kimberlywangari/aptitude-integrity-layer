# The candidate and staff app, built once and served by nginx. nginx also proxies /api to the API,
# so the browser sees one origin (no CORS, one HTTPS address for the camera: master plan A6).
FROM node:24-alpine AS build
WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Type-checks, then builds. No VITE_MOCK_API and no VITE_MIC_CHECK=off: those live in
# .env.development files, which a production build does not read.
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
