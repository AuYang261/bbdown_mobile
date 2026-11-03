(function (root, factory) {
  const utils = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = utils;
  }
  root.extractUrlFromText = utils.extractUrlFromText;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const URL_PATTERN = /https?:\/\/[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+/i;
  const TRAILING_PUNCTUATION = /[.,;:!?)\]}>]+$/;

  function extractUrlFromText(text) {
    const original = String(text == null ? "" : text).trim();
    const match = original.match(URL_PATTERN);
    return match ? match[0].replace(TRAILING_PUNCTUATION, "") : original;
  }

  return { extractUrlFromText };
});
