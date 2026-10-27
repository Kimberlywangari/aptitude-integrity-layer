# The candidate and staff app, built once and served by nginx. nginx also proxies /api to the API,
# so the browser sees one origin (no CORS, one HTTPS address for the camera: master plan A6).
# Base images are pinned by digest so a rebuild uses the image that was tested; Dependabot proposes
# newer ones (.github/dependabot.yml) and CI runs on each proposal.
FROM node:26-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS build
WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Type-checks, then builds. No VITE_MOCK_API and no VITE_MIC_CHECK=off: those live in
# .env.development files, which a production build does not read.
RUN npm run build

FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Empty unless production mounts something over it (see nginx.conf).
RUN touch /etc/nginx/real-ip.conf
COPY --from=build /app/dist /usr/share/nginx/html
# The capture spike page is a developer tool, not part of the product.
RUN rm -rf /usr/share/nginx/html/spike

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
