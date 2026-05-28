<script lang="ts">
	import { onMount } from 'svelte';
	import QRCode from 'qrcode';

	let { ssid, nextUrl, teardownInS = 5 }: {
		ssid: string;
		nextUrl: string;
		teardownInS?: number;
	} = $props();

	let qrDataUrl = $state<string | null>(null);
	let qrError = $state<string | null>(null);
	let remaining = $state(0);

	onMount(() => {
		remaining = teardownInS;
		QRCode.toDataURL(nextUrl, {
			width: 320,
			margin: 2,
			color: { dark: '#0a0a0a', light: '#ffffff' },
			errorCorrectionLevel: 'M'
		})
			.then((url) => {
				qrDataUrl = url;
			})
			.catch((err) => {
				qrError = err?.message ?? 'QR rendering failed';
			});

		const tick = setInterval(() => {
			remaining -= 1;
			if (remaining <= 0) {
				clearInterval(tick);
			}
		}, 1000);
		return () => clearInterval(tick);
	});
</script>

<div class="flex flex-col items-center gap-6 px-4 py-8 text-center">
	<div class="text-sm tracking-wider text-[var(--color-text-muted)] uppercase">
		Switching networks…
	</div>
	<h1 class="text-2xl font-semibold">
		Almost there!
	</h1>

	<p class="max-w-md text-[var(--color-text-muted)]">
		The sorter is joining <span class="font-medium text-[var(--color-text)]">{ssid}</span> now.
		Switch your phone or laptop to the same Wi-Fi, then open:
	</p>

	<a
		href={nextUrl}
		class="font-mono text-base break-all underline decoration-[var(--color-accent)] underline-offset-4 hover:text-[var(--color-accent)]"
	>
		{nextUrl}
	</a>

	<div class="mt-2 border border-[var(--color-border)] bg-white p-2">
		{#if qrDataUrl}
			<img src={qrDataUrl} alt="QR code for {nextUrl}" width="240" height="240" />
		{:else if qrError}
			<div class="m-8 max-w-[200px] text-xs text-[var(--color-danger)]">
				{qrError}
			</div>
		{:else}
			<div class="flex h-[240px] w-[240px] items-center justify-center text-xs text-[var(--color-text-muted)]">
				Generating QR…
			</div>
		{/if}
	</div>

	{#if remaining > 0}
		<div class="text-sm text-[var(--color-text-muted)]">
			This hotspot shuts down in <span class="font-mono">{remaining}s</span>.
		</div>
	{:else}
		<div class="text-sm text-[var(--color-text-muted)]">
			Hotspot is closing. If your phone hasn't reconnected automatically,
			pick <span class="text-[var(--color-text)]">{ssid}</span> in your Wi-Fi settings.
		</div>
	{/if}

	<div class="mt-4 max-w-md text-xs text-[var(--color-text-muted)]/80">
		Can't find the sorter on the new network? It also responds on its LAN IP — check your router's
		device list for the device named after a LEGO color.
	</div>
</div>
