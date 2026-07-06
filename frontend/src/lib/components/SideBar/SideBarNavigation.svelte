<script lang="ts">
	import { navData } from '$lib/components/SideBar/navData';

	import SideBarItem from '$lib/components/SideBar/SideBarItem.svelte';
	import SideBarCategory from '$lib/components/SideBar/SideBarCategory.svelte';
	import { Accordion } from '@skeletonlabs/skeleton-svelte';
	import { page } from '$app/state';
	import { URL_MODEL_MAP } from '$lib/utils/crud';
	import { driverInstance } from '$lib/utils/stores';

	const user = $derived(page.data.user);
	// focus_folder_id is echoed by current-user, so it is always in sync with
	// the (possibly focus-scoped) permissions of the same payload
	const focusActive = $derived(Boolean(user?.focus_folder_id));
	const rootPermissions = $derived(
		new Set<string>(user?.domain_permissions?.[user?.root_folder_id] ?? [])
	);

	function requiredPermissions(subItem): string[] | null {
		if (subItem.permissions) return subItem.permissions;
		const segment = subItem.href.split('/')[1];
		if (Object.hasOwn(URL_MODEL_MAP, segment)) {
			return [`view_${URL_MODEL_MAP[segment].name}`];
		}
		return null;
	}

	const navItems = $derived.by(() =>
		navData.items
			.map((item) => {
				// Check and filter the sub-items based on user permissions
				const filteredSubItems = item.items.filter((subItem) => {
					if (subItem.exclude) {
						return user?.roles?.some((role: string) => !subItem.exclude.includes(role)) ?? false;
					}
					const required = requiredPermissions(subItem);
					if (!required) return false;
					// Entries managing root-homed objects (users, libraries, settings...)
					// are unreachable while focused on a domain: hide them
					if (subItem.scope === 'global' && focusActive) {
						return required.some((permission) => rootPermissions.has(permission));
					}
					return required.some(
						(permission) => user?.permissions && Object.hasOwn(user.permissions, permission)
					);
				});

				return {
					...item,
					items: filteredSubItems
				};
			})
			.filter((item) => item.items.length > 0)
	); // Filter out items with no sub-items

	import { lastAccordionItem } from '$lib/utils/stores';
	interface Props {
		sideBarVisibleItems: Record<string, boolean>;
	}

	let { sideBarVisibleItems }: Props = $props();

	function handleValueChange(details: { value: string[] }) {
		$lastAccordionItem = details.value;
		setTimeout(() => {
			$driverInstance?.moveNext();
		}, 0);
	}
</script>

<nav class="grow scrollbar">
	<Accordion
		value={$lastAccordionItem}
		onValueChange={handleValueChange}
		collapsible
		class="space-y-4"
	>
		{#each navItems as item}
			{#if sideBarVisibleItems && sideBarVisibleItems[item.name] !== false}
				<Accordion.Item value={item.name} id={item.name.toLowerCase().replace(' ', '-')}>
					<Accordion.ItemTrigger class="flex w-full items-center cursor-pointer">
						<SideBarCategory {item} />
						<Accordion.ItemIndicator
							class="transition-transform duration-200 data-[state=open]:rotate-0 data-[state=closed]:-rotate-90 text-primary-700-300"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="14px"
								height="14px"
								viewBox="0 0 448 512"
								fill="currentColor"
							>
								<path
									d="M201.4 374.6c12.5 12.5 32.8 12.5 45.3 0l160-160c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L224 306.7 86.6 169.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l160 160z"
								/>
							</svg>
						</Accordion.ItemIndicator>
					</Accordion.ItemTrigger>
					<Accordion.ItemContent class="space-y-2">
						<SideBarItem item={item.items} {sideBarVisibleItems} />
					</Accordion.ItemContent>
				</Accordion.Item>
			{/if}
		{/each}
	</Accordion>
</nav>
