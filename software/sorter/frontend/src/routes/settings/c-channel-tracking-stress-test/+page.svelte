<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import ZoneSection from '$lib/components/settings/ZoneSection.svelte';
	import { Alert, Button, Input } from '$lib/components/primitives';
	import { onDestroy, onMount } from 'svelte';

	const manager = getMachinesContext();

	type TrialResult = {
		params: {
			speed_microsteps_per_second: number;
			pulse_steps: number;
			pause_ms: number;
			acceleration_microsteps_per_second_sq: number;
		};
		status:
			| 'pending'
			| 'delivered'
			| 'exited'
			| 'track_lost'
			| 'no_exit'
			| 'no_piece'
			| 'skipped';
		tracked_global_id: number | null;
		pulses_fired: number;
		duration_s: number;
		note: string | null;
	};

	type RunState = {
		id: string;
		started_at: number;
		ended_at: number | null;
		status:
			| 'running'
			| 'waiting_for_piece'
			| 'paused'
			| 'stopping'
			| 'completed'
			| 'stopped'
			| 'failed';
		current_trial_index: number | null;
		last_event: string | null;
		error: string | null;
		sweep: {
			top_speed: number;
			min_speed: number;
			speed_step: number;
			pulse_steps: number;
			start_pause_ms: number;
			max_pause_ms: number;
			pause_step_ms: number;
			acceleration_microsteps_per_second_sq: number;
			track_loss_grace_observations: number;
		};
		trials: TrialResult[];
	};

	let topSpeed = $state(5000);
	let minSpeed = $state(1500);
	let speedStep = $state(500);
	let pulseSteps = $state(1000);
	let startPauseMs = $state(0);
	let maxPauseMs = $state(0);
	let pauseStepMs = $state(0);
	let accel = $state(20000);
	let trackLossGraceObservations = $state(2);

	let runState = $state<RunState | null>(null);
	let active = $state(false);
	let errorMsg = $state<string | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let busy = $state(false);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected'
					? manager.selectedMachine.url
					: null
			) ?? getBackendHttpBase()
		);
	}

	async function refreshStatus() {
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/c-channel-tracking-stress-test/status`
			);
			if (!res.ok) return;
			const payload = await res.json();
			active = Boolean(payload?.active);
			runState = payload?.run ?? null;
		} catch {
			// transient network errors — keep last good state visible
		}
	}

	function startPolling() {
		stopPolling();
		pollTimer = setInterval(refreshStatus, 750);
	}

	function stopPolling() {
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	async function postAction(
		path: string,
		body?: Record<string, unknown>
	): Promise<void> {
		busy = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}${path}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: body ? JSON.stringify(body) : undefined
			});
			if (!res.ok) {
				let detail = `HTTP ${res.status}`;
				try {
					const payload = await res.json();
					if (payload?.detail) detail = String(payload.detail);
				} catch {
					/* ignore */
				}
				throw new Error(detail);
			}
			const payload = await res.json();
			active = Boolean(payload?.active);
			runState = payload?.run ?? null;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function startRun() {
		await postAction('/api/c-channel-tracking-stress-test/start', {
			top_speed: Number(topSpeed),
			min_speed: Number(minSpeed),
			speed_step: Number(speedStep),
			pulse_steps: Number(pulseSteps),
			start_pause_ms: Number(startPauseMs),
			max_pause_ms: Number(maxPauseMs),
			pause_step_ms: Number(pauseStepMs),
			acceleration_microsteps_per_second_sq: Number(accel),
			track_loss_grace_observations: Number(trackLossGraceObservations)
		});
		if (!errorMsg) startPolling();
	}

	async function pauseRun() {
		await postAction('/api/c-channel-tracking-stress-test/pause');
	}

	async function resumeRun() {
		await postAction('/api/c-channel-tracking-stress-test/resume');
	}

	async function stopRun() {
		await postAction('/api/c-channel-tracking-stress-test/stop');
	}

	function trialStatusColor(status: TrialResult['status']): string {
		switch (status) {
			case 'delivered':
			case 'exited':
				return 'text-success';
			case 'track_lost':
				return 'text-danger';
			case 'no_exit':
				return 'text-warning';
			case 'no_piece':
			case 'skipped':
				return 'text-text-muted';
			default:
				return 'text-text';
		}
	}

	onMount(() => {
		refreshStatus().then(() => {
			if (active) startPolling();
		});
	});

	onDestroy(stopPolling);
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="C-Channel 2 live feed"
		description="Same tracked video feed as the C-Channel 2 settings page. Watch the global_id of the piece in transit during a trial — if it vanishes mid-channel that's a track-lost result (too fast); if it falls off the exit zone that's a clean exit (good)."
	>
		<ZoneSection channels={['second']} stepperKey="c_channel_2" />
	</SectionCard>

	<SectionCard
		title="C-Channel Tracking Stress Test"
		description="Find the fastest C-channel pulse parameters that don't lose the vision track for the piece in transit. Per trial: pulse C1 at its current settings until a piece appears on C2's tracker, then run C2 at the trial's stress params and watch whether the same global_id reaches C3 or vanishes mid-pulse."
	>
		<Alert variant="info">
			<div class="text-sm">
				<p class="font-semibold">Setup</p>
				<p class="mt-1">
					Put a line of pieces into C-Channel 1 so it can carefully
					dispense one piece at a time. The test only works while the
					hardware is initialized and the machine is not actively sorting.
					C2's speed/acceleration are restored to production defaults when
					the run ends.
				</p>
			</div>
		</Alert>

		{#if errorMsg}
			<div class="mt-4">
				<Alert variant="danger">
					<div class="text-sm">{errorMsg}</div>
				</Alert>
			</div>
		{/if}

		<div class="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">
					Top speed (µsteps/sec) — start aggressive
				</span>
				<Input type="number" bind:value={topSpeed} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Min speed (µsteps/sec)</span>
				<Input type="number" bind:value={minSpeed} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Speed step (µsteps/sec per trial)</span>
				<Input type="number" bind:value={speedStep} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Pulse length (microsteps)</span>
				<Input type="number" bind:value={pulseSteps} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Start pause (ms) — start at 0</span>
				<Input type="number" bind:value={startPauseMs} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Max pause (ms)</span>
				<Input type="number" bind:value={maxPauseMs} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Pause step (ms)</span>
				<Input type="number" bind:value={pauseStepMs} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">Acceleration (µsteps/sec²)</span>
				<Input type="number" bind:value={accel} disabled={active} />
			</label>
			<label class="flex flex-col gap-1 text-sm">
				<span class="text-text">
					Track-loss grace (observations) — misses tolerated before lost
				</span>
				<Input
					type="number"
					bind:value={trackLossGraceObservations}
					disabled={active}
				/>
			</label>
		</div>

		<div class="mt-6 flex flex-wrap gap-2">
			{#if !active}
				<Button variant="primary" onclick={startRun} loading={busy}>
					Start
				</Button>
			{:else if runState?.status === 'paused'}
				<Button variant="primary" onclick={resumeRun} loading={busy}>
					Resume
				</Button>
				<Button variant="danger" onclick={stopRun} loading={busy}>
					Stop
				</Button>
			{:else}
				<Button variant="secondary" onclick={pauseRun} loading={busy}>
					Pause
				</Button>
				<Button variant="danger" onclick={stopRun} loading={busy}>
					Stop
				</Button>
			{/if}
			<Button variant="ghost" onclick={refreshStatus}>Refresh</Button>
		</div>
	</SectionCard>

	{#if runState}
		<SectionCard
			title="Run status"
			description={`Status: ${runState.status}${runState.last_event ? ` — ${runState.last_event}` : ''}`}
		>
			{#if runState.error}
				<Alert variant="danger">
					<div class="text-sm">{runState.error}</div>
				</Alert>
			{/if}

			<div class="mt-4 overflow-x-auto">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr class="border-b border-border text-left text-text-muted">
							<th class="px-2 py-2">#</th>
							<th class="px-2 py-2">Speed (µs/s)</th>
							<th class="px-2 py-2">Pulse (µsteps)</th>
							<th class="px-2 py-2">Pause (ms)</th>
							<th class="px-2 py-2">Pulses</th>
							<th class="px-2 py-2">Duration</th>
							<th class="px-2 py-2">Tracked GID</th>
							<th class="px-2 py-2">Status</th>
							<th class="px-2 py-2">Note</th>
						</tr>
					</thead>
					<tbody>
						{#each runState.trials as trial, i (i)}
							<tr
								class="border-b border-border {runState.current_trial_index === i
									? 'bg-primary/5'
									: ''}"
							>
								<td class="px-2 py-2 text-text-muted">{i + 1}</td>
								<td class="px-2 py-2">{trial.params.speed_microsteps_per_second}</td>
								<td class="px-2 py-2">{trial.params.pulse_steps}</td>
								<td class="px-2 py-2">{trial.params.pause_ms}</td>
								<td class="px-2 py-2">{trial.pulses_fired}</td>
								<td class="px-2 py-2">{trial.duration_s.toFixed(2)}s</td>
								<td class="px-2 py-2">{trial.tracked_global_id ?? '—'}</td>
								<td class={`px-2 py-2 font-medium ${trialStatusColor(trial.status)}`}>
									{trial.status}
								</td>
								<td class="px-2 py-2 text-text-muted">{trial.note ?? ''}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</SectionCard>
	{/if}
</div>
