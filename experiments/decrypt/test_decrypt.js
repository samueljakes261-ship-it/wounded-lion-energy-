const fs = require("fs");
const path = require("path");
const createDecryptor = require("./decrypt.js");

(async () => {
    console.log("Loading decryptor...");

    const decryptor = await createDecryptor();

    console.log("Loaded successfully.");

    decryptor.wasmAlloc = decryptor.cwrap("wasm_alloc", "number", ["number"]);
    decryptor.wasmFree = decryptor.cwrap("wasm_free", null, ["number"]);
    decryptor.wasmDecrypt = decryptor.cwrap("wasm_decrypt", "number", ["number", "number"]);
    decryptor.wasmGetResult = decryptor.cwrap("wasm_get_result", "number", []);
    decryptor.wasmGetResultLen = decryptor.cwrap("wasm_get_result_len", "number", []);
    decryptor.wasmFreeResult = decryptor.cwrap("wasm_free_result", null, []);

    console.log("All WASM functions loaded.");

    //---------------------------------------
    // Read encrypted payload from a file
    //---------------------------------------

    const inputFile = process.argv[2];

    if (!inputFile) {
        console.log("");
        console.log("Usage:");
        console.log("node test_decrypt.js payload.txt");
        process.exit(1);
    }

    const payload = fs.readFileSync(inputFile, "utf8").trim();

    //---------------------------------------
    // Decode Base64
    //---------------------------------------

    const bytes = Uint8Array.from(Buffer.from(payload, "base64"));

    console.log("Payload bytes:", bytes.length);

    //---------------------------------------
    // Allocate WASM memory
    //---------------------------------------

    const ptr = decryptor.wasmAlloc(bytes.length);

    decryptor.HEAPU8.set(bytes, ptr);

    //---------------------------------------
    // Decrypt
    //---------------------------------------

    const resultCode = decryptor.wasmDecrypt(ptr, bytes.length);

    console.log("Decrypt return code:", resultCode);

    decryptor.wasmFree(ptr);

    if (resultCode !== 0) {
        console.log("Decryption failed.");
        process.exit(1);
    }

    //---------------------------------------
    // Get decrypted JSON
    //---------------------------------------

    const resultPtr = decryptor.wasmGetResult();
    const resultLen = decryptor.wasmGetResultLen();

    const text = decryptor.UTF8ToString(resultPtr, resultLen);

    decryptor.wasmFreeResult();

    //---------------------------------------
    // Save JSON
    //---------------------------------------

    const outputPath = path.join(__dirname, "decrypted_output.json");

    fs.writeFileSync(outputPath, text, "utf8");

    console.log("");
    console.log(`Saved decrypted JSON (${resultLen} bytes)`);
    console.log(outputPath);

    console.log("");
    console.log("First 500 characters:");
    console.log("---------------------------------------");
    console.log(text.substring(0, 500));
    console.log("---------------------------------------");
})();