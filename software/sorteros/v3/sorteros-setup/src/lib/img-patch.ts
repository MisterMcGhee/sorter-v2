// Byte-pattern search and in-place patch of the sorteros-config.toml
// placeholder inside a .img file. Runs entirely in the browser on a
// File / ArrayBuffer; nothing is uploaded.

const START_MARKER = '__SORTEROS_CFG_START__';
const END_MARKER = '__SORTEROS_CFG_END__';

export interface SorterosConfig {
    hostname?: string;
    wifi?: { ssid: string; password: string };
    ssh_authorized_key?: string;
}

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
    outer: for (let i = from; i <= haystack.length - needle.length; i++) {
        for (let j = 0; j < needle.length; j++) {
            if (haystack[i + j] !== needle[j]) continue outer;
        }
        return i;
    }
    return -1;
}

export function patchImage(buf: ArrayBuffer, cfg: SorterosConfig): ArrayBuffer {
    const bytes = new Uint8Array(buf);
    const enc = new TextEncoder();
    const startBytes = enc.encode(START_MARKER);
    const endBytes = enc.encode(END_MARKER);

    const start = indexOfBytes(bytes, startBytes);
    if (start < 0) throw new Error('start marker not found — wrong .img?');
    const end = indexOfBytes(bytes, endBytes, start + startBytes.length);
    if (end < 0) throw new Error('end marker not found');

    // The region between (and including) the markers is the placeholder.
    // We keep both markers intact so the file stays detectable / patchable
    // multiple times.
    const regionStart = start + startBytes.length;
    const regionEnd = end;
    const capacity = regionEnd - regionStart;

    const toml = buildToml(cfg);
    const tomlBytes = enc.encode(toml);
    if (tomlBytes.length > capacity) {
        throw new Error(
            `config too large: ${tomlBytes.length} bytes, capacity ${capacity}`
        );
    }

    // Overwrite with TOML, then pad the rest with newlines so it stays
    // valid TOML and the file size doesn't change.
    bytes.fill(0x0a, regionStart, regionEnd); // 0x0a = '\n'
    bytes.set(tomlBytes, regionStart);

    return bytes.buffer;
}

function buildToml(cfg: SorterosConfig): string {
    const lines: string[] = ['# written by sorteros-setup'];
    if (cfg.hostname) lines.push(`hostname = ${JSON.stringify(cfg.hostname)}`);
    if (cfg.wifi) {
        lines.push('', '[wifi]');
        lines.push(`ssid = ${JSON.stringify(cfg.wifi.ssid)}`);
        lines.push(`password = ${JSON.stringify(cfg.wifi.password)}`);
    }
    if (cfg.ssh_authorized_key) {
        lines.push('', '[ssh]');
        lines.push(`authorized_key = ${JSON.stringify(cfg.ssh_authorized_key)}`);
    }
    return lines.join('\n') + '\n';
}
