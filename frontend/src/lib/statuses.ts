import type { ChunkStatus } from '../api/types'

export const CHUNK_DOT_COLORS: Record<ChunkStatus, string> = {
  pending: 'bg-gray-400',
  extracted: 'bg-sky-400',
  translated: 'bg-indigo-500',
  verified: 'bg-violet-500',
  terminology_reviewed: 'bg-amber-500',
  approved: 'bg-green-500',
  failed: 'bg-red-500',
}
