const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const {
  extractUrlFromText,
  normalizeDownloadUrlInput,
} = require("../../static/url_utils");

const cases = [
  [
    "【测试视频】 https://b23.tv/kkwWxgx，分享自哔哩哔哩",
    "https://b23.tv/kkwWxgx",
  ],
  [
    "标题文字\nhttps://www.bilibili.com/video/BV1ZpdVBgEz1/?p=4。",
    "https://www.bilibili.com/video/BV1ZpdVBgEz1/?p=4",
  ],
  ["BV1ZpdVBgEz1", "BV1ZpdVBgEz1"],
];

for (const [input, expected] of cases) {
  assert.strictEqual(extractUrlFromText(input), expected);
}

const input = { value: "【测试视频】 https://b23.tv/kkwWxgx，分享自哔哩哔哩" };
assert.strictEqual(normalizeDownloadUrlInput(input), "https://b23.tv/kkwWxgx");
assert.strictEqual(input.value, "https://b23.tv/kkwWxgx");

const browserContext = {};
vm.createContext(browserContext);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../../static/url_utils.js"), "utf8"),
  browserContext
);
assert.strictEqual(typeof browserContext.extractUrlFromText, "function");
assert.strictEqual(typeof browserContext.normalizeDownloadUrlInput, "function");

console.log(`url_utils: ${cases.length + 2} passed`);
