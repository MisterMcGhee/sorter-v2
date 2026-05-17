<script lang="ts">
	import SectionCard from '$lib/components/settings/SectionCard.svelte';

	type Field = {
		key: string;
		type: string;
		default?: string;
		description: string;
	};

	type Section = {
		header: string;
		toml: string;
		description: string;
		fields: Field[];
	};

	const sections: Section[] = [
		{
			header: 'Servo',
			toml: '[servo]',
			description: 'Controls flap servo angles and hardware backend selection.',
			fields: [
				{
					key: 'open_angle',
					type: 'int (0–180)',
					default: '10',
					description: 'Angle in degrees for the open (drop) position.'
				},
				{
					key: 'closed_angle',
					type: 'int (0–180)',
					default: '83',
					description: 'Angle in degrees for the closed (hold) position.'
				},
				{
					key: 'backend',
					type: '"pca9685" | "waveshare"',
					default: '"pca9685"',
					description: 'Servo driver to use. "pca9685" uses the onboard I²C driver; "waveshare" uses the SC bus over USB.'
				},
				{
					key: 'port',
					type: 'string',
					default: 'auto-detected',
					description: 'Serial port for the Waveshare SC bus. Omit to auto-detect. Only used when backend = "waveshare".'
				}
			]
		},
		{
			header: 'Servo Channels',
			toml: '[[servo.channels]]',
			description: 'Per-channel servo configuration. One entry per servo, in layer order. Only used when backend = "waveshare".',
			fields: [
				{
					key: 'id',
					type: 'int | null',
					description: 'SC bus servo ID (1–253). Null skips this slot.'
				},
				{
					key: 'invert',
					type: 'bool',
					default: 'false',
					description: 'Flip the direction of open/closed angles for this servo.'
				}
			]
		},
		{
			header: 'Layers',
			toml: '[layers]',
			description: 'Bin layout — one inner array per physical layer of the tower (bottom to top), each containing bin size strings.',
			fields: [
				{
					key: 'sections',
					type: 'array of arrays',
					description: 'Each element is a layer; each layer is an array of bin-pair arrays like ["medium","medium"]. Defines the physical bin topology.'
				},
				{
					key: 'servo_open_angles',
					type: 'table {layer_index = angle}',
					description: 'Per-layer open angle overrides. Keys are 0-based layer indices.'
				},
				{
					key: 'servo_closed_angles',
					type: 'table {layer_index = angle}',
					description: 'Per-layer closed angle overrides. Keys are 0-based layer indices.'
				}
			]
		},
		{
			header: 'Chute',
			toml: '[chute]',
			description: 'Chute stepper calibration — home pin wiring and bin layout geometry.',
			fields: [
				{
					key: 'home_pin_channel',
					type: 'int',
					default: '3',
					description: 'Digital input channel index on the distribution board where the chute endstop is wired.'
				},
				{
					key: 'first_bin_center',
					type: 'float (degrees)',
					default: '8.25',
					description: 'Angular position of the first bin center after homing completes.'
				},
				{
					key: 'pillar_width_deg',
					type: 'float (degrees)',
					default: '8.25',
					description: 'Angular width consumed by each divider pillar between bins.'
				},
				{
					key: 'endstop_active_high',
					type: 'bool',
					default: 'true',
					description: 'Set to true if the chute endstop input reads high when physically triggered.'
				},
				{
					key: 'operating_speed_microsteps_per_second',
					type: 'int',
					default: '3000',
					description: 'Chute stepper top speed during normal positioning moves.'
				}
			]
		},
		{
			header: 'Carousel',
			toml: '[carousel]',
			description: 'Carousel stepper calibration — home pin wiring.',
			fields: [
				{
					key: 'home_pin_channel',
					type: 'int',
					default: '2',
					description: 'Digital input channel index on the feeder board where the carousel home sensor is wired.'
				},
				{
					key: 'endstop_active_high',
					type: 'bool',
					default: 'false',
					description: 'Set to true if the carousel home sensor reads high when triggered.'
				}
			]
		},
		{
			header: 'Machine Setup',
			toml: '[machine_setup]',
			description: 'Selects the overall machine topology. Changing this requires a full reset and re-home.',
			fields: [
				{
					key: 'type',
					type: '"standard_carousel" | "classification_channel" | "manual_carousel"',
					default: '"standard_carousel"',
					description:
						'"standard_carousel": full FIDA + carousel + classification path. "classification_channel": dedicated C-channel classifier. "manual_carousel": operator places parts directly into the carousel.'
				}
			]
		},
		{
			header: 'Stepper Bindings',
			toml: '[stepper_bindings]',
			description: 'Remaps logical stepper names to physical firmware channel names when the physical wiring does not match the firmware defaults.',
			fields: [
				{
					key: 'carousel',
					type: 'string (physical stepper name)',
					description: 'Override which physical stepper drives the carousel.'
				},
				{
					key: 'c_channel_1',
					type: 'string (physical stepper name)',
					description: 'Override which physical stepper drives C-channel 1.'
				},
				{
					key: 'c_channel_2',
					type: 'string (physical stepper name)',
					description: 'Override which physical stepper drives C-channel 2.'
				},
				{
					key: 'c_channel_3',
					type: 'string (physical stepper name)',
					description: 'Override which physical stepper drives C-channel 3.'
				},
				{
					key: 'chute',
					type: 'string (physical stepper name)',
					description: 'Override which physical stepper drives the distribution chute.'
				}
			]
		},
		{
			header: 'Stepper Direction Inverts',
			toml: '[stepper_direction_inverts]',
			description: 'Flip the logical direction of a stepper without reflashing firmware. Keys are logical stepper names (carousel, c_channel_1, c_channel_2, c_channel_3, chute).',
			fields: [
				{
					key: '<logical_stepper_name>',
					type: 'bool',
					default: 'false',
					description: 'Set to true to invert CW/CCW for that stepper. Example: carousel = true'
				}
			]
		},
		{
			header: 'Stepper Current Overrides',
			toml: '[stepper_current_overrides.<stepper_name>]',
			description: 'Per-stepper TMC driver current settings. Omit to use firmware defaults. Keys are physical or canonical stepper names.',
			fields: [
				{
					key: 'irun',
					type: 'int (0–31)',
					default: '16',
					description: 'Run current register value. Higher = more torque, more heat.'
				},
				{
					key: 'ihold',
					type: 'int (0–31)',
					default: '4',
					description: 'Hold current register value when the stepper is stopped.'
				},
				{
					key: 'ihold_delay',
					type: 'int (0–15)',
					default: '8',
					description: 'Delay (in clock cycles) before current ramps from irun to ihold after a move ends.'
				}
			]
		},
		{
			header: 'Cameras',
			toml: '[cameras]',
			description: 'Camera layout and device index assignments.',
			fields: [
				{
					key: 'layout',
					type: '"default" | "split_feeder"',
					default: '"default"',
					description:
						'"default": single feeder camera + classification cameras. "split_feeder": separate camera per C-channel + carousel.'
				},
				{
					key: 'feeder',
					type: 'int',
					description: 'OpenCV device index for the feeder camera. Used in "default" layout.'
				},
				{
					key: 'carousel',
					type: 'int | string (URL)',
					description: 'Device index or MJPEG URL for the carousel/classification camera.'
				},
				{
					key: 'classification_top',
					type: 'int | string (URL)',
					description: 'Device index or URL for the top classification camera.'
				},
				{
					key: 'classification_bottom',
					type: 'int | string (URL)',
					description: 'Device index or URL for the bottom classification camera.'
				},
				{
					key: 'c_channel_2',
					type: 'int',
					description: 'Device index for the C-channel 2 camera. Only used in "split_feeder" layout.'
				},
				{
					key: 'c_channel_3',
					type: 'int',
					description: 'Device index for the C-channel 3 camera. Only used in "split_feeder" layout.'
				}
			]
		},
		{
			header: 'Camera Capture Modes',
			toml: '[camera_capture_modes.<role>]',
			description: 'Per-camera capture settings. Role matches camera keys from [cameras] (e.g. feeder, carousel). Strongly recommended on Linux to force MJPG and avoid USB bandwidth exhaustion.',
			fields: [
				{
					key: 'fourcc',
					type: 'string',
					description: 'Four-character code for the capture format. "MJPG" is strongly recommended on Linux multi-cam setups.'
				},
				{
					key: 'width',
					type: 'int',
					description: 'Capture width in pixels.'
				},
				{
					key: 'height',
					type: 'int',
					description: 'Capture height in pixels.'
				},
				{
					key: 'fps',
					type: 'int',
					description: 'Target capture frame rate.'
				}
			]
		},
		{
			header: 'Camera Picture Settings',
			toml: '[camera_picture_settings.<role>]',
			description: 'Per-camera image transform settings applied after capture.',
			fields: [
				{
					key: 'rotation',
					type: 'int (0, 90, 180, 270)',
					default: '0',
					description: 'Clockwise rotation in degrees applied to every captured frame.'
				},
				{
					key: 'flip_horizontal',
					type: 'bool',
					default: 'false',
					description: 'Mirror the image left-to-right.'
				},
				{
					key: 'flip_vertical',
					type: 'bool',
					default: 'false',
					description: 'Flip the image top-to-bottom.'
				}
			]
		},
		{
			header: 'GPIO LEDs',
			toml: '[[gpio_leds]]',
			description: 'Digital output pins that are driven HIGH on boot and LOW on shutdown. One entry per pin. Useful for status LEDs wired to the Basically or SKR Pico boards.',
			fields: [
				{
					key: 'board',
					type: '"feeder" | "distribution" | "any"',
					description: 'Which board to target. "any" applies the same pin index to all connected boards.'
				},
				{
					key: 'pin',
					type: 'int (≥ 0)',
					description: '0-based digital output channel index on the target board.'
				}
			]
		}
	];
</script>

<div class="mx-auto max-w-3xl px-4 py-8 sm:px-6">
	<div class="mb-6">
		<h1 class="text-xl font-bold text-text">machine.toml Reference</h1>
		<p class="mt-2 text-sm text-text-muted">
			All fields for the machine-specific config file. Set
			<code class="bg-surface px-1 py-0.5 font-mono text-xs">MACHINE_SPECIFIC_PARAMS_PATH</code>
			to point to your copy.
		</p>
	</div>

	<div class="flex flex-col gap-5">
		{#each sections as section}
			<SectionCard title={section.header} description={section.description}>
				<div class="mb-3 font-mono text-xs text-text-muted">{section.toml}</div>
				<div class="border border-border">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border bg-surface">
								<th class="px-3 py-2 text-left text-xs font-semibold tracking-wider text-text-muted uppercase">Key</th>
								<th class="px-3 py-2 text-left text-xs font-semibold tracking-wider text-text-muted uppercase">Type</th>
								<th class="px-3 py-2 text-left text-xs font-semibold tracking-wider text-text-muted uppercase">Default</th>
								<th class="px-3 py-2 text-left text-xs font-semibold tracking-wider text-text-muted uppercase">Description</th>
							</tr>
						</thead>
						<tbody>
							{#each section.fields as field, i}
								<tr class={i % 2 === 0 ? 'bg-bg' : 'bg-surface'}>
									<td class="px-3 py-2 align-top font-mono text-xs text-text">{field.key}</td>
									<td class="px-3 py-2 align-top font-mono text-xs text-text-muted whitespace-nowrap">{field.type}</td>
									<td class="px-3 py-2 align-top font-mono text-xs text-text-muted whitespace-nowrap">{field.default ?? '—'}</td>
									<td class="px-3 py-2 align-top text-sm text-text-muted">{field.description}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</SectionCard>
		{/each}
	</div>
</div>
