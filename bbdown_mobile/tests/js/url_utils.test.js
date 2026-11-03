const assert = require("assert");
const { extractUrlFromText } = require("../../static/url_utils");

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

console.log(`url_utils: ${cases.length} passed`);
