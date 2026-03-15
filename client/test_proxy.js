const { createProxyMiddleware } = require('http-proxy-middleware');
const express = require('express');
const app = express();

app.use(createProxyMiddleware({ pathFilter: '/http-api/**', target: 'http://localhost:8000', changeOrigin: true }));
app.use((req, res) => res.status(404).send('Express 404'));

app.listen(3001, () => console.log('started'));
