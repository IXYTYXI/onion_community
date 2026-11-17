import { marked } from 'marked';

function escapeAttribute(value) {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
}

export function renderInstallMarkdown(source) {
  const renderer = new marked.Renderer();
  // The guide is a published file. Keep its Markdown formatting, but never
  // interpret embedded HTML or executable/external image content.
  renderer.html = () => '';
  renderer.image = () => '';
  renderer.link = function (token) {
    const label = this.parser.parseInline(token.tokens);
    let url;
    try {
      url = new URL(token.href, 'https://ai.lab.yc345.tv/files/d/');
    } catch {
      return label;
    }
    if (!['http:', 'https:'].includes(url.protocol)) return label;
    return `<a href="${escapeAttribute(url.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  };
  // The published guide uses bare ~ for home directories. GFM treats pairs of
  // those characters as strikethrough delimiters across the same paragraph.
  return marked.parse(source, { renderer, gfm: false });
}
