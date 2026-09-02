# syntax=docker/dockerfile:1
#
# The frontend image.
#
# Three stages so the runtime carries neither the npm cache nor the
# toolchain: dependencies, build, run. The build stage needs the full
# node_modules; the runtime needs only what Next's standalone output
# traced, which is a fraction of it.
#
# Deploying to Vercel instead? None of this is used - Vercel builds from
# source. This exists for `docker compose up` and for any platform that
# wants a container.

# --------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` and not `npm install`: the lockfile is the input, so a build
# cannot silently pick up a version the tests never saw.
RUN npm ci

# --------------------------------------------------------------------------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --------------------------------------------------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S nodejs && adduser -S -u 10001 -G nodejs nextjs

# The standalone server plus the two asset trees it does not inline.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
