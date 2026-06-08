FROM node:20-alpine AS build

WORKDIR /repo
RUN corepack enable

ARG NUXT_APP_BASE_URL=/blog/
ARG NUXT_PUBLIC_BLOG_SITE_URL=https://soulcuts.com.ua/blog
ARG NUXT_PUBLIC_API_BASE=https://api.soulcuts.com.ua/api/v1

ENV NUXT_APP_BASE_URL=${NUXT_APP_BASE_URL}
ENV NUXT_PUBLIC_BLOG_SITE_URL=${NUXT_PUBLIC_BLOG_SITE_URL}
ENV NUXT_PUBLIC_API_BASE=${NUXT_PUBLIC_API_BASE}

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/barbershop/assets ./apps/barbershop/assets
COPY apps/blog ./apps/blog

RUN pnpm install --frozen-lockfile
RUN pnpm --filter @apps/blog build

FROM node:20-alpine AS runtime

ENV NODE_ENV=production
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3000
ENV NUXT_APP_BASE_URL=/blog/
ENV NUXT_PUBLIC_BLOG_SITE_URL=https://soulcuts.com.ua/blog
ENV NUXT_PUBLIC_API_BASE=https://api.soulcuts.com.ua/api/v1

WORKDIR /app
COPY --from=build /repo/apps/blog/.output ./.output

EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
