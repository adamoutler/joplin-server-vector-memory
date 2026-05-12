const fs = require('fs');

module.exports = {
  existsSync: (path) => fs.existsSync(path),
  mkdirSync: (path, options) => fs.mkdirSync(path, options),
  readdirSync: (path) => fs.readdirSync(path),
  rmSync: (path, options) => fs.rmSync(path, options),
  readFileSync: (path, options) => fs.readFileSync(path, options),
  writeFileSync: (path, data, options) => fs.writeFileSync(path, data, options),
  renameSync: (oldPath, newPath) => fs.renameSync(oldPath, newPath),
  unlinkSync: (path) => fs.unlinkSync(path),
  promises: {
    readFile: (path, options) => fs.promises.readFile(path, options),
    writeFile: (path, data, options) => fs.promises.writeFile(path, data, options)
  }
};
