// svg_to_png.js - Renders SVG files to PNG using Puppeteer (2D, no WebGL needed)
const puppeteer = require("puppeteer");
const path = require("path");
const fs = require("fs");

(async () => {
    const [inputSvg, outputPng, width = 2000, height = 1400] = process.argv.slice(2);
    if (!inputSvg || !outputPng) {
        console.error("Usage: node svg_to_png.js <input.svg> <output.png> [width] [height]");
        process.exit(1);
    }

    const absSvg = path.resolve(inputSvg);
    if (!fs.existsSync(absSvg)) {
        console.error("Not found: " + absSvg);
        process.exit(1);
    }

    const svgContent = fs.readFileSync(absSvg, "utf-8");

    // Wrap SVG in minimal HTML
    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
      body { margin: 0; padding: 0; background: white; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
      svg { max-width: 100%; height: auto; }
    </style></head><body>${svgContent}</body></html>`;

    const browser = await puppeteer.launch({
        headless: "new",
        args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
    });

    try {
        const page = await browser.newPage();
        const w = parseInt(width), h = parseInt(height);
        await page.setViewport({ width: w, height: h });

        await page.setContent(html, { waitUntil: "load", timeout: 15000 });

        // Wait for SVG to render (usually instant)
        await new Promise(r => setTimeout(r, 500));

        const outDir = path.dirname(outputPng);
        if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

        await page.screenshot({ path: outputPng, type: "png", fullPage: true });
        console.log("CONVERTED:" + outputPng);
    } catch (e) {
        console.error("FAILED:" + e.message);
        process.exit(1);
    } finally {
        await browser.close();
    }
})();
