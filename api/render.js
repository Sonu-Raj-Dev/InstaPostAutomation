// Vercel Node function: renders 1080x1350 slides / guide pages with serverless Chromium and stores them in Vercel Blob.
// Called only by the Python app (src/media.py) with a key derived from APP_SECRET/APP_PASSWORD.
import crypto from "node:crypto";
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { put } from "@vercel/blob";

const W = 1080, H = 1350;
const internalKey = () =>
  crypto.createHash("sha256").update(`render:${process.env.APP_SECRET || process.env.APP_PASSWORD || "local-dev"}`).digest("hex");

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const key = req.headers["x-internal-key"] || "";
  const want = internalKey();
  if (key.length !== want.length || !crypto.timingSafeEqual(Buffer.from(key), Buffer.from(want))) {
    return res.status(401).json({ error: "unauthorized" });
  }
  const { action, html, names, prefix, path, data, contentType } = req.body || {};
  try {
    if (action === "put") {
      const blob = await put(path, Buffer.from(data, "base64"), { access: "public", contentType, addRandomSuffix: true });
      return res.json({ url: blob.url });
    }
    if (!html || !Array.isArray(names) || !names.length || names.length > 12) return res.status(400).json({ error: "html and 1-12 names required" });
    const browser = await puppeteer.launch({
      args: chromium.args,
      executablePath: await chromium.executablePath(),
      headless: true,
      defaultViewport: { width: W, height: H * names.length, deviceScaleFactor: 1 },
    });
    try {
      const page = await browser.newPage();
      await page.setContent(html, { waitUntil: "networkidle0", timeout: 45000 });
      await page.evaluate(() => document.fonts.ready);
      // broken remote images: drop their frame instead of showing an empty box
      await page.evaluate(() => document.querySelectorAll("img").forEach((i) => { if (!i.complete || !i.naturalWidth) i.parentNode && i.parentNode.remove(); }));
      const urls = [];
      for (let i = 0; i < names.length; i++) {
        const buf = await page.screenshot({ type: "jpeg", quality: 92, clip: { x: 0, y: i * H, width: W, height: H } });
        const blob = await put(`${prefix}/${names[i]}`, buf, { access: "public", contentType: "image/jpeg", addRandomSuffix: true });
        urls.push(blob.url);
      }
      return res.json({ urls });
    } finally {
      await browser.close();
    }
  } catch (e) {
    return res.status(500).json({ error: String(e && e.message || e).slice(0, 300) });
  }
}
