<script lang="ts">
	import { getContext } from 'svelte';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	import { models as _models, type Model } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { sanitizeResponseContent } from '$lib/utils';

	const i18n = getContext('i18n');

	export let selectedModels: string[] = [''];
	export let atSelectedModel: Model | undefined = undefined;
	export let compact = false;
	export let onAgentSelect: Function = () => {};

	const capabilityLabels: Record<string, string> = {
		web_search: 'Web',
		image_generation: 'Image',
		code_interpreter: 'Code',
		vision: 'Vision',
		terminal: 'Terminal',
		memory: 'Memory',
		file_upload: 'Files'
	};

	const titleCase = (value: string) =>
		value
			.split(/[_-]/)
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');

	const getDescription = (agent: Model | undefined) =>
		agent?.info?.meta?.description?.trim() ||
		$i18n.t('Configured for focused work in this workspace.');

	const getDescriptionHtml = (agent: Model | undefined) =>
		DOMPurify.sanitize(
			marked.parse(sanitizeResponseContent(getDescription(agent)).replaceAll('\n', '<br>'))
		);

	const getCapabilityBadges = (agent: Model | undefined) => {
		const meta = (agent?.info?.meta ?? {}) as Record<string, any>;
		const badges = Object.entries(meta.capabilities ?? {})
			.filter(([, enabled]) => Boolean(enabled))
			.map(([key]) => capabilityLabels[key] ?? titleCase(key));

		if ((meta.toolIds ?? []).length > 0 && !badges.includes('Tools')) {
			badges.push('Tools');
		}

		return badges.slice(0, 3);
	};

	const getProfileImageSrc = (agent: Model | undefined) =>
		`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${agent?.id}&lang=${$i18n.language}`;

	const selectAgent = async (agent: Model) => {
		atSelectedModel = undefined;
		selectedModels = [agent.id];
		await onAgentSelect(agent);
	};

	$: availableAgents = $_models.filter((model) => !(model?.info?.meta?.hidden ?? false));
	$: selectedAgentId =
		atSelectedModel?.id ??
		selectedModels.find(
			(modelId) => modelId && availableAgents.some((agent) => agent.id === modelId)
		) ??
		availableAgents[0]?.id ??
		'';
	$: selectedAgent =
		availableAgents.find((agent) => agent.id === selectedAgentId) ??
		availableAgents[0] ??
		undefined;
</script>

<div
	class={`mx-auto w-full ${compact ? 'max-w-6xl px-4 py-8' : 'max-w-7xl px-3 @2xl:px-10 py-8 @sm:py-10'}`}
>
	<div class="mx-auto max-w-3xl">
		<p class="text-[11px] font-medium uppercase tracking-[0.22em] text-gray-500 dark:text-gray-400">
			{$i18n.t('Agent workspace')}
		</p>
		<h1
			class={`mt-3 font-primary font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-50 ${compact ? 'text-2xl @sm:text-3xl' : 'text-[2rem] @sm:text-[2.45rem]'}`}
		>
			{$i18n.t('Choose an agent')}
		</h1>
		<p class="mt-3 max-w-[68ch] text-sm leading-6 text-gray-600 dark:text-gray-300">
			{$i18n.t(
				'Each agent is configured for a specific kind of work. Pick one, review what it is for, then start the conversation.'
			)}
		</p>
	</div>

	{#if selectedAgent}
		<section
			class="mx-auto mt-6 max-w-6xl rounded-[28px] border border-gray-200/90 bg-white/90 p-5 dark:border-gray-800 dark:bg-gray-900/80"
			aria-label={$i18n.t('Selected agent')}
		>
			<div class="flex flex-col gap-5 @lg:flex-row @lg:items-start @lg:justify-between">
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-3">
						<img
							src={getProfileImageSrc(selectedAgent)}
							alt=""
							class="size-12 rounded-full border border-gray-200 object-cover dark:border-gray-700"
							draggable="false"
							on:error={(e) => {
								e.currentTarget.src = '/favicon.png';
							}}
						/>
						<div class="min-w-0">
							<div
								class="text-xs font-medium uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400"
							>
								{$i18n.t('Selected agent')}
							</div>
							<div class="mt-1 line-clamp-1 text-xl font-medium text-gray-900 dark:text-gray-50">
								{selectedAgent.name}
							</div>
						</div>
					</div>

					<div
						class="mt-4 max-w-[75ch] text-sm leading-6 text-gray-600 dark:text-gray-300 markdown"
					>
						{@html getDescriptionHtml(selectedAgent)}
					</div>
				</div>

				<div class="flex shrink-0 flex-col gap-3 @lg:max-w-56 @lg:items-end">
					<div class="text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t('Ready to start with this agent.')}
					</div>
					<div class="flex flex-wrap gap-2 @lg:justify-end">
						{#each getCapabilityBadges(selectedAgent) as badge}
							<div
								class="rounded-full border border-gray-200 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.16em] text-gray-600 dark:border-gray-700 dark:text-gray-300"
							>
								{badge}
							</div>
						{/each}
					</div>
				</div>
			</div>
		</section>
	{/if}

	<div class="mx-auto mt-6 max-w-6xl">
		{#if availableAgents.length > 0}
			<div class="grid gap-3 @lg:grid-cols-2 @4xl:grid-cols-3">
				{#each availableAgents as agent}
					<button
						type="button"
						class={`group flex h-full flex-col rounded-[24px] border p-4 text-left transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400/70 dark:focus-visible:ring-gray-500/70 ${
							agent.id === selectedAgentId
								? 'border-gray-900 bg-gray-900 text-gray-50 dark:border-gray-100 dark:bg-gray-100 dark:text-gray-900'
								: 'border-gray-200/90 bg-white/75 text-gray-900 hover:bg-white dark:border-gray-800 dark:bg-gray-900/55 dark:text-gray-100 dark:hover:bg-gray-900'
						}`}
						aria-pressed={agent.id === selectedAgentId}
						on:click={() => selectAgent(agent)}
					>
						<div class="flex items-start gap-3">
							<img
								src={getProfileImageSrc(agent)}
								alt=""
								class={`mt-0.5 size-11 shrink-0 rounded-full border object-cover ${
									agent.id === selectedAgentId
										? 'border-white/20 dark:border-black/10'
										: 'border-gray-200 dark:border-gray-700'
								}`}
								draggable="false"
								on:error={(e) => {
									e.currentTarget.src = '/favicon.png';
								}}
							/>

							<div class="min-w-0 flex-1">
								<div class="flex items-start justify-between gap-3">
									<div class="min-w-0">
										<div class="line-clamp-1 text-base font-medium">{agent.name}</div>
										<div
											class={`mt-1 text-[11px] font-medium uppercase tracking-[0.16em] ${
												agent.id === selectedAgentId
													? 'text-gray-300 dark:text-gray-600'
													: 'text-gray-500 dark:text-gray-400'
											}`}
										>
											{$i18n.t('Agent')}
										</div>
									</div>

									{#if agent.id === selectedAgentId}
										<div
											class="rounded-full border border-white/15 px-2 py-1 text-[11px] font-medium uppercase tracking-[0.16em] text-white dark:border-black/10 dark:text-gray-900"
										>
											{$i18n.t('Selected')}
										</div>
									{/if}
								</div>
							</div>
						</div>

						<div
							class={`mt-4 line-clamp-4 text-sm leading-6 markdown ${
								agent.id === selectedAgentId
									? 'text-gray-100 dark:text-gray-800'
									: 'text-gray-600 dark:text-gray-300'
							}`}
						>
							{@html getDescriptionHtml(agent)}
						</div>

						{#if getCapabilityBadges(agent).length > 0}
							<div class="mt-4 flex flex-wrap gap-2">
								{#each getCapabilityBadges(agent) as badge}
									<div
										class={`rounded-full border px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.14em] ${
											agent.id === selectedAgentId
												? 'border-white/15 text-gray-200 dark:border-black/10 dark:text-gray-700'
												: 'border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300'
										}`}
									>
										{badge}
									</div>
								{/each}
							</div>
						{/if}
					</button>
				{/each}
			</div>
		{:else}
			<div
				class="rounded-[24px] border border-dashed border-gray-300 px-5 py-8 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400"
			>
				{$i18n.t('No agents are available yet.')}
			</div>
		{/if}
	</div>
</div>
