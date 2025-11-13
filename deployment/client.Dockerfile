# Client Dockerfile (for web builds or CI/CD)
# This is typically not used for desktop clients, but useful for web exports

FROM nginx:alpine

WORKDIR /usr/share/nginx/html

# Copy exported web client
COPY ../exports/client/web/ ./

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
