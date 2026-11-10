import { proxy } from '../../cloudflare/proxy.js'

// Every /api/* request goes to the backend through the tunnel.
export const onRequest = proxy
