<script lang="ts">
	import { config, models as _models, temporaryChatEnabled } from '$lib/stores';
	import { onMount, getContext } from 'svelte';

	import { fade } from 'svelte/transition';

	import AgentHome from './AgentHome.svelte';
	import Suggestions from './Suggestions.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';

	const i18n = getContext('i18n');

	export let modelIds = [];
	export let models = [];
	export let atSelectedModel;
	export let focusComposer: Function = () => {};

	export let onSelect = (e) => {};

	let mounted = false;

	$: models = modelIds.map((id) => $_models.find((m) => m.id === id));
	$: activeModel = atSelectedModel ?? models[models.length - 1];

	onMount(() => {
		mounted = true;
	});
</script>

{#key mounted}
	<div class="m-auto w-full">
		{#if $temporaryChatEnabled}
			<Tooltip
				content={$i18n.t("This chat won't appear in history and your messages will not be saved.")}
				className="w-full flex justify-center pt-4"
				placement="top"
			>
				<div class="flex items-center gap-2 text-gray-500 text-base my-2 w-fit">
					<EyeSlash strokeWidth="2.5" className="size-5" />{$i18n.t('Temporary Chat')}
				</div>
			</Tooltip>
		{/if}

		<AgentHome
			bind:selectedModels={modelIds}
			bind:atSelectedModel
			compact={true}
			onAgentSelect={async () => {
				await focusComposer();
			}}
		/>

		<div
			class="mx-auto w-full max-w-3xl px-4 pb-4 font-primary"
			in:fade={{ duration: 200, delay: 300 }}
		>
			<Suggestions
				className="grid grid-cols-1 @lg:grid-cols-2"
				suggestionPrompts={atSelectedModel?.info?.meta?.suggestion_prompts ??
					activeModel?.info?.meta?.suggestion_prompts ??
					$config?.default_prompt_suggestions ??
					[]}
				{onSelect}
			/>
		</div>
	</div>
{/key}
