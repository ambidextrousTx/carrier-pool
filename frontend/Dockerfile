# frontend/Dockerfile

# 1. Base stage for dependencies
FROM node:20-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm ci

# 2. Development stage (used by docker-compose for local dev)
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# 3. Production build stage
FROM base AS build
COPY . .
RUN npm run build

# 4. Production serve stage (serves static files with Nginx)
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
