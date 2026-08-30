const fs = require("fs");
const os = require("os");
const path = require("path");
const createDecryptor = require("../../experiments/decrypt/decrypt.js");

const FORENSICS_FLAG = path.join(os.tmpdir(), "arbscanner-bk-prematch-forensics.done");
const FORENSICS_FILE = path.join(os.tmpdir(), "arbscanner-bk-prematch-forensics.json");

function typeName(value) {
    if (value === null) return "null";
    if (Array.isArray(value)) return "list";
    return typeof value;
}

function summarize(value, depth, maxDepth) {
    if (value === null) return "null";
    if (Array.isArray(value)) {
        const first = value.length && depth < maxDepth
            ? summarize(value[0], depth + 1, maxDepth)
            : (value.length ? typeName(value[0]) : null);
        return { type: "list", length: value.length, first };
    }
    if (typeof value === "object") {
        const keys = Object.keys(value);
        if (depth >= maxDepth) {
            return { type: "dict", keys: keys.slice(0, 24) };
        }
        const fields = {};
        for (const key of keys.slice(0, 24)) {
            fields[key] = summarize(value[key], depth + 1, maxDepth);
        }
        return { type: "dict", keys, fields };
    }
    if (typeof value === "string") return `str(len=${value.length})`;
    return typeof value;
}

function looksLikeEvent(node) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return false;
    const home = node.EHT || node.HT || node.home;
    const away = node.EAT || node.AT || node.away;
    return Boolean(home && away);
}

function findFirstEvent(node) {
    if (looksLikeEvent(node)) return node;
    if (Array.isArray(node)) {
        for (const item of node) {
            const found = findFirstEvent(item);
            if (found) return found;
        }
    } else if (node && typeof node === "object") {
        for (const value of Object.values(node)) {
            const found = findFirstEvent(value);
            if (found) return found;
        }
    }
    return null;
}

function dumpForensicsOnce(parsed, tournamentId) {
    if (fs.existsSync(FORENSICS_FLAG)) return;
    try {
        fs.writeFileSync(FORENSICS_FLAG, "1", "utf8");
        const firstEvent = findFirstEvent(parsed);
        const markets = firstEvent
            ? (firstEvent.StakeTypes || firstEvent.stakeTypes || firstEvent.Markets || [])
            : [];
        const firstMarket = Array.isArray(markets) ? markets[0] : null;
        let matchOdds = null;
        if (Array.isArray(markets)) {
            for (const market of markets) {
                const stakes = (market && (market.Stakes || market.stakes)) || [];
                const mapped = {};
                for (const stake of stakes) {
                    const token = String((stake && (stake.SN || stake.N)) || "").toLowerCase();
                    if (token === "1" || token === "home") mapped.home = stake;
                    else if (token === "x" || token === "draw") mapped.draw = stake;
                    else if (token === "2" || token === "kazanan2" || token === "away") mapped.away = stake;
                }
                if (mapped.home && mapped.draw && mapped.away) {
                    matchOdds = {
                        marketId: market.Id,
                        marketName: market.N,
                        home: { SN: mapped.home.SN, N: mapped.home.N, F: mapped.home.F, IsL: mapped.home.IsL },
                        draw: { SN: mapped.draw.SN, N: mapped.draw.N, F: mapped.draw.F, IsL: mapped.draw.IsL },
                        away: { SN: mapped.away.SN, N: mapped.away.N, F: mapped.away.F, IsL: mapped.away.IsL },
                    };
                    break;
                }
            }
        }
        const dump = {
            capturedAt: new Date().toISOString(),
            tournamentId: tournamentId || null,
            rootType: Array.isArray(parsed) ? "list" : typeof parsed,
            rootKeys: parsed && typeof parsed === "object" && !Array.isArray(parsed)
                ? Object.keys(parsed)
                : [],
            structure: summarize(parsed, 0, 4),
            eventCountHint: firstEvent ? "at_least_1" : "none_found",
            firstEventKeys: firstEvent ? Object.keys(firstEvent) : [],
            firstEventTeams: firstEvent
                ? {
                    home: firstEvent.EHT || firstEvent.HT || firstEvent.home || null,
                    away: firstEvent.EAT || firstEvent.AT || firstEvent.away || null,
                    eventId: firstEvent.Id || firstEvent.EN || null,
                    tournamentHint: firstEvent.CId || firstEvent.RId || null,
                }
                : null,
            marketCount: Array.isArray(markets) ? markets.length : 0,
            firstMarketKeys: firstMarket ? Object.keys(firstMarket) : [],
            firstMarketMeta: firstMarket
                ? {
                    Id: firstMarket.Id,
                    N: firstMarket.N,
                    stakeCount: Array.isArray(firstMarket.Stakes) ? firstMarket.Stakes.length : null,
                    firstStakeKeys: firstMarket.Stakes && firstMarket.Stakes[0]
                        ? Object.keys(firstMarket.Stakes[0])
                        : [],
                    firstStake: firstMarket.Stakes && firstMarket.Stakes[0]
                        ? {
                            Id: firstMarket.Stakes[0].Id,
                            N: firstMarket.Stakes[0].N,
                            SN: firstMarket.Stakes[0].SN,
                            F: firstMarket.Stakes[0].F,
                            IsL: firstMarket.Stakes[0].IsL,
                            IsA: firstMarket.Stakes[0].IsA,
                        }
                        : null,
                }
                : null,
            matchOdds1x2: matchOdds,
        };
        fs.writeFileSync(FORENSICS_FILE, JSON.stringify(dump, null, 2), "utf8");
        process.stderr.write(`[BETKANYON PREMATCH FORENSICS] wrote ${FORENSICS_FILE}\n`);
    } catch (err) {
        // Forensics must never fail decryption.
    }
}

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
                dumpForensicsOnce(output[id], id);
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
    dumpForensicsOnce(parsed, null);
    fs.mkdirSync(path.dirname(outputFile), { recursive: true });
    fs.writeFileSync(outputFile, JSON.stringify(parsed), "utf8");
})();
