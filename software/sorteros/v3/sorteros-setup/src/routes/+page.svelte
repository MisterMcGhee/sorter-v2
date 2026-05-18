<script lang="ts">
    import { patchImage, type SorterosConfig } from '$lib/img-patch';

    let file: File | null = $state(null);
    let hostname = $state('sorter');
    let ssid = $state('');
    let password = $state('');
    let sshKey = $state('');
    let status = $state('');
    let busy = $state(false);

    async function handlePatch() {
        if (!file) { status = 'Pick an .img file first.'; return; }
        busy = true;
        status = 'Patching...';
        try {
            const buf = await file.arrayBuffer();
            const cfg: SorterosConfig = {
                hostname,
                wifi: ssid ? { ssid, password } : undefined,
                ssh_authorized_key: sshKey || undefined
            };
            const out = patchImage(buf, cfg);
            const blob = new Blob([out], { type: 'application/octet-stream' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = file.name.replace(/\.img$/, '') + '-customized.img';
            a.click();
            status = 'Done. Flash with balenaEtcher.';
        } catch (e: any) {
            status = `Error: ${e.message}`;
        } finally {
            busy = false;
        }
    }
</script>

<svelte:head>
    <title>sorter — setup</title>
</svelte:head>

<main class="min-h-screen max-w-xl mx-auto p-6">
    <header class="mb-10">
        <p class="text-xs font-semibold tracking-wider uppercase text-neutral-400">basically</p>
        <h1 class="text-2xl font-semibold mt-1">sorteros setup</h1>
        <p class="text-sm text-neutral-400 mt-2">
            Customize your sorter image before flashing. Everything stays in your
            browser — nothing is uploaded.
        </p>
    </header>

    <section class="space-y-4">
        <div>
            <label for="img" class="block text-sm font-medium mb-2">SorterOS .img file</label>
            <input id="img" type="file" accept=".img"
                onchange={(e) => file = (e.currentTarget as HTMLInputElement).files?.[0] ?? null}
                class="w-full text-sm bg-neutral-900 border border-neutral-700 px-3 py-2" />
        </div>

        <div>
            <label for="hostname" class="block text-sm font-medium mb-2">Hostname</label>
            <input id="hostname" type="text" bind:value={hostname}
                class="w-full text-sm bg-neutral-900 border border-neutral-700 px-3 py-2" />
        </div>

        <div>
            <label for="ssid" class="block text-sm font-medium mb-2">Wi-Fi SSID</label>
            <input id="ssid" type="text" bind:value={ssid} placeholder="optional"
                class="w-full text-sm bg-neutral-900 border border-neutral-700 px-3 py-2" />
        </div>

        <div>
            <label for="pw" class="block text-sm font-medium mb-2">Wi-Fi password</label>
            <input id="pw" type="password" bind:value={password} autocomplete="off"
                class="w-full text-sm bg-neutral-900 border border-neutral-700 px-3 py-2" />
        </div>

        <div>
            <label for="ssh" class="block text-sm font-medium mb-2">SSH public key</label>
            <textarea id="ssh" bind:value={sshKey} rows="3" placeholder="optional — ssh-ed25519 AAAA…"
                class="w-full text-sm bg-neutral-900 border border-neutral-700 px-3 py-2 font-mono"></textarea>
        </div>

        <button onclick={handlePatch} disabled={busy}
            class="w-full bg-yellow-400 text-black font-semibold py-3 text-sm disabled:opacity-50">
            Customize &amp; download
        </button>

        {#if status}
            <p class="text-sm text-neutral-400">{status}</p>
        {/if}
    </section>

    <footer class="mt-12 text-xs text-neutral-500 space-y-1">
        <p>If the SSID is empty, the sorter will boot into AP mode so you can
        configure Wi-Fi from your phone after flashing.</p>
        <p>Files never leave your browser.</p>
    </footer>
</main>
