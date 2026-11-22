/** @type {import('@commitlint/types').UserConfig} */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    // 日本語の件名の先頭に英語の固有名詞 (Renovate, GitHub など) が来ると誤検知になるので、大文字小文字は検査しない
    "subject-case": [0],
  },
};
