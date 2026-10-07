// Static check that auto-save wiring exists in app.js.
// "AI 设置未保存在本地，禁止每次去设置" → 用户改了 input 必须写 localStorage。

const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(
  path.join(__dirname, "..", "static", "app.js"),
  "utf8"
);

function assertContains(name, re, hint) {
  if (re.test(src)) {
    console.log("OK  " + name);
  } else {
    console.error("FAIL " + name + " — " + hint);
    process.exit(1);
  }
}

function assertNotContains(name, re, hint) {
  if (!re.test(src)) {
    console.log("OK  " + name);
  } else {
    console.error("FAIL " + name + " — " + hint);
    process.exit(1);
  }
}

// 1) bindAutoSave 函数存在
assertContains(
  "bindAutoSave function defined",
  /function bindAutoSave\s*\(/,
  "expected: function bindAutoSave()"
);

// 2) bindAutoSave 绑了 input change/blur
assertContains(
  "bindAutoSave listens to change event",
  /\.addEventListener\(\s*["']change["']/,
  "expected: .addEventListener('change', ...)"
);
assertContains(
  "bindAutoSave listens to blur event",
  /\.addEventListener\(\s*["']blur["']/,
  "expected: .addEventListener('blur', ...)"
);

// 3) bindAutoSave 绑的三个关键 input
assertContains(
  "bindAutoSave binds apiKey/baseUrl/model",
  /\[\s*\$apiKey\s*,\s*\$baseUrl\s*,\s*\$model\s*\]\.forEach/,
  "expected: [$apiKey, $baseUrl, $model].forEach"
);

// 4) hideSettings() 内调用 saveConfig() — modal 任何路径关闭都自动保存
assertContains(
  "hideSettings calls saveConfig (auto-save on close)",
  /function hideSettings\s*\(\s*\)\s*\{[\s\S]{0,200}?saveConfig\s*\(/,
  "expected: function hideSettings() { ... saveConfig() ... }"
);

// 5) init 调用 bindAutoSave
assertContains(
  "init() calls bindAutoSave()",
  /function init\s*\(\s*\)\s*\{[\s\S]{0,2000}?bindAutoSave\s*\(/,
  "expected: init() contains bindAutoSave()"
);

// 6) 没残留之前的 monkey-patch 死代码
assertNotContains(
  "no leftover window.hideSettings monkey-patch",
  /window\.hideSettings\s*=\s*function/,
  "leftover: window.hideSettings = function (should be removed)"
);
assertNotContains(
  "no leftover _patchHideSettings",
  /_patchHideSettings/,
  "leftover: _patchHideSettings"
);
assertNotContains(
  "no leftover _hideSettingsOriginal",
  /_hideSettingsOriginal/,
  "leftover: _hideSettingsOriginal"
);

console.log("\nAll auto-save wiring checks passed.");
