# syntax=docker/dockerfile:1
FROM node:22-alpine
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package*.json ./
# Optional extra CA for TLS-intercepting corporate proxies (no-op when not supplied).
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
USER node
EXPOSE 3000
HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=30 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["npm", "start"]
