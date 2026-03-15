const { createProxyMiddleware } = require('http-proxy-middleware');
const proxy = createProxyMiddleware({ pathFilter: '/http-api', target: 'http://localhost:8000' });
console.log(proxy);
