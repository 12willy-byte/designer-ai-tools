// headless_render.js v5 - Software WebGL via SwiftShader for headless GPU-less servers
const puppeteer = require("puppeteer");
const path = require("path");
const fs = require("fs");
const os = require("os");

(async () => {
    const [inputHtml, outputPng, width = 1280, height = 720] = process.argv.slice(2);
    if (!inputHtml || !outputPng) {
        console.error("Usage: node headless_render.js <html> <png> [w] [h]");
        process.exit(1);
    }

    const absHtml = path.resolve(inputHtml);
    if (!fs.existsSync(absHtml)) {
        console.error("Not found: " + absHtml);
        process.exit(1);
    }

    const threeModulePath = path.resolve(__dirname, "..", "node_modules", "three", "build", "three.module.js");
    const threeAddonsPath = path.resolve(__dirname, "..", "node_modules", "three", "examples", "jsm");

    if (!fs.existsSync(threeModulePath)) {
        console.error("three.module.js not found at: " + threeModulePath);
        process.exit(1);
    }

    let htmlContent = fs.readFileSync(absHtml, "utf-8");

    const fileThree = "file:///" + threeModulePath.replace(/\\/g, "/");
    const fileAddons = "file:///" + threeAddonsPath.replace(/\\/g, "/") + "/";
    const importMapLocal = JSON.stringify({
        imports: {
            "three": fileThree,
            "three/addons/": fileAddons
        }
    });

    htmlContent = htmlContent.replace(
        /<script type="importmap">[\s\S]*?<\/script>/,
        '<script type="importmap">' + importMapLocal + "</script>"
    );

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "codex-render-"));
    const tmpHtml = path.join(tmpDir, "scene.html");
    fs.writeFileSync(tmpHtml, htmlContent, "utf-8");
    console.log("[headless] Patched HTML: " + tmpHtml);

    const browser = await puppeteer.launch({
        headless: "new",
        args: [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--use-gl=swiftshader",        // Software WebGL
            "--enable-webgl",
            "--allow-file-access-from-files"
        ]
    });

    try {
        const page = await browser.newPage();
        await page.setViewport({ width: parseInt(width), height: parseInt(height) });

        page.on("console", msg => console.log("[PAGE]", msg.text()));
        page.on("pageerror", err => console.log("[PAGE ERROR]", err.message));

        await page.goto("file:///" + tmpHtml.replace(/\\/g, "/"), {
            waitUntil: "load",
            timeout: 45000
        });

        // Wait for WebGL canvas
        let canvasReady = false;
        for (let i = 0; i < 60; i++) {
            const ready = await page.evaluate(() => {
                const c = document.querySelector("canvas");
                if (!c || c.width === 0 || c.height === 0) return false;
                const gl = c.getContext("webgl2") || c.getContext("webgl");
                if (!gl) return false;
                const pixel = new Uint8Array(4);
                gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
                return pixel[0] > 0 || pixel[1] > 0 || pixel[2] > 0;
            });
            if (ready) { canvasReady = true; break; }
            await new Promise(r => setTimeout(r, 500));
        }

        if (!canvasReady) {
            // Fallback: try to get any screenshot
            console.error("[headless] WebGL may not be rendering. Taking screenshot anyway...");
        }

        await new Promise(r => setTimeout(r, 2000));

        const outDir = path.dirname(outputPng);
        if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

        await page.screenshot({ path: outputPng, type: "png" });
        console.log("RENDERED:" + outputPng);
    } catch (e) {
        console.error("FAILED:" + e.message);
        process.exit(1);
    } finally {
        await browser.close();
        try { fs.unlinkSync(tmpHtml); fs.rmdirSync(tmpDir); } catch (_) {}
    }
})();
