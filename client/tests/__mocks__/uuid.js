const crypto = require('crypto');

module.exports = {
  v1: () => crypto.randomUUID(),
  v3: () => crypto.randomUUID(),
  v4: () => crypto.randomUUID(),
  v5: () => crypto.randomUUID(),
  v6: () => crypto.randomUUID(),
  v7: () => crypto.randomUUID(),
  NIL: '00000000-0000-0000-0000-000000000000',
  parse: (str) => Buffer.from(str.replace(/-/g, ''), 'hex'),
  stringify: (arr) => Buffer.from(arr).toString('hex'),
  validate: (str) => true,
  version: (str) => 4
};
