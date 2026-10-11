const {
  fetchWithTimeout,
  validateJoplinSession,
  fetchJoplinEvents,
  checkJoplinSyncInfo,
  triggerInternalEmbedding
} = require('../src/network');

describe('network.js', () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    jest.clearAllTimers();
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  describe('safeUrl validation (via fetchWithTimeout & helpers)', () => {
    it('blocks non-http and non-https protocols (line 14)', async () => {
      const invalidProtocols = [
        'ftp://example.com/file.txt',
        'file:///etc/passwd',
        'ws://localhost:8080',
        'javascript:alert(1)',
        'data:text/plain;base64,SGVsbG8='
      ];

      for (const url of invalidProtocols) {
        await expect(fetchWithTimeout(url)).rejects.toThrow(`Invalid URL: ${url}`);
        try {
          await fetchWithTimeout(url);
        } catch (err) {
          expect(err.cause).toBeDefined();
          expect(err.cause.message).toMatch(/^Unsafe protocol:/);
        }
      }
    });

    it('blocks SSRF cloud metadata IP (line 21)', async () => {
      const metadataUrl = 'http://169.254.169.254/latest/meta-data';
      await expect(fetchWithTimeout(metadataUrl)).rejects.toThrow(`Invalid URL: ${metadataUrl}`);
      try {
        await fetchWithTimeout(metadataUrl);
      } catch (err) {
        expect(err.cause).toBeDefined();
        expect(err.cause.message).toBe('Unsafe host: 169.254.169.254');
      }
    });

    it('blocks SSRF .internal hosts (line 21)', async () => {
      const internalUrls = [
        'http://metadata.google.internal/computeMetadata/v1/',
        'http://service.internal/api',
        'https://backend.corp.internal:8000'
      ];

      for (const url of internalUrls) {
        await expect(fetchWithTimeout(url)).rejects.toThrow(`Invalid URL: ${url}`);
        try {
          await fetchWithTimeout(url);
        } catch (err) {
          expect(err.cause).toBeDefined();
          expect(err.cause.message).toMatch(/^Unsafe host: .*\.internal$/);
        }
      }
    });

    it('catches invalid URL formatting (line 25)', async () => {
      const malformedUrls = [
        'not-a-valid-url',
        '',
        '://missing-scheme',
        'http://',
        'htp:/malformed'
      ];

      for (const url of malformedUrls) {
        await expect(fetchWithTimeout(url)).rejects.toThrow(`Invalid URL: ${url}`);
      }
    });
  });

  describe('fetchWithTimeout timeout and error handling', () => {
    it('aborts request and cleans up timer on timeout (line 31)', async () => {
      jest.useFakeTimers();

      globalThis.fetch = jest.fn((url, options) => {
        return new Promise((resolve, reject) => {
          if (options && options.signal) {
            options.signal.addEventListener('abort', () => {
              const abortErr = new Error('The operation was aborted');
              abortErr.name = 'AbortError';
              reject(abortErr);
            });
          }
        });
      });

      const fetchPromise = fetchWithTimeout('http://127.0.0.1:3000/slow', {}, 2000);

      // Advance timers to trigger timeout callback
      jest.advanceTimersByTime(2000);

      await expect(fetchPromise).rejects.toThrow('The operation was aborted');
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });

    it('clears timeout and throws when request fails with network error (lines 37-38)', async () => {
      const clearTimeoutSpy = jest.spyOn(global, 'clearTimeout');
      globalThis.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

      await expect(fetchWithTimeout('http://127.0.0.1:3000/fail', {}, 5000)).rejects.toThrow('ECONNREFUSED');
      expect(clearTimeoutSpy).toHaveBeenCalled();
      clearTimeoutSpy.mockRestore();
    });

    it('clears timeout and returns response on success (lines 34-35)', async () => {
      const mockResponse = { ok: true, status: 200, json: async () => ({ success: true }) };
      const clearTimeoutSpy = jest.spyOn(global, 'clearTimeout');
      globalThis.fetch = jest.fn().mockResolvedValue(mockResponse);

      const response = await fetchWithTimeout('http://127.0.0.1:3000/success', { method: 'GET' }, 5000);
      expect(response).toBe(mockResponse);
      expect(clearTimeoutSpy).toHaveBeenCalled();
      clearTimeoutSpy.mockRestore();
    });
  });

  describe('Joplin client network helpers', () => {
    it('validateJoplinSession posts credentials to /api/sessions', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: 'session_token' }) });

      const res = await validateJoplinSession('http://127.0.0.1:22300', 'user@example.com', 'mypass');
      expect(res.ok).toBe(true);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:22300/api/sessions',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: 'user@example.com', password: 'mypass' })
        })
      );
    });

    it('fetchJoplinEvents fetches events without cursor', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], has_more: false }) });

      const res = await fetchJoplinEvents('http://127.0.0.1:22300', 'session_abc');
      expect(res.ok).toBe(true);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:22300/api/events',
        expect.objectContaining({
          headers: { 'X-API-AUTH': 'session_abc' }
        })
      );
    });

    it('fetchJoplinEvents fetches events with cursor query parameter', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], has_more: false }) });

      const res = await fetchJoplinEvents('http://127.0.0.1:22300', 'session_abc', 'cursor_999');
      expect(res.ok).toBe(true);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:22300/api/events?cursor=cursor_999',
        expect.objectContaining({
          headers: { 'X-API-AUTH': 'session_abc' }
        })
      );
    });

    it('checkJoplinSyncInfo fetches root:/info.json:/content with manual redirect', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200 });

      const res = await checkJoplinSyncInfo('http://127.0.0.1:22300', 'session_abc');
      expect(res.ok).toBe(true);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:22300/api/items/root:/info.json:/content',
        expect.objectContaining({
          headers: { 'X-API-AUTH': 'session_abc' },
          redirect: 'manual'
        })
      );
    });

    it('triggerInternalEmbedding posts texts to /http-api/internal/embed', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ embeddings: [[0.1, 0.2]] }) });

      const payload = { texts: ['Hello Joplin'] };
      const res = await triggerInternalEmbedding('http://127.0.0.1:8000', payload);
      expect(res.ok).toBe(true);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/http-api/internal/embed',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
      );
    });
  });
});
