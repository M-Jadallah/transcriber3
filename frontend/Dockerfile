# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=22
ARG PNPM_VERSION=9.15.9

FROM node:${NODE_VERSION}-alpine AS frontend-builder

ARG PNPM_VERSION

ENV CI=true

WORKDIR /app

# The Docker Compose build context is the repository root, so frontend/
# must be included explicitly in COPY paths.
COPY frontend/ /app/

RUN corepack enable \
    && if [ -f pnpm-lock.yaml ]; then \
         corepack prepare "pnpm@${PNPM_VERSION}" --activate \
         && pnpm install --frozen-lockfile; \
       elif [ -f yarn.lock ]; then \
         yarn install --frozen-lockfile; \
       elif [ -f package-lock.json ]; then \
         npm ci; \
       else \
         npm install; \
       fi

RUN if [ -f pnpm-lock.yaml ]; then \
      pnpm run build; \
    elif [ -f yarn.lock ]; then \
      yarn build; \
    else \
      npm run build; \
    fi \
    && test -f /app/dist/index.html


FROM nginx:1.27-alpine AS runtime

COPY --from=frontend-builder /app/dist/ /usr/share/nginx/html/
COPY frontend/nginx.conf /etc/nginx/nginx.conf

RUN test -f /usr/share/nginx/html/index.html \
    && nginx -t

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
