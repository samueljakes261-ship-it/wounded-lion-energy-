const fs = require("fs");
const path = require("path");
const createDecryptor = require("../../experiments/decrypt/decrypt.js");

function decryptOne(decryptor, payload) {
    const bytes = Uint8Array.from(Buffer.from(String(payload).trim(), "base64"));
    const ptr = decryptor.wasmAlloc(bytes.length);
    decryptor.HEAPU8.set(bytes, ptr);
    const resultCode = decryptor.wasmDecrypt(ptr, bytes.length);
    decryptor.wasmFree(ptr);
    if (resultCode !== 0) {
        throw new Error("Decryption failed.");
    }
    const resultPtr = decryptor.wasmGetResult();
    const resultLen = decryptor.wasmGetResultLen();
    const text = decryptor.UTF8ToString(resultPtr, resultLen);
    decryptor.wasmFreeResult();
    return JSON.parse(text);
}

async function boot() {
    const decryptor = await createDecryptor();
    decryptor.wasmAlloc = decryptor.cwrap("wasm_alloc", "number", ["number"]);
    decryptor.wasmFree = decryptor.cwrap("wasm_free", null, ["number"]);
    decryptor.wasmDecrypt = decryptor.cwrap("wasm_decrypt", "number", ["number", "number"]);
    decryptor.wasmGetResult = decryptor.cwrap("wasm_get_result", "number", []);
    decryptor.wasmGetResultLen = decryptor.cwrap("wasm_get_result_len", "number", []);
    decryptor.wasmFreeResult = decryptor.cwrap("wasm_free_result", null, []);
    return decryptor;
}

(async () => {
    const mode = process.argv[2];
    const decryptor = await boot();

    if (mode === "--batch") {
        const inputFile = process.argv[3];
        const outputFile = process.argv[4];
        if (!inputFile || !outputFile) {
            process.stderr.write("Usage: node decrypt_cli.js --batch payloads.json out.json\n");
            process.exit(1);
        }
        const input = JSON.parse(fs.readFileSync(inputFile, "utf8"));
        const output = {};
        for (const [id, payload] of Object.entries(input)) {
            try {
                output[id] = decryptOne(decryptor, payload);
            } catch (err) {
                // Skip a single tournament rather than aborting the snapshot.
            }
        }
        fs.mkdirSync(path.dirname(outputFile), { recursive: true });
        fs.writeFileSync(outputFile, JSON.stringify(output), "utf8");
        return;
    }

    const inputFile = process.argv[2];
    const outputFile = process.argv[3];
    if (!inputFile || !outputFile) {
        process.stderr.write("Usage: node decrypt_cli.js payload.txt out.json\n");
        process.exit(1);
    }
    const payload = fs.readFileSync(inputFile, "utf8").trim();
    const parsed = decryptOne(decryptor, payload);
    fs.mkdirSync(path.dirname(outputFile), { recursive: true });
    fs.writeFileSync(outputFile, JSON.stringify(parsed), "utf8");
})();
