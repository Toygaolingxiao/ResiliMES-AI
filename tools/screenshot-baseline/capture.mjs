/**
 * Capture the Wave 0 screenshot matrix.
 *
 * Usage (from repo root, with the demo server already running):
 *   cd tools/screenshot-baseline && npm install && npm run capture -- --base http://127.0.0.1:8000
 *
 * Does not modify or rebuild the served app. Writes PNGs under ./baselines/
 * and a manifest.json of paths + metadata.
 */
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dir = dirname(fileURLToPath(import.meta.url));
const matrix = JSON.parse(readFileSync(join(__dir, "matrix.json"), "utf8"));

function arg(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
}

const base = arg("base", "http://127.0.0.1:8000").replace(/\/$/, "");
const outDir = arg("out", join(__dir, "baselines"));
mkdirSync(outDir, { recursive: true });

function stretchText(root = document.body, factor = 1.35) {
  if (!root) return;
  const walk = (node) => {
    if (node.nodeType === 3) {
      const t = node.nodeValue;
      if (t && /\S/.test(t) && t.trim().length > 1) {
        node.nodeValue = t.replace(/\S+/g, (w) => w + "x".repeat(Math.max(1, Math.round(w.length * (factor - 1)))));
      }
      return;
    }
    if (node.nodeType === 1 && node.tagName !== "SCRIPT" && node.tagName !== "STYLE") {
      for (const child of [...node.childNodes]) walk(child);
    }
  };
  walk(root);
}

async function applyPrefs(page, lang, theme) {
  await page.addInitScript(
    ({ langKey, themeKey, lang, theme }) => {
      try {
        localStorage.setItem(langKey, lang);
        if (theme === "dark") localStorage.setItem(themeKey, "dark");
        else localStorage.removeItem(themeKey);
      } catch (_) {}
    },
    {
      langKey: matrix.storage.lang,
      themeKey: matrix.storage.theme,
      lang,
      theme,
    },
  );
}

async function shot(page, pageSpec, lang, theme, width, { pseudo = false } = {}) {
  await page.setViewportSize({ width, height: matrix.height_px });
  await applyPrefs(page, lang, theme);
  await page.goto(base + pageSpec.path, { waitUntil: "networkidle" });
  if (theme === "dark") {
    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
    });
  } else {
    await page.evaluate(() => {
      delete document.documentElement.dataset.theme;
    });
  }
  await page.evaluate((lang) => {
    localStorage.setItem("resilimes.lang", lang);
    document.documentElement.lang = lang === "zh" ? "zh-Hans" : lang;
    document.querySelectorAll("[data-lang]").forEach((btn) => {
      if (btn.getAttribute("data-lang") === lang) btn.click();
    });
  }, lang);
  if (pageSpec.ready_selector) {
    await page.waitForSelector(pageSpec.ready_selector, { timeout: 15000 });
  }
  if (pseudo) {
    await page.evaluate(stretchText);
  }
  const name = [
    pageSpec.id,
    lang,
    theme,
    `${width}w`,
    pseudo ? "pseudo" : null,
  ]
    .filter(Boolean)
    .join("__");
  const file = join(outDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return { id: name, file, page: pageSpec.id, lang, theme, width, pseudo };
}

const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
const shots = [];

try {
  for (const pageSpec of matrix.pages) {
    if (pageSpec.pseudo_l10n) {
      for (const lang of matrix.pseudo_langs) {
        for (const theme of matrix.pseudo_themes) {
          for (const width of matrix.pseudo_widths) {
            shots.push(await shot(page, pageSpec, lang, theme, width, { pseudo: true }));
          }
        }
      }
      continue;
    }
    for (const lang of matrix.langs) {
      for (const theme of matrix.themes) {
        for (const width of matrix.widths_px) {
          shots.push(await shot(page, pageSpec, lang, theme, width));
        }
      }
    }
  }
} finally {
  await browser.close();
}

if (shots.length !== matrix.expected_shot_count) {
  console.error(
    `shot count ${shots.length} != expected ${matrix.expected_shot_count}`,
  );
  process.exitCode = 1;
}

writeFileSync(
  join(outDir, "manifest.json"),
  JSON.stringify({ captured_at: new Date().toISOString(), base, shots }, null, 2),
);
console.log(`wrote ${shots.length} shots → ${outDir}`);
