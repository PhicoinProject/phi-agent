import type { Usage } from '@phi/shared/gateway-events'

export { usageFromTick } from '@phi/shared/usage-tick'

export const ZERO: Usage = { calls: 0, input: 0, output: 0, total: 0 }
