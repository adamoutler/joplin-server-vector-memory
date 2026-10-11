const fsw = require('../src/fsw');
const fs = require('node:fs');
const path = require('path');
const os = require('os');

describe('fsw (filesystem wrapper)', () => {
  let testDir;

  beforeAll(() => {
    testDir = path.join(os.tmpdir(), `fsw-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    fsw.mkdirSync(testDir, { recursive: true });
  });

  afterAll(() => {
    try {
      if (fsw.existsSync(testDir)) {
        fsw.rmSync(testDir, { recursive: true, force: true });
      }
    } catch (_e) {
      // ignore cleanup errors
    }
  });

  it('mkdirSync and existsSync operate correctly', () => {
    const subDir = path.join(testDir, 'subdir');
    expect(fsw.existsSync(subDir)).toBe(false);

    fsw.mkdirSync(subDir, { recursive: true });
    expect(fsw.existsSync(subDir)).toBe(true);
  });

  it('writeFileSync and readFileSync write and read files', () => {
    const filePath = path.join(testDir, 'test.txt');
    fsw.writeFileSync(filePath, 'hello fsw', 'utf8');

    expect(fsw.existsSync(filePath)).toBe(true);
    const content = fsw.readFileSync(filePath, 'utf8');
    expect(content).toBe('hello fsw');
  });

  it('renameSync renames a file to a new path', () => {
    const oldPath = path.join(testDir, 'rename-old.txt');
    const newPath = path.join(testDir, 'rename-new.txt');
    fsw.writeFileSync(oldPath, 'rename content', 'utf8');

    expect(fsw.existsSync(oldPath)).toBe(true);
    expect(fsw.existsSync(newPath)).toBe(false);

    fsw.renameSync(oldPath, newPath);

    expect(fsw.existsSync(oldPath)).toBe(false);
    expect(fsw.existsSync(newPath)).toBe(true);
    expect(fsw.readFileSync(newPath, 'utf8')).toBe('rename content');
  });

  it('readdirSync returns array of file names in directory', () => {
    const listDir = path.join(testDir, 'readdir_test');
    fsw.mkdirSync(listDir, { recursive: true });
    fsw.writeFileSync(path.join(listDir, 'a.txt'), '1');
    fsw.writeFileSync(path.join(listDir, 'b.txt'), '2');

    const entries = fsw.readdirSync(listDir);
    expect(entries.sort()).toEqual(['a.txt', 'b.txt']);
  });

  it('unlinkSync deletes a single file', () => {
    const filePath = path.join(testDir, 'unlink_me.txt');
    fsw.writeFileSync(filePath, 'delete this', 'utf8');
    expect(fsw.existsSync(filePath)).toBe(true);

    fsw.unlinkSync(filePath);
    expect(fsw.existsSync(filePath)).toBe(false);
  });

  it('rmSync recursively removes directory (line 7)', () => {
    const rmDir = path.join(testDir, 'rm_target');
    const subRmDir = path.join(rmDir, 'nested');
    fsw.mkdirSync(subRmDir, { recursive: true });
    fsw.writeFileSync(path.join(subRmDir, 'nested.txt'), 'nested content');

    expect(fsw.existsSync(rmDir)).toBe(true);

    fsw.rmSync(rmDir, { recursive: true, force: true });
    expect(fsw.existsSync(rmDir)).toBe(false);
  });

  it('promises.writeFile writes file asynchronously (line 14)', async () => {
    const filePath = path.join(testDir, 'async_write.txt');
    await fsw.promises.writeFile(filePath, 'async data', 'utf8');

    expect(fsw.existsSync(filePath)).toBe(true);
    const content = fsw.readFileSync(filePath, 'utf8');
    expect(content).toBe('async data');
  });

  it('promises.readFile reads file asynchronously', async () => {
    const filePath = path.join(testDir, 'async_read.txt');
    fsw.writeFileSync(filePath, 'async read data', 'utf8');

    const content = await fsw.promises.readFile(filePath, 'utf8');
    expect(content).toBe('async read data');
  });

  it('direct delegation verification to node:fs methods', async () => {
    const spyRm = jest.spyOn(fs, 'rmSync').mockImplementationOnce(() => {});
    fsw.rmSync('dummy-path', { force: true });
    expect(spyRm).toHaveBeenCalledWith('dummy-path', { force: true });
    spyRm.mockRestore();

    const spyWriteFile = jest.spyOn(fs.promises, 'writeFile').mockResolvedValueOnce();
    await fsw.promises.writeFile('dummy-path', 'data', 'utf8');
    expect(spyWriteFile).toHaveBeenCalledWith('dummy-path', 'data', 'utf8');
    spyWriteFile.mockRestore();
  });
});
