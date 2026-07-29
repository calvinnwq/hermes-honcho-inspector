declare module "@hermes/plugin-sdk" {
  export interface PluginContribution {
    id: string
    area: string
    title?: string
    order?: number
    render?: () => unknown
    data?: unknown
  }

  export interface PluginContext {
    readonly source: string
    register(contribution: PluginContribution): () => void
    registerMany(contributions: PluginContribution[]): () => void
    rest<T>(path: string, options?: { method?: string; body?: unknown; timeoutMs?: number }): Promise<T>
  }

  export interface HermesPlugin {
    id: string
    name?: string
    defaultEnabled?: boolean
    register(ctx: PluginContext): void
  }

  export const ROUTES_AREA: string
  export const SIDEBAR_NAV_AREA: string
  export const PALETTE_AREA: string

  export interface ReadableAtom<T> {
    get(): T
    subscribe(listener: (value: T) => void): () => void
  }

  export const host: {
    state: {
      profile: ReadableAtom<string>
    }
    navigate(path: string): void
  }

  export function useValue<T>(store: ReadableAtom<T>): T

  export function useQuery<T>(options: {
    queryKey: unknown[]
    queryFn: () => Promise<T>
    retry?: boolean
  }): {
    data: T | undefined
    isLoading: boolean
    isError: boolean
    isFetching: boolean
    refetch(): Promise<unknown>
  }

  export const Button: unknown
  export const ErrorState: unknown
  export const Loader: unknown
  export const StatusDot: unknown
}

declare module "react" {
  export function useState<T>(initialValue: T): [T, (value: T) => void]
  export function useEffect(effect: () => void, dependencies?: unknown[]): void
}

declare module "react/jsx-runtime" {
  export function jsx(type: unknown, props: Record<string, unknown>, key?: string): unknown
  export function jsxs(type: unknown, props: Record<string, unknown>, key?: string): unknown
}
