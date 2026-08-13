import axios from 'axios'

const axiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Response interceptor: unwrap data, normalize errors
axiosInstance.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const detail = error.response?.data?.detail
    let message = 'An error occurred'
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail)) {
      message = detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : JSON.stringify(item)))
        .join('; ')
    } else if (detail && typeof detail === 'object' && 'msg' in detail) {
      message = String(detail.msg)
    }
    return Promise.reject(new Error(message))
  }
)

// ---- API types (mirroring backend schemas) ----

export interface ArtistSummary {
  id: string
  name: string
  sort_name: string | null
  avatar_path?: string | null
}

export interface AlbumSummary {
  id: string
  title: string
  artist_id: string | null
  year: number | null
  cover_path: string | null
}

export interface Artist {
  id: string
  name: string
  sort_name: string | null
  mbid: string | null
  avatar_path: string | null
  created_at: string
  updated_at: string | null
}

export interface Album {
  id: string
  title: string
  artist_id: string | null
  year: number | null
  mbid: string | null
  cover_path: string | null
  artist: ArtistSummary | null
  track_count: number
  created_at: string
  updated_at: string | null
}

export interface FileTags {
  title: string | null
  artist: string | null
  album: string | null
  has_cover: boolean
}

export interface Track {
  id: string
  title: string
  album_id: string | null
  artist_id: string | null
  track_number: number
  disc_number: number
  duration_ms: number | null
  mbid: string | null
  file_path: string
  file_hash: string | null
  artist: ArtistSummary | null
  artists?: ArtistSummary[]
  album: AlbumSummary | null
  file_tags?: FileTags | null
  created_at: string
  updated_at: string | null
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface AppSettings {
  app_version: string
  music_path: string
  transfer_path: string
  covers_path: string
  data_path?: string
  database_engine: string
  audio_extensions: string[]
  match_confidence_threshold: number
}

export interface ScanJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  root_path: string
  tracks_found: number
  tracks_processed: number
  error_msg: string | null
  created_at: string
  updated_at: string | null
}

export interface MusicSyncResponse {
  changed: boolean
  file_count: number
  fingerprint: string
  job: ScanJob | null
}

export interface Stats {
  total_tracks: number
  total_albums: number
  total_artists: number
  missing_covers: number
  unknown_artists: number
  missing_albums: number
  pending_review: number
  transfer_pending: number
}

export type MetadataIssue =
  | 'transfer'
  | 'missing_album'
  | 'unknown_artist'
  | 'missing_cover'

export type MetadataProvider = 'qqmusic' | 'netease'

export interface MatchCandidate {
  title: string
  artist: string
  album: string
  duration: number
  mbid: string
  album_mbid: string | null
  year: number | null
  confidence: number
  score: number
  cover_url?: string | null
  artist_image_url?: string | null
  artist_images?: { name: string; url: string }[] | null
  provider?: MetadataProvider | null
}

export interface MatchCandidatesResponse {
  track_id: string
  provider: MetadataProvider
  candidates: MatchCandidate[]
}

export interface MatchJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  provider: MetadataProvider | string
  threshold: number
  auto_apply: boolean
  scope?: string
  force_refresh_images?: boolean
  tracks_total: number
  tracks_processed: number
  auto_applied: number
  needs_review: number
  unmatched: number
  failed: number
  error_msg: string | null
  created_at: string
  updated_at: string | null
}

const AUDIO_ACCEPT = '.mp3,.flac,.m4a,.ogg,.wav,.ape,audio/*'

// ---- API client ----

// The response interceptor unwraps `response.data`, so the runtime value is T
// even though axios types it as AxiosResponse<T> - hence the casts.
export const api = {
  get: async <T = any>(url: string, params?: Record<string, any>): Promise<T> => {
    return (await axiosInstance.get(url, { params })) as unknown as T
  },

  post: async <T = any>(
    url: string,
    data?: Record<string, any>,
    params?: Record<string, any>,
  ): Promise<T> => {
    return (await axiosInstance.post(url, data, { params })) as unknown as T
  },

  put: async <T = any>(url: string, data?: Record<string, any>): Promise<T> => {
    return (await axiosInstance.put(url, data)) as unknown as T
  },

  patch: async <T = any>(url: string, data?: Record<string, any>): Promise<T> => {
    return (await axiosInstance.patch(url, data)) as unknown as T
  },

  delete: async <T = any>(url: string): Promise<T> => {
    return (await axiosInstance.delete(url)) as unknown as T
  },

  upload: async <T = any>(url: string, formData: FormData): Promise<T> => {
    return (await axiosInstance.post(url, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })) as unknown as T
  },
}

export { AUDIO_ACCEPT }

export default api
