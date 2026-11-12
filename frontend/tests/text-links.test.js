import test from "node:test";
import assert from "node:assert/strict";
import { textLinks } from "../src/services/text-links.js";

test("补交链接不包含后面的中文说明，且不丢失文本", () => {
  const url =
    "https://guanghe.feishu.cn/share/base/form/shrcnqFF2DE85xr8rOj67xbFCpg";
  const text = `补交表单 ${url}。该表单只用于异常处理，不作为常规入口。\n注意事项`;
  const parts = textLinks(text);
  assert.deepEqual(
    parts.filter((p) => p.href).map((p) => p.href),
    [url],
  );
  assert.equal(parts.map((p) => p.text).join(""), text);
});
test("保留参数、编码、多个链接及周边标点", () => {
  const text =
    "入口：https://example.com/a?x=1&name=%E4%B8%AD，指南（https://example.com/b）。";
  const parts = textLinks(text);
  assert.equal(parts.filter((p) => p.href).length, 2);
  assert.equal(parts.map((p) => p.text).join(""), text);
  assert.equal(parts[1].href, "https://example.com/a?x=1&name=%E4%B8%AD");
});
test("无链接和不安全协议只作为普通文字", () => {
  assert.deepEqual(textLinks("javascript:alert(1)"), [
    { text: "javascript:alert(1)" },
  ]);
  assert.deepEqual(textLinks(), []);
});
