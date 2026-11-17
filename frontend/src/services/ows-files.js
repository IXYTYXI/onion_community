const CACHE_NAME = 'ows-connect-files-v1';
const FILES = new Set(['ows-install.md', 'ows-release.json']);

function fileUrl(filename) {
  if (!FILES.has(filename)) throw new Error('未知的接入文件');
  return `/api/v1/ows-release/files/${filename}`;
}

async function fileCache() {
  try {
    return globalThis.caches ? await caches.open(CACHE_NAME) : null;
  } catch {
    return null;
  }
}

export async function readCachedOwsFile(filename) {
  const cache = await fileCache();
  if (!cache) return '';
  try {
    const response = await cache.match(fileUrl(filename));
    return response?.ok ? await response.text() : '';
  } catch {
    return '';
  }
}

export async function fetchAndCacheOwsFile(filename) {
  const url = fileUrl(filename);
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error('文件暂时无法读取');
  const content = await response.text();
  const cache = await fileCache();
  if (cache) {
    const type = filename.endsWith('.json') ? 'application/json' : 'text/markdown';
    try {
      await cache.put(url, new Response(content, { headers: { 'Content-Type': `${type}; charset=utf-8` } }));
    } catch {
      // Private browsing and storage limits must not prevent reading the file.
    }
  }
  return content;
}
