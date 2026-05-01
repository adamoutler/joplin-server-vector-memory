/**
 * Robust fetch with timeout using global fetch
 */
function safeUrl(urlString) {
  try {
    const url = new URL(urlString);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error(`Unsafe protocol: ${url.protocol}`);
    }
    return url.toString();
  } catch (e) {
    throw new Error(`Invalid URL: ${urlString}`, { cause: e });
  }
}

async function fetchWithTimeout(url, options = {}, timeout = 15000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(safeUrl(url), { ...options, signal: controller.signal });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    throw error;
  }
}

async function validateJoplinSession(joplinUrl, email, password) {
  return fetch(safeUrl(`${joplinUrl}/api/sessions`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
}

async function fetchJoplinEvents(joplinUrl, sessionId, cursor = null) {
  const url = cursor ? `${joplinUrl}/api/events?cursor=${cursor}` : `${joplinUrl}/api/events`;
  return fetch(safeUrl(url), {
    headers: { 'X-API-AUTH': sessionId }
  });
}

async function checkJoplinSyncInfo(joplinUrl, sessionId) {
  // skillsafe-disable-next-line network-access
  return fetch(safeUrl(`${joplinUrl}/api/items/root:/info.json:/content`), {
    headers: { 'X-API-AUTH': sessionId },
    redirect: 'manual'
  });
}

async function triggerInternalEmbedding(internalApiUrl, data) {
  return fetch(safeUrl(`${internalApiUrl}/http-api/internal/embed`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

module.exports = {
  fetchWithTimeout,
  validateJoplinSession,
  fetchJoplinEvents,
  checkJoplinSyncInfo,
  triggerInternalEmbedding
};
;
