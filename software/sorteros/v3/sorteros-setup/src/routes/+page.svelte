<script lang="ts">
    import { patchImage, type SorterosConfig } from '$lib/img-patch';

    let file: File | null = $state(null);
    let hostname = $state('sorter');
    let ssid = $state('');
    let password = $state('');
    let sshKey = $state('');
    let status = $state('');
    let statusKind: 'info' | 'success' | 'danger' = $state('info');
    let busy = $state(false);

    async function handlePatch() {
        if (!file) {
            statusKind = 'danger';
            status = 'Pick an image file first.';
            return;
        }
        busy = true;
        statusKind = 'info';
        status = 'Patching image...';
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
            statusKind = 'success';
            status = 'Done. Flash with balenaEtcher.';
        } catch (e: unknown) {
            statusKind = 'danger';
            status = `Error: ${e instanceof Error ? e.message : String(e)}`;
        } finally {
            busy = false;
        }
    }

    function pickFile(e: Event) {
        const files = (e.currentTarget as HTMLInputElement).files;
        file = files?.[0] ?? null;
    }
</script>

<svelte:head>
    <title>sorter — setup</title>
</svelte:head>

<main class="mx-auto min-h-screen max-w-xl p-6">
    <header class="mb-10">
        <p class="text-text-muted text-xs font-semibold tracking-wider uppercase">basically</p>
        <h1 class="mt-1 text-2xl font-semibold">sorteros setup</h1>
        <p class="text-text-muted mt-2 text-sm">
            Customize your sorter image before flashing. Everything stays in your
            browser — nothing is uploaded.
        </p>
    </header>

    <section class="space-y-4">
        <div>
            <label for="img" class="mb-2 block text-sm font-medium">SorterOS .img file</label>
            <input
                id="img"
                type="file"
                accept=".img"
                onchange={pickFile}
                class="setup-control text-sm"
            />
        </div>

        <div>
            <label for="hostname" class="mb-2 block text-sm font-medium">Hostname</label>
            <input
                id="hostname"
                type="text"
                bind:value={hostname}
                class="setup-control text-sm"
            />
        </div>

        <div>
            <label for="ssid" class="mb-2 block text-sm font-medium">Wi-Fi SSID</label>
            <input
                id="ssid"
                type="text"
                bind:value={ssid}
                placeholder="optional — leave blank to use AP setup on the device"
                class="setup-control text-sm"
            />
        </div>

        <div>
            <label for="pw" class="mb-2 block text-sm font-medium">Wi-Fi password</label>
            <input
                id="pw"
                type="password"
                bind:value={password}
                autocomplete="off"
                class="setup-control text-sm"
            />
        </div>

        <div>
            <label for="ssh" class="mb-2 block text-sm font-medium">SSH public key</label>
            <textarea
                id="ssh"
                bind:value={sshKey}
                rows={3}
                placeholder="optional — ssh-ed25519 AAAA..."
                class="setup-control font-mono text-sm"
            ></textarea>
        </div>

        <button
            onclick={handlePatch}
            disabled={busy}
            class="setup-button-primary text-sm"
        >
            Customize &amp; download
        </button>

        {#if status}
            {@const kindToBorder = {
                info: 'border-text-muted/40',
                success: 'border-success/40',
                danger: 'border-danger/40'
            }}
            {@const kindToText = {
                info: 'text-text',
                success: 'text-success',
                danger: 'text-danger'
            }}
            <div
                class={'border bg-surface/40 p-3 text-sm ' +
                    kindToBorder[statusKind] +
                    ' ' +
                    kindToText[statusKind]}
                role="status"
            >
                {status}
            </div>
        {/if}
    </section>

    <footer class="text-text-muted mt-12 space-y-1 text-xs">
        <p>
            Leave the Wi-Fi SSID blank to make the sorter boot into AP mode — you'll
            join its hotspot from your phone and pick a network there.
        </p>
        <p>Files never leave your browser. This page is fully client-side.</p>
    </footer>
</main>
